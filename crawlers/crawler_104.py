"""
104 人力銀行爬蟲
- 用零食/飲料/伙食福利碼篩選目標公司
- 抓取公司電話、HR 姓名、地址
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import time
import logging
from typing import Optional
from crawlers.utils import request_with_retry

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}

# 零食/飲料/伙食相關福利碼
SNACK_WELFARE_CODES = ["wf27", "wf19", "wf18"]

# 所有福利碼對照表
WELFARE_CODES = {
    "wf1": "員工旅遊",
    "wf2": "三節獎金",
    "wf3": "年終獎金",
    "wf7": "彈性上下班",
    "wf8": "在家上班",
    "wf9": "週休二日",
    "wf18": "餐費補助",
    "wf19": "伙食津貼",
    "wf26": "健身補助",
    "wf27": "下午茶/零食飲料",
    "wf28": "慶生",
    "wf29": "娛樂設施",
}


def search_jobs(
    welfare_code: str = "wf27",
    area: str = "6001001000",  # 台北市
    page: int = 1,
    per_page: int = 30,
) -> list[dict]:
    """
    用福利碼篩選職缺清單
    回傳原始 job list
    """
    url = "https://www.104.com.tw/jobs/search/api/jobs"
    params = {
        "ro": "0",
        "area": area,
        "order": "15",
        "asc": "0",
        "page": str(page),
        "perPage": str(per_page),
        "welfare": welfare_code,
        "s9": "1",
    }
    headers = {**HEADERS, "Referer": "https://www.104.com.tw/jobs/search/"}

    try:
        resp = request_with_retry(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        raw = data.get("data", {})
        jobs = raw.get("list", []) if isinstance(raw, dict) else raw
        total = data.get("metadata", {}).get("total", 0)
        logger.info(f"搜尋 {welfare_code} 第{page}頁：取得 {len(jobs)} 筆，共 {total} 筆")
        return jobs
    except Exception as e:
        logger.error(f"search_jobs 失敗：{e}")
        return []


def get_company_detail(cust_id: str) -> Optional[dict]:
    """
    取得公司詳細資訊（電話、HR姓名、地址等）
    回傳 data 欄位的內容
    """
    url = f"https://www.104.com.tw/company/ajax/content/{cust_id}"
    headers = {
        **HEADERS,
        "Referer": f"https://www.104.com.tw/company/{cust_id}",
    }
    try:
        resp = request_with_retry(url, headers=headers, timeout=10)
        return resp.json().get("data", {})
    except Exception as e:
        logger.error(f"get_company_detail {cust_id} 失敗：{e}")
        return None


def get_job_detail(job_id: str, job_url: str) -> Optional[dict]:
    """
    取得職缺詳細資訊，含 contact.email（80% 填充率）
    回傳 data.contact 欄位
    """
    url = f"https://www.104.com.tw/job/ajax/content/{job_id}"
    headers = {**HEADERS, "Referer": job_url}
    try:
        resp = request_with_retry(url, headers=headers, timeout=10)
        return resp.json().get("data", {}).get("contact", {}) or {}
    except Exception as e:
        logger.error(f"get_job_detail {job_id} 失敗：{e}")
        return None


def extract_cust_id(job: dict) -> Optional[str]:
    """從職缺 JSON 解出公司 ID"""
    link = job.get("link", {})
    if isinstance(link, dict):
        cust_url = link.get("cust", "")
        if "/company/" in cust_url:
            return cust_url.split("/company/")[-1].split("?")[0]
    return job.get("custNo")


def extract_job_id(job: dict) -> tuple[str, str]:
    """從職缺 JSON 解出 job_id 和完整 job_url"""
    link = job.get("link", {})
    if isinstance(link, dict):
        job_path = link.get("job", "")
        if "/job/" in job_path:
            job_id = job_path.split("/job/")[-1].split("?")[0]
            # 補齊完整 URL
            if job_path.startswith("http"):
                return job_id, job_path
            return job_id, f"https://www.104.com.tw{job_path}"
    return "", ""


def decode_welfare_tags(job: dict) -> list[str]:
    """解碼職缺的福利標籤"""
    tags = (job.get("tags") or {})
    return [WELFARE_CODES.get(k, k) for k in tags.keys() if k in WELFARE_CODES]


def get_estimated_total(area: str = "6001001000") -> dict:
    """
    查詢各福利碼的估計職缺數與可爬公司數。
    用 lastPage × count（perPage=30）算出 welfare filter 過後的真實職缺數。

    Returns:
        {"wf27": 1200, "wf19": 800, "wf18": 600,
         "estimated_unique": 800,   # 估計可爬不重複公司數
         "db_already": 0}           # 呼叫端可疊加 DB 現有數
    """
    totals: dict = {}
    for wf_code in SNACK_WELFARE_CODES:
        url = "https://www.104.com.tw/jobs/search/api/jobs"
        params = {
            "ro": "0",
            "area": area,
            "order": "15",
            "asc": "0",
            "page": "1",
            "perPage": "30",
            "welfare": wf_code,
            "s9": "1",
        }
        headers = {**HEADERS, "Referer": "https://www.104.com.tw/jobs/search/"}
        try:
            resp = request_with_retry(url, params=params, headers=headers, timeout=10)
            data = resp.json()
            pg = data.get("metadata", {}).get("pagination", {})
            last_page  = int(pg.get("lastPage", 1) or 1)
            count_page = int(pg.get("count", 30) or 30)
            # lastPage × count_page = 這個 welfare filter 的總職缺數
            totals[wf_code] = last_page * count_page
        except Exception:
            totals[wf_code] = 0

    # 估計唯一公司數：取最多的福利碼職缺數 ÷ 2（一家公司平均 2 個職缺）
    max_jobs = max(totals.values()) if totals else 0
    estimated_unique = max(max_jobs // 2, 0)
    totals["estimated_unique"] = estimated_unique
    return totals


def crawl_snack_companies(
    areas: list[str] = None,
    max_pages: int = 3,
    delay: float = 0.4,
    progress_callback=None,
) -> list[dict]:
    """
    主爬蟲函數：搜尋有零食/飲料/伙食福利的公司，抓取完整聯絡資訊

    Args:
        areas: 地區碼列表，預設台北市 + 新北市
        max_pages: 每個福利碼最多抓幾頁
        delay: 兩次請求之間的延遲（秒）

    Returns:
        公司名單（已去重），每筆包含：
        - source: "104"
        - cust_id, cust_name, industry, employee_count
        - address, phone, hr_name
        - welfare_tags, website
    """
    if areas is None:
        areas = ["6001001000", "6001002000"]  # 台北市, 新北市

    seen_ids: set[str] = set()
    companies: list[dict] = []

    for area in areas:
        for wf_code in SNACK_WELFARE_CODES:
            for page in range(1, max_pages + 1):
                jobs = search_jobs(
                    welfare_code=wf_code,
                    area=area,
                    page=page,
                    per_page=30,
                )
                if not jobs:
                    break

                new_ids = []
                for job in jobs:
                    cid = extract_cust_id(job)
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        new_ids.append((cid, job))

                # 只用 job_detail 取 email（company_detail API 目前被 104 封鎖）
                for cid, job in new_ids:
                    job_id, job_url = extract_job_id(job)
                    link = job.get("link", {})
                    cust_path = link.get("cust", "") if isinstance(link, dict) else ""
                    company_url = (
                        cust_path if cust_path.startswith("http")
                        else f"https://www.104.com.tw{cust_path}"
                    ) if cust_path else ""

                    phone = ""
                    hr_name = ""
                    address = job.get("jobAddrNoDesc", "")  # 從 job 本體取地址
                    website = ""
                    email = ""

                    # job_detail API 仍然正常，可取 email / hrName / phone
                    if job_id:
                        time.sleep(delay)
                        contact = get_job_detail(job_id, job_url)
                        if contact:
                            email = contact.get("email") or ""
                            hr_name = contact.get("hrName") or ""
                            phone_list = contact.get("phone") or []
                            phone = phone_list[0] if isinstance(phone_list, list) and phone_list else str(phone_list) if phone_list else ""

                    # 通知呼叫端有進度（供 UI 即時更新）
                    if progress_callback:
                        progress_callback(job.get("custName", cid), email)

                    companies.append(
                        {
                            "source": "104",
                            "cust_id": cid,
                            "cust_name": job.get("custName", ""),
                            "industry": job.get("coIndustryDesc", ""),
                            "employee_count": job.get("employeeCount", ""),
                            "address": address or job.get("jobAddrNoDesc", ""),
                            "phone": phone,
                            "hr_name": hr_name,
                            "email": email,
                            "job_url": job_url,
                            "company_url": company_url,
                            "welfare_tags": decode_welfare_tags(job),
                            "website": website,
                            "has_snack_benefit": True,
                        }
                    )

                    logger.info(
                        f"  [{cid}] {job.get('custName')} | 電話:{phone} | HR:{hr_name} | email:{email}"
                    )

                if len(jobs) < 30:
                    break  # 已是最後一頁

    logger.info(f"爬蟲完成：共 {len(companies)} 家公司")
    return companies


# ── 快速測試 ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print("=== 104 爬蟲測試（5 家公司）===\n")
    results = crawl_snack_companies(
        areas=["6001001000"],
        max_pages=1,
        delay=0.5,
    )

    # 只取前 5 筆輸出
    for i, c in enumerate(results[:5], 1):
        print(f"{i}. {c['cust_name']} | {c['industry']} | {c['employee_count']}")
        print(f"   地址：{c['address']}")
        print(f"   電話：{c['phone'] or '無'}")
        print(f"   HR：{c['hr_name'] or '無'}")
        print(f"   Email：{c['email'] or '無'}")
        print(f"   職缺連結：{c['job_url'] or '無'}")
        print(f"   公司連結：{c['company_url'] or '無'}")
        print(f"   福利：{c['welfare_tags']}")
        print()

    has_phone = sum(1 for c in results if c["phone"])
    has_hr = sum(1 for c in results if c["hr_name"])
    has_email = sum(1 for c in results if c.get("email"))
    print(f"有電話：{has_phone}/{len(results)}")
    print(f"有 HR 姓名：{has_hr}/{len(results)}")
    print(f"有 Email：{has_email}/{len(results)}")
