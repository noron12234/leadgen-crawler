"""
Yourator 爬蟲
- 使用公開的 /api/v2/companies API
- 補充台灣科技新創公司清單
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import logging
from crawlers.utils import request_with_retry

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def crawl_yourator_companies(timeout: int = 20) -> list[dict]:
    """
    從 Yourator 公開 API 取得公司清單

    Returns:
        公司清單，每筆含：source, cust_name, industry, address, website
    """
    url = "https://www.yourator.co/api/v2/companies"
    try:
        resp = request_with_retry(url, headers=HEADERS, timeout=timeout)
        data = resp.json()
    except Exception as e:
        logger.error(f"Yourator API 失敗：{e}")
        return []

    # data 可能是 list 或 dict
    if isinstance(data, list):
        raw_companies = data
    elif isinstance(data, dict):
        raw_companies = data.get("companies") or data.get("data") or []
    else:
        logger.warning(f"Yourator API 回傳未知格式：{type(data)}")
        return []

    logger.info(f"Yourator 取得 {len(raw_companies)} 家公司")

    companies = []
    for c in raw_companies:
        name = c.get("brand") or c.get("name") or c.get("brand_name") or ""
        if not name:
            continue

        path = c.get("path") or c.get("slug") or ""
        website = f"https://www.yourator.co/companies/{path}" if path else ""

        # industry 可能是 dict {"id": 1, "name": "網路"}
        raw_ind = c.get("category") or c.get("industry") or {}
        industry = raw_ind.get("name", "") if isinstance(raw_ind, dict) else str(raw_ind)

        # address/location 可能是 dict {"code": "TPE", "name": "Taipei City"}
        raw_loc = c.get("location") or c.get("city") or {}
        address = raw_loc.get("name", "") if isinstance(raw_loc, dict) else str(raw_loc)

        # employee_count 可能是 dict
        raw_emp = c.get("employee_count") or c.get("size") or ""
        employee_count = (
            raw_emp.get("name", "") if isinstance(raw_emp, dict) else str(raw_emp)
        )

        companies.append(
            {
                "source": "yourator",
                "cust_id": f"yourator_{path or name}",
                "cust_name": name,
                "industry": industry,
                "employee_count": employee_count,
                "address": address,
                "phone": "",
                "hr_name": "",
                "welfare_tags": [],
                "website": website,
                "has_snack_benefit": False,
            }
        )

    return companies


# ── 快速測試 ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("=== Yourator 爬蟲測試 ===\n")
    results = crawl_yourator_companies()

    for i, c in enumerate(results[:10], 1):
        print(f"{i}. {c['cust_name']} | {c['industry']} | {c['address']}")
        print(f"   Yourator: {c['website']}")

    print(f"\n共取得 {len(results)} 家公司")
