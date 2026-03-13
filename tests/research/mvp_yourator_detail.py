"""
Yourator 深挖 + 104 link 欄位分析
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests, json, time

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}

def ok(m):   print(f"  [OK]  {m}")
def fail(m): print(f"  [XX]  {m}")
def info(m): print(f"  [--]  {m}")
def sep(t):  print(f"\n{'='*60}\n  {t}\n{'='*60}")

def test_104_link_field():
    sep("104 - 分析 link 欄位取得正確的 jobNo")
    url = "https://www.104.com.tw/jobs/search/api/jobs"
    params = {"ro": "0", "area": "6001001000", "order": "15",
              "asc": "0", "page": "1", "perPage": "3"}
    h = {**H, "Referer": "https://www.104.com.tw/jobs/search/"}
    r = requests.get(url, params=params, headers=h, timeout=10)

    if r.status_code == 200:
        data = r.json()
        raw = data.get("data", {})
        jobs = raw if isinstance(raw, list) else raw.get("list", [])
        if jobs:
            j = jobs[0]
            info(f"link 欄位：{j.get('link')}")
            info(f"jobNo：{j.get('jobNo')}")
            info(f"tags：{j.get('tags')}")
            info(f"labels：{j.get('labels')}")
            info(f"coIndustry：{j.get('coIndustry')}")
            info(f"coIndustryDesc：{j.get('coIndustryDesc')}")
            info(f"employeeCount：{j.get('employeeCount')}")
            info(f"d3（福利？）：{j.get('d3')}")
            info(f"period（工作時間）：{j.get('period')}")

            # 用 link 裡的 URL 取 job detail
            link = j.get('link', {})
            if isinstance(link, dict):
                job_url = link.get('job') or link.get('applyAnalyze') or ''
                info(f"job URL：{job_url}")
                # 從 URL 抽 ID
                import re
                m = re.search(r'/job/([a-zA-Z0-9]+)', job_url)
                if m:
                    real_job_id = m.group(1)
                    ok(f"真正的 jobId：{real_job_id}")

                    # 嘗試不同的 detail API
                    for path in [
                        f"https://www.104.com.tw/job/ajax/content/{real_job_id}",
                        f"https://www.104.com.tw/job/{real_job_id}/ajax",
                    ]:
                        dr = requests.get(path, headers={**H, "Referer": f"https://www.104.com.tw/job/{real_job_id}"}, timeout=8)
                        info(f"Detail API {path.split('/')[-2:]}: {dr.status_code}")
                        if dr.status_code == 200:
                            dd = dr.json()
                            ok(f"有資料！keys：{list(dd.keys())}")
                            data2 = dd.get('data', {})
                            contact = data2.get('contactInfo', {}) or {}
                            ok(f"contactInfo：{contact}")
                        time.sleep(0.3)

def test_yourator_brand():
    sep("Yourator - 完整公司欄位（brand 物件）")
    h = {**H, "Referer": "https://www.yourator.co/"}
    r = requests.get("https://www.yourator.co/api/v2/companies?per=5&page=1", headers=h, timeout=10)

    if r.status_code == 200:
        data = r.json()
        companies = data.get('companies', [])
        if companies:
            c = companies[0]
            info(f"第一家公司原始資料：{json.dumps(c, ensure_ascii=False, indent=2)[:800]}")

            # 試試單一公司 API
            company_id = c.get('id')
            if company_id:
                cr = requests.get(f"https://www.yourator.co/api/v2/companies/{company_id}", headers=h, timeout=8)
                info(f"\n單一公司 API -> {cr.status_code}")
                if cr.status_code == 200:
                    cd = cr.json()
                    ok(f"完整公司資料 keys：{list(cd.keys())}")
                    info(f"資料：{json.dumps(cd, ensure_ascii=False)[:500]}")

def test_yourator_jobs_search():
    sep("Yourator - 找職缺的正確方法")
    h = {**H, "Referer": "https://www.yourator.co/"}

    # 試各種可能的 endpoint
    endpoints = [
        "/api/v2/positions?per=5",
        "/api/v2/job_listings?per=5",
        "/api/v2/opportunities?per=5",
        "/api/v2/careers?per=5",
    ]
    for ep in endpoints:
        r = requests.get(f"https://www.yourator.co{ep}", headers=h, timeout=8)
        info(f"{ep} -> {r.status_code}")
        if r.status_code == 200:
            try:
                d = r.json()
                ok(f"有資料！keys：{list(d.keys())}")
            except: pass
        time.sleep(0.2)

    # Yourator 的職缺搜尋頁有 GraphQL 嗎？
    gql_r = requests.post("https://www.yourator.co/graphql",
                          json={"query": "{ jobs { title } }"},
                          headers=h, timeout=5)
    info(f"\nGraphQL 嘗試 -> {gql_r.status_code}")

if __name__ == "__main__":
    test_104_link_field()
    time.sleep(1)
    test_yourator_brand()
    time.sleep(1)
    test_yourator_jobs_search()
    print("\n========== 完成 ==========")
