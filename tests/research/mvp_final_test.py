"""
平台測試 Round 3 - 修正解析，找到真正的資料
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests, json, time, re
from bs4 import BeautifulSoup

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}

def ok(m):   print(f"  [OK]  {m}")
def fail(m): print(f"  [XX]  {m}")
def info(m): print(f"  [--]  {m}")
def sep(t):  print(f"\n{'='*60}\n  {t}\n{'='*60}")

# ============================================================
# 104 - 修正版，直接 print raw 找結構
# ============================================================
def test_104_raw():
    sep("104 API - 找真正的資料結構")

    url = "https://www.104.com.tw/jobs/search/api/jobs"
    params = {"ro": "0", "area": "6001001000", "order": "15",
              "asc": "0", "page": "1", "perPage": "3"}
    h = {**H, "Referer": "https://www.104.com.tw/jobs/search/"}

    r = requests.get(url, params=params, headers=h, timeout=10)
    info(f"狀態碼：{r.status_code}")

    if r.status_code == 200:
        data = r.json()
        info(f"頂層 keys：{list(data.keys())}")

        # 找 jobs list
        if isinstance(data, list):
            jobs = data
        elif "data" in data:
            d = data["data"]
            if isinstance(d, list):
                jobs = d
            else:
                info(f"data 的 keys：{list(d.keys())}")
                jobs = d.get("list") or d.get("jobs") or []
        else:
            jobs = []

        ok(f"取得 {len(jobs)} 筆職缺")

        if jobs:
            j = jobs[0]
            print()
            ok(f"公司名稱：{j.get('custName')}")
            ok(f"產業：{j.get('indcat')}")
            ok(f"員工人數：{j.get('coSize')}")
            ok(f"地址：{j.get('jobAddrNoDesc')}")
            ok(f"職缺名稱：{j.get('jobName')}")
            ok(f"custNo（公司ID）：{j.get('custNo')}")
            ok(f"jobNo（職缺ID）：{j.get('jobNo')}")
            welfare = (j.get('welfare') or {}).get('tag', [])
            ok(f"福利標籤：{welfare}") if welfare else fail("福利標籤：空的")
            print()
            info(f"欄位列表：{sorted(j.keys())}")
            return j.get('custNo'), j.get('jobNo')
    return None, None

def test_104_job_detail(job_no):
    sep(f"104 職缺詳細（jobNo={job_no}）")
    if not job_no: fail("跳過"); return

    url = f"https://www.104.com.tw/job/ajax/content/{job_no}"
    h = {**H, "Referer": f"https://www.104.com.tw/job/{job_no}"}
    r = requests.get(url, headers=h, timeout=10)
    info(f"狀態碼：{r.status_code}")

    if r.status_code == 200:
        data = r.json().get("data", {})
        header  = data.get("header", {}) or {}
        company = data.get("company", {}) or {}
        contact = data.get("contactInfo", {}) or {}
        job_info = data.get("jobDetail", {}) or {}

        print("\n  -- 公司資訊 --")
        ok(f"公司名稱：{header.get('custName')}")
        ok(f"員工規模：{company.get('empNo')}")
        ok(f"公司地址：{company.get('address')}")
        ok(f"公司官網：{company.get('website') or '沒有'}")

        print("\n  -- 職缺資訊 --")
        ok(f"職缺名稱：{header.get('jobName')}")
        tags = job_info.get('jobCategory', [])
        ok(f"職缺類別：{tags}")

        print("\n  -- 聯絡資訊（最重要！）--")
        name = contact.get('hrName') or contact.get('name')
        title = contact.get('hrTitle') or contact.get('title')
        email = contact.get('email') or contact.get('hrEmail')
        phone = contact.get('phone') or contact.get('contactPhone')
        name  and ok(f"HR 姓名：{name}")   or fail("HR 姓名：沒有")
        title and ok(f"HR 職稱：{title}")  or fail("HR 職稱：沒有")
        email and ok(f"HR Email：{email}") or fail("HR Email：登入才看到")
        phone and ok(f"HR 電話：{phone}") or fail("HR 電話：沒有")
        print()
        info(f"contactInfo 全部欄位：{list(contact.keys())}")

# ============================================================
# Cake - 找 initialState 裡的 jobs
# ============================================================
def test_cake_initialstate():
    sep("Cake.me - 解析 initialState")

    r = requests.get("https://www.cake.me/jobs?q=&location=taipei",
                     headers={**H, "Referer": "https://www.cake.me/"}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    nd = soup.find("script", id="__NEXT_DATA__")
    if not nd:
        fail("找不到 __NEXT_DATA__"); return

    data = json.loads(nd.string)
    page = data.get("props", {}).get("pageProps", {})
    state = page.get("initialState", {})

    info(f"initialState keys：{list(state.keys())[:10]}")

    # 找 job 相關 key
    for key in state:
        val = state[key]
        if isinstance(val, dict):
            info(f"  {key} -> dict keys：{list(val.keys())[:5]}")
        elif isinstance(val, list) and len(val) > 0:
            info(f"  {key} -> list[{len(val)}] 第一筆type：{type(val[0]).__name__}")

    # 直接搜尋 jobs
    jobs = None
    for path in [["jobs"], ["jobList"], ["data", "jobs"], ["search", "jobs"]]:
        tmp = state
        try:
            for k in path:
                tmp = tmp[k]
            if isinstance(tmp, list) and tmp:
                jobs = tmp
                ok(f"在 state.{'.'.join(path)} 找到 {len(jobs)} 筆！")
                break
        except (KeyError, TypeError):
            pass

    if not jobs:
        # 遞迴搜尋
        def find_jobs(obj, depth=0):
            if depth > 5: return None
            if isinstance(obj, list) and len(obj) > 2:
                if isinstance(obj[0], dict) and ("title" in obj[0] or "jobTitle" in obj[0]):
                    return obj
            if isinstance(obj, dict):
                for k, v in obj.items():
                    result = find_jobs(v, depth+1)
                    if result: return result
            return None

        jobs = find_jobs(state)
        if jobs:
            ok(f"遞迴找到 {len(jobs)} 筆職缺！")

    if jobs:
        j = jobs[0]
        print()
        ok(f"職缺名稱：{j.get('title') or j.get('job_title') or j.get('name')}")
        company = j.get('company') or j.get('employer') or {}
        ok(f"公司名稱：{company.get('name') if isinstance(company, dict) else company}")
        ok(f"地點：{j.get('location') or j.get('city')}")

        recruiter = j.get('recruiter') or j.get('hr') or j.get('contact') or {}
        if recruiter:
            ok(f"HR 姓名：{recruiter.get('name') or recruiter.get('display_name')}")
            ok(f"HR 職稱：{recruiter.get('title') or recruiter.get('position')}")
            ok(f"HR Cake URL：{recruiter.get('url') or recruiter.get('profile_url')}")
        else:
            fail("HR 資訊：不在 job 物件裡")

        print()
        info(f"職缺欄位：{sorted(j.keys())}")
    else:
        fail("找不到職缺列表，Cake 可能需要 Playwright")

# ============================================================
# Yourator - 公開 API 深挖
# ============================================================
def test_yourator_api():
    sep("Yourator 公開 API")
    h = {**H, "Referer": "https://www.yourator.co/"}

    # 公司 API
    r = requests.get("https://www.yourator.co/api/v2/companies?per=3&page=1", headers=h, timeout=10)
    info(f"公司 API 狀態：{r.status_code}")
    if r.status_code == 200:
        data = r.json()
        companies = data.get("companies", [])
        ok(f"取得 {len(companies)} 家公司！總計 {data.get('total', 'N/A')} 家")

        if companies:
            c = companies[0]
            print()
            ok(f"公司名稱：{c.get('name') or c.get('display_name')}")
            ok(f"產業：{c.get('category') or c.get('industry')}")
            ok(f"員工人數：{c.get('size') or c.get('employee_count')}")
            ok(f"地址：{c.get('address') or c.get('location')}")
            ok(f"官網：{c.get('website') or c.get('homepage')}")
            ok(f"公司 ID：{c.get('id') or c.get('slug')}")
            print()
            info(f"公司欄位：{sorted(c.keys())}")

            # 試試找職缺
            company_id = c.get('slug') or c.get('id')
            if company_id:
                jr = requests.get(f"https://www.yourator.co/api/v2/companies/{company_id}/jobs",
                                   headers=h, timeout=8)
                info(f"\n公司職缺 API -> {jr.status_code}")
                if jr.status_code == 200:
                    jdata = jr.json()
                    ok(f"取得職缺！keys：{list(jdata.keys())}")
                    jobs = jdata.get("jobs") or jdata.get("positions") or []
                    if jobs:
                        jj = jobs[0]
                        ok(f"職缺名稱：{jj.get('title') or jj.get('name')}")
                        info(f"職缺欄位：{sorted(jj.keys())}")

    time.sleep(0.5)

    # 試職缺搜尋 API
    for endpoint in ["/api/v2/jobs", "/api/v2/positions", "/api/v1/jobs"]:
        jr = requests.get(f"https://www.yourator.co{endpoint}?per=3", headers=h, timeout=8)
        info(f"職缺 API {endpoint} -> {jr.status_code}")
        if jr.status_code == 200:
            try:
                d = jr.json()
                ok(f"有資料！keys：{list(d.keys())}")
            except:
                pass
        time.sleep(0.3)

if __name__ == "__main__":
    print("Round 3 測試開始\n")
    cust_no, job_no = test_104_raw()
    time.sleep(1)
    if job_no:
        test_104_job_detail(job_no)
    time.sleep(1)
    test_cake_initialstate()
    time.sleep(1)
    test_yourator_api()
    print("\n========== 完成 ==========")
