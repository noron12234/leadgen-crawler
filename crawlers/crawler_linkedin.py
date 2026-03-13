"""
LinkedIn 爬蟲（透過 ByCrawl REST API）
- 搜尋行政/總務相關職缺 → 有辦公室的公司 = 潛在零食客戶
- 人物搜尋 → 找到決策者（總務、行政、Office Manager）
- 取得公司 LinkedIn 頁面、員工數、產業描述
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import requests
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bycrawl.com"

# 搜尋這些關鍵字 → 有辦公室管理需求的公司
SEARCH_KEYWORDS = [
    "行政助理",
    "總務",
    "辦公室管理",
    "Office Administrator",
]

# 地區對照（104 area code → LinkedIn location）
AREA_TO_LOCATION = {
    "6001001000": "Taipei",
    "6001002000": "New Taipei",
    "6001003000": "Taoyuan",
    "6001006000": "Taichung",
}


def _get_api_key() -> str:
    key = os.environ.get("BYCRAWL_API_KEY", "")
    if not key:
        # 嘗試從 .env 載入
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.environ.get("BYCRAWL_API_KEY", "")
        except ImportError:
            pass
    return key


def _api_get(endpoint: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
    api_key = _get_api_key()
    if not api_key:
        logger.error("BYCRAWL_API_KEY 未設定")
        return None

    headers = {"x-api-key": api_key}
    url = f"{BASE_URL}{endpoint}"

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 429:
            logger.warning(f"ByCrawl 速率限制，等待 5 秒後重試: {endpoint}")
            time.sleep(5)
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception:
                pass
        logger.error(f"ByCrawl API {resp.status_code}: {endpoint} → {e}")
        return None
    except Exception as e:
        logger.error(f"ByCrawl API 連線失敗: {endpoint} → {e}")
        return None


def search_linkedin_jobs(
    keyword: str,
    location: str = "Taiwan",
    count: int = 50,
) -> list[dict]:
    """搜尋 LinkedIn 職缺"""
    data = _api_get("/linkedin/jobs/search", {
        "query": keyword,
        "location": location,
        "count": count,
    })
    if not data or not data.get("success"):
        return []

    jobs = data.get("data", {}).get("jobs", [])
    logger.info(f"LinkedIn 搜尋「{keyword}」→ {len(jobs)} 筆職缺")
    return jobs


def get_company_profile(company_id: str) -> Optional[dict]:
    """取得 LinkedIn 公司資料"""
    data = _api_get(f"/linkedin/companies/{company_id}")
    if not data or not data.get("success"):
        return None
    return data.get("data")


def _guess_company_slug(company_name: str) -> str:
    """從公司名稱猜測 LinkedIn slug（小寫、去空白、去特殊字）"""
    slug = company_name.lower().strip()
    # 移除常見後綴
    for suffix in [" co., ltd.", " co.,ltd.", " ltd.", " inc.", " corp.",
                   " corporation", " group", " 股份有限公司", " 有限公司"]:
        slug = slug.replace(suffix, "")
    # 只保留英數和連字號
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def crawl_linkedin_companies(
    area: str = "6001001000",
    max_results_per_keyword: int = 50,
    delay: float = 1.0,
) -> list[dict]:
    """
    從 LinkedIn 職缺搜尋中擷取公司名單

    策略：搜尋行政/總務相關職缺 → 有辦公室的公司 → 零食飲料潛在客戶

    Args:
        area: 104 地區碼（用來對照 LinkedIn 地點）
        max_results_per_keyword: 每個關鍵字最多抓幾筆
        delay: API 呼叫間隔秒數

    Returns:
        公司清單，格式與其他爬蟲一致
    """
    api_key = _get_api_key()
    if not api_key:
        logger.error("LinkedIn 爬蟲需要 BYCRAWL_API_KEY，請在 .env 中設定")
        return []

    location = AREA_TO_LOCATION.get(area, "Taiwan")

    # 1) 搜尋所有關鍵字的職缺
    all_jobs = []
    for kw in SEARCH_KEYWORDS:
        jobs = search_linkedin_jobs(kw, location=location, count=max_results_per_keyword)
        all_jobs.extend(jobs)
        if delay > 0:
            time.sleep(delay)

    if not all_jobs:
        logger.warning("LinkedIn 未找到任何職缺")
        return []

    logger.info(f"LinkedIn 共取得 {len(all_jobs)} 筆職缺（含重複）")

    # 2) 去重：按公司名稱分組
    company_map: dict[str, dict] = {}
    for job in all_jobs:
        name = (job.get("company") or "").strip()
        if not name:
            continue

        key = name.lower()
        if key not in company_map:
            company_map[key] = {
                "name": name,
                "jobs": [],
                "locations": set(),
            }
        company_map[key]["jobs"].append(job.get("title", ""))
        loc = job.get("location", "")
        if loc:
            company_map[key]["locations"].add(loc)

    logger.info(f"LinkedIn 共 {len(company_map)} 家不重複公司")

    # 3) 嘗試取得公司 profile（補齊員工數、描述）
    companies = []
    for key, info in company_map.items():
        name = info["name"]
        slug = _guess_company_slug(name)

        employee_count = ""
        description = ""
        company_linkedin_url = ""
        headquarters = ""

        if slug and len(slug) >= 2:
            profile = get_company_profile(slug)
            if profile:
                employee_count = str(profile.get("employeeCount") or profile.get("size") or "")
                description = profile.get("description", "")[:200]
                company_linkedin_url = profile.get("website") or f"https://www.linkedin.com/company/{slug}"
                headquarters = profile.get("headquarters") or ""
                logger.info(f"  ✓ {name} → {employee_count} 人")
            # 避免 rate limit
            time.sleep(max(delay, 1.5))

        # 地點：優先用 profile 的 headquarters，其次用職缺的 location
        address = headquarters
        if not address and info["locations"]:
            # 取第一個 location
            address = next(iter(info["locations"]))

        if not company_linkedin_url and slug:
            company_linkedin_url = f"https://www.linkedin.com/company/{slug}"

        job_titles = ", ".join(info["jobs"][:3])
        if len(info["jobs"]) > 3:
            job_titles += f" ...等 {len(info['jobs'])} 筆"

        companies.append({
            "source": "linkedin",
            "cust_id": f"linkedin_{slug or key}",
            "cust_name": name,
            "industry": "",
            "employee_count": employee_count,
            "address": address,
            "phone": "",
            "hr_name": "",
            "email": "",
            "job_url": "",
            "company_url": company_linkedin_url,
            "welfare_tags": [],
            "website": company_linkedin_url,
            "has_snack_benefit": False,
            "description": description,
            "job_titles": job_titles,
        })

    logger.info(f"LinkedIn 爬蟲完成：{len(companies)} 家公司")
    return companies


# ══════════════════════════════════════════════════════
# 人物搜尋
# ══════════════════════════════════════════════════════

def search_linkedin_people(
    keyword: str,
    count: int = 25,
) -> list[dict]:
    """
    搜尋 LinkedIn 人物

    Args:
        keyword: 搜尋關鍵字（僅支援英文，如 engineer, office manager, procurement）
        count: 最多幾筆結果

    Returns:
        人物清單
    """
    data = _api_get("/linkedin/users/search", {
        "query": keyword,
        "count": count,
    })
    if not data or not data.get("success"):
        # 備用：嘗試不同的 endpoint 格式
        data = _api_get("/linkedin/users", {
            "query": keyword,
            "count": count,
        })
        if not data or not data.get("success"):
            return []

    users = data.get("data", {}).get("users", [])
    logger.info(f"LinkedIn 人物搜尋「{keyword}」→ {len(users)} 人")

    people = []
    for u in users:
        name = u.get("name", "").strip()
        if not name:
            continue

        people.append({
            "username": u.get("username", ""),
            "name": name,
            "location": u.get("location", ""),
            "companies": u.get("companies", ""),
            "education": u.get("education", ""),
            "profile_url": u.get("profileUrl", ""),
            "profile_pic": u.get("profilePic", ""),
        })

    return people


def get_linkedin_person_detail(username: str) -> Optional[dict]:
    """
    取得 LinkedIn 個人詳細資料

    Returns:
        含 headline, experience, followers 等欄位的 dict
    """
    data = _api_get(f"/linkedin/users/{username}")
    if not data or not data.get("success"):
        return None

    p = data.get("data", {})
    return {
        "username": p.get("username", ""),
        "name": p.get("name", ""),
        "headline": p.get("headline", ""),
        "location": p.get("location", ""),
        "about": p.get("about", ""),
        "followers": p.get("followers"),
        "connections": p.get("connections"),
        "profile_pic": p.get("profilePic", ""),
        "experience": [
            {
                "company": exp.get("company", ""),
                "start_date": exp.get("startDate"),
                "end_date": exp.get("endDate"),
            }
            for exp in (p.get("experience") or [])
        ],
        "job_titles": p.get("jobTitles", []),
        "profile_url": f"https://www.linkedin.com/in/{p.get('username', '')}",
    }


# ── 快速測試 ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 載入 .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    print("=== LinkedIn 爬蟲測試 ===\n")
    results = crawl_linkedin_companies(area="6001001000", max_results_per_keyword=10, delay=1.0)

    for i, c in enumerate(results[:15], 1):
        print(f"{i}. {c['cust_name']}")
        print(f"   員工數: {c['employee_count'] or '未知'} | 地點: {c['address']}")
        print(f"   職缺: {c['job_titles']}")
        print(f"   LinkedIn: {c['company_url']}")
        print()

    print(f"\n共取得 {len(results)} 家公司")
