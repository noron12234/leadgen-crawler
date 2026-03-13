"""
官網 Email 補充模組
- 從公司官網首頁掃描 mailto: 連結和 email pattern
- 補充 104 沒有抓到的 20% email
- 不需要登入，只抓公開首頁
"""
import re
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# email 正則（寬鬆版，從 HTML 中提取）
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
)

# 要排除的 email（常見無用 email）
EXCLUDE_PATTERNS = [
    r'example\.com$',
    r'test\.com$',
    r'domain\.com$',
    r'email\.com$',
    r'sentry\.io$',
    r'w3\.org$',
    r'schema\.org$',
    r'google\.com$',
    r'facebook\.com$',
    r'twitter\.com$',
    r'wixpress\.com$',
    r'\.png$',
    r'\.jpg$',
    r'\.gif$',
    r'\.svg$',
    r'\.css$',
    r'\.js$',
]


def _is_useful_email(email: str) -> bool:
    """判斷 email 是否有用（排除網站模板、圖片 URL 等）"""
    email_lower = email.lower()
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, email_lower):
            return False
    # 至少要有 2 個字元的 local part
    local = email_lower.split("@")[0]
    if len(local) < 2:
        return False
    return True


def scan_website_for_email(url: str, timeout: float = 8.0) -> list[str]:
    """
    掃描單一官網首頁，提取所有 email

    Args:
        url: 公司官網 URL
        timeout: 請求超時秒數

    Returns:
        找到的 email 列表（去重、排除無用的）
    """
    if not url:
        return []

    # 確保有 http 前綴
    if not url.startswith("http"):
        url = "https://" + url

    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            logger.debug(f"官網 {url} 回傳 {resp.status_code}")
            return []

        html = resp.text

        # 方法 1: 從 mailto: 連結提取
        mailto_emails = re.findall(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', html)

        # 方法 2: 從整個 HTML 中提取 email pattern
        all_emails = EMAIL_PATTERN.findall(html)

        # 合併、去重、過濾
        combined = set(mailto_emails + all_emails)
        useful = [e for e in combined if _is_useful_email(e)]

        # mailto 來的優先排在前面
        mailto_set = set(e.lower() for e in mailto_emails)
        useful.sort(key=lambda e: (0 if e.lower() in mailto_set else 1, e))

        if useful:
            logger.info(f"官網 {url} 找到 {len(useful)} 個 email：{useful[:3]}")

        return useful

    except requests.exceptions.Timeout:
        logger.debug(f"官網 {url} 超時")
        return []
    except requests.exceptions.ConnectionError:
        logger.debug(f"官網 {url} 連線失敗")
        return []
    except Exception as e:
        logger.debug(f"官網 {url} 掃描失敗：{e}")
        return []


def scan_and_update_db(max_workers: int = 5) -> dict:
    """
    批次掃描：從 DB 取出有官網但沒 email 的公司，掃描官網補充 email

    Returns:
        {"scanned": int, "found": int, "updated": int}
    """
    from database.db import get_all_companies, get_connection, init_db

    init_db()
    companies = get_all_companies()

    # 篩選：有官網、沒 email 的公司
    targets = [
        c for c in companies
        if c.get("website") and (not c.get("email") or "@" not in c.get("email", ""))
    ]

    if not targets:
        logger.info("沒有需要補充 email 的公司（全部都有 email 或沒有官網）")
        return {"scanned": 0, "found": 0, "updated": 0}

    logger.info(f"開始掃描 {len(targets)} 家公司的官網...")

    found_count = 0
    updated_count = 0

    def _scan(company):
        emails = scan_website_for_email(company["website"])
        return company, emails

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_scan, c): c for c in targets}
        for future in as_completed(future_map):
            try:
                company, emails = future.result()
                if emails:
                    results.append((company, emails[0]))
            except Exception as e:
                logger.debug(f"掃描失敗：{e}")

    # 寫入 DB
    if results:
        with get_connection() as conn:
            for company, email in results:
                conn.execute(
                    "UPDATE companies SET email = ? WHERE id = ? AND (email IS NULL OR email = '')",
                    (email, company["id"]),
                )
                updated_count += 1
            conn.commit()
        found_count = len(results)

    logger.info(f"官網掃描完成：掃描 {len(targets)} 家，找到 {found_count} 個 email，更新 {updated_count} 筆")
    return {"scanned": len(targets), "found": found_count, "updated": updated_count}


# ── 快速測試 ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 測試單一官網
    test_urls = [
        "https://www.104.com.tw",
        "https://www.cake.me",
    ]
    for url in test_urls:
        emails = scan_website_for_email(url)
        print(f"{url} → {emails}")
