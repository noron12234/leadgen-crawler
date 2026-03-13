"""
Cake.me 爬蟲
- 從職缺搜尋頁的 __NEXT_DATA__ 取公司名稱 + 完整門牌地址
- 補充 104 沒有的新創公司
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import re
import json
import logging
from typing import Optional
from crawlers.utils import request_with_retry

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def _extract_next_data(html: str) -> Optional[dict]:
    """從 HTML 中提取 __NEXT_DATA__ JSON"""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _parse_geo(geo: dict) -> str:
    """從 geo 物件組合完整地址"""
    if not geo:
        return ""
    parts = []
    if geo.get("stateName"):
        parts.append(geo["stateName"])
    if geo.get("regionL"):
        parts.append(geo["regionL"])
    if geo.get("streetAddress"):
        parts.append(geo["streetAddress"])
    return ", ".join(parts)


def crawl_cake_jobs(keyword: str = "HR", location: str = "taipei", timeout: int = 30) -> list[dict]:
    """
    搜尋 Cake.me 職缺，從 SSR 資料取公司清單

    Args:
        keyword: 搜尋關鍵字
        location: 地點
        timeout: 請求逾時秒數（Cake 可能較慢）

    Returns:
        公司清單，每筆含：source, cust_name, address, path（公司URL）
    """
    url = f"https://www.cake.me/jobs?q={keyword}&location={location}"
    try:
        resp = request_with_retry(url, headers=HEADERS, timeout=timeout)
    except Exception as e:
        logger.error(f"Cake 請求失敗：{e}")
        return []

    nd = _extract_next_data(resp.text)
    if not nd:
        logger.warning("Cake：找不到 __NEXT_DATA__")
        return []

    state = nd.get("props", {}).get("pageProps", {}).get("initialState", {})
    entities = state.get("jobSearch", {}).get("entityByPathId", {})

    if not entities:
        logger.warning("Cake：jobSearch.entityByPathId 為空")
        return []

    logger.info(f"Cake 取得 {len(entities)} 筆職缺 SSR 資料")

    seen_companies: set[str] = set()
    companies: list[dict] = []

    for job in entities.values():
        page = job.get("page") or {}
        company_path = page.get("path", "")
        company_name = page.get("name", "")

        if not company_name or company_path in seen_companies:
            continue
        seen_companies.add(company_path)

        geo = page.get("geo", {})
        address = _parse_geo(geo)

        companies.append(
            {
                "source": "cake",
                "cust_id": f"cake_{company_path}",
                "cust_name": company_name,
                "industry": "",
                "employee_count": "",
                "address": address,
                "phone": "",
                "hr_name": "",
                "welfare_tags": [],
                "website": f"https://www.cake.me/companies/{company_path}" if company_path else "",
                "has_snack_benefit": False,
            }
        )

    logger.info(f"Cake 去重後 {len(companies)} 家公司")
    return companies


# ── 快速測試 ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("=== Cake.me 爬蟲測試 ===\n")
    results = crawl_cake_jobs(keyword="HR", location="taipei")

    for i, c in enumerate(results, 1):
        print(f"{i}. {c['cust_name']}")
        print(f"   地址：{c['address']}")
        print(f"   Cake 頁：{c['website']}")
        print()

    print(f"共取得 {len(results)} 家公司")
