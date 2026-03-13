"""
平台 MVP 測試 - 實際測試各平台能抓到什麼資料
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import requests, json, time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "application/json, text/plain, */*",
}

def section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def ok(msg): print(f"  [OK]  {msg}")
def fail(msg): print(f"  [XX]  {msg}")
def info(msg): print(f"  [--]  {msg}")

# ============================================================
# 104 人力銀行
# ============================================================
def test_104():
    section("104 人力銀行 - 職缺搜尋 API")

    url = "https://www.104.com.tw/jobs/search/api/jobs"
    params = {
        "ro": "0",
        "kwop": "7",
        "keyword": "",
        "area": "6001001000",
        "order": "15",
        "asc": "0",
        "s9": "1",
        "page": "1",
        "perPage": "5",
        "mode": "s",
        "jobsource": "index_s",
    }
    h = {**HEADERS,
         "Referer": "https://www.104.com.tw/jobs/search/",
         "Accept": "application/json, text/plain, */*"}

    try:
        resp = requests.get(url, params=params, headers=h, timeout=10)
        info(f"狀態碼：{resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            jobs = data.get("data", {}).get("list", [])
            ok(f"成功取得 {len(jobs)} 筆職缺")

            if jobs:
                j = jobs[0]
                print()
                ok(f"職缺名稱：{j.get('jobName','N/A')}")
                ok(f"公司名稱：{j.get('custName','N/A')}")
                ok(f"公司產業：{j.get('indcat','N/A')}")
                ok(f"公司地址：{j.get('jobAddrNoDesc','N/A')}")
                ok(f"員工人數：{j.get('coSize','N/A')}")

                # 福利
                welfare = j.get('welfare',{}) or {}
                tags = welfare.get('tag', [])
                ok(f"福利標籤：{tags}") if tags else fail("福利標籤：沒有")

                # 聯絡人（最重要）
                hr = j.get('hrName') or j.get('contactName')
                email = j.get('hrEmail') or j.get('contactEmail')
                hr and ok(f"HR 姓名：{hr}") or fail("HR 姓名：職缺列表層沒有")
                email and ok(f"HR Email：{email}") or fail("HR Email：職缺列表層沒有")

                print()
                info(f"所有欄位：{sorted(j.keys())}")

                # 拿第一筆的公司 ID 做進階測試
                cust_no = j.get('custNo') or j.get('custcode')
                job_no = j.get('jobNo') or j.get('jobCode')
                return cust_no, job_no
        else:
            fail(f"失敗，回應：{resp.text[:200]}")
    except Exception as e:
        fail(f"例外：{e}")
    return None, None

def test_104_job_detail(job_no):
    section(f"104 - 職缺詳細頁 (jobNo={job_no})")
    if not job_no:
        fail("沒有 jobNo，跳過")
        return

    url = f"https://www.104.com.tw/job/ajax/content/{job_no}"
    h = {**HEADERS, "Referer": f"https://www.104.com.tw/job/{job_no}"}
    try:
        resp = requests.get(url, headers=h, timeout=10)
        info(f"狀態碼：{resp.status_code}")
        if resp.status_code == 200:
            data = resp.json().get("data",{})
            contact = data.get("contactInfo",{}) or {}
            company = data.get("company",{}) or {}
            header  = data.get("header",{}) or {}

            ok(f"公司名稱：{header.get('custName','N/A')}")
            ok(f"員工規模：{company.get('empNo','N/A')}")
            ok(f"公司地址：{company.get('address','N/A')}")
            ok(f"公司官網：{company.get('website','N/A')}")

            name = contact.get('hrName') or contact.get('name')
            email = contact.get('email')
            phone = contact.get('phone')
            name and ok(f"HR 姓名：{name}") or fail("HR 姓名：沒有（可能要登入）")
            email and ok(f"HR Email：{email}") or fail("HR Email：隱藏（需登入）")
            phone and ok(f"HR 電話：{phone}") or fail("HR 電話：隱藏")

            info(f"contactInfo 欄位：{list(contact.keys())}")
    except Exception as e:
        fail(f"例外：{e}")

def test_104_company(cust_no):
    section(f"104 - 公司詳細 API (custNo={cust_no})")
    if not cust_no:
        fail("沒有 custNo，跳過")
        return

    url = f"https://www.104.com.tw/company/ajax/content/{cust_no}"
    h = {**HEADERS, "Referer": f"https://www.104.com.tw/company/{cust_no}"}
    try:
        resp = requests.get(url, headers=h, timeout=10)
        info(f"狀態碼：{resp.status_code}")
        if resp.status_code == 200:
            data = resp.json().get("data",{})
            ok(f"公司名稱：{data.get('custName','N/A')}")
            ok(f"員工人數：{data.get('empNo','N/A')}")
            ok(f"公司地址：{data.get('address','N/A')}")
            addr = data.get('addr','N/A')
            ok(f"詳細地址：{addr}")
            phone = data.get('phone','N/A')
            phone and ok(f"公司電話：{phone}") or fail("公司電話：沒有")
            email = data.get('email','N/A')
            email and ok(f"公司信箱：{email}") or fail("公司信箱：沒有")
            ok(f"官網：{data.get('website','N/A')}")
            info(f"所有欄位：{sorted(data.keys())}")
    except Exception as e:
        fail(f"例外：{e}")

# ============================================================
# Cake
# ============================================================
def test_cake():
    section("Cake.me - 職缺頁面")
    url = "https://www.cake.me/jobs?q=&location=taipei"
    h = {**HEADERS, "Referer": "https://www.cake.me/"}
    try:
        resp = requests.get(url, headers=h, timeout=10)
        info(f"狀態碼：{resp.status_code}，大小：{len(resp.text):,} bytes")

        text = resp.text
        # 看有沒有職缺資料
        has_json_data = '"jobs"' in text or '"job_list"' in text or 'application/ld+json' in text
        has_company = '"company"' in text or '"employer"' in text
        has_html_jobs = 'job-list' in text or 'job-card' in text or 'JobCard' in text

        has_json_data and ok("有內嵌 JSON 資料") or fail("沒有內嵌 JSON 資料")
        has_company and ok("有公司資料欄位") or fail("沒有公司資料欄位")
        has_html_jobs and ok("有 HTML 職缺卡片") or fail("沒有 HTML 職缺卡片（可能需要 JS）")

        # 嘗試找 API
        for api_path in ["/api/v1/jobs", "/api/v2/jobs", "/api/jobs"]:
            ar = requests.get(f"https://www.cake.me{api_path}", headers=h, timeout=5)
            info(f"API {api_path} -> {ar.status_code}")

    except Exception as e:
        fail(f"例外：{e}")

# ============================================================
# Yourator
# ============================================================
def test_yourator():
    section("Yourator - 職缺頁面")
    url = "https://www.yourator.co/jobs"
    h = {**HEADERS, "Referer": "https://www.yourator.co/"}
    try:
        resp = requests.get(url, headers=h, timeout=10)
        info(f"狀態碼：{resp.status_code}，大小：{len(resp.text):,} bytes")

        text = resp.text
        has_json = '"jobs"' in text or 'application/ld+json' in text
        has_html = 'job-card' in text or 'job-item' in text or 'JobItem' in text

        has_json and ok("有內嵌 JSON 資料") or fail("沒有 JSON（可能需要 Playwright）")
        has_html and ok("有 HTML 職缺") or fail("沒有 HTML 職缺")

        # 嘗試 API
        for api_path in ["/api/v2/jobs", "/api/jobs", "/api/v1/positions"]:
            ar = requests.get(f"https://www.yourator.co{api_path}", headers=h, timeout=5)
            info(f"API {api_path} -> {ar.status_code}")
            if ar.status_code == 200:
                try:
                    d = ar.json()
                    ok(f"API 有資料！keys={list(d.keys())[:5]}")
                except:
                    pass

    except Exception as e:
        fail(f"例外：{e}")

# ============================================================
# LinkedIn（不登入）
# ============================================================
def test_linkedin():
    section("LinkedIn - 不登入能拿到什麼")
    url = "https://www.linkedin.com/jobs/search/?keywords=HR+Manager&location=Taipei"
    h = {**HEADERS, "Referer": "https://www.linkedin.com/"}
    try:
        resp = requests.get(url, headers=h, timeout=10)
        info(f"狀態碼：{resp.status_code}，大小：{len(resp.text):,} bytes")

        if resp.status_code == 999:
            fail("被 LinkedIn 封鎖（999 = Bot 偵測）")
            fail("結論：LinkedIn 必須用 Playwright + 帳號登入")
        elif resp.status_code == 200:
            text = resp.text
            has_job = "job-search-card" in text or "base-card" in text
            has_name = '"name"' in text
            has_job and ok("有職缺 HTML 資料") or fail("沒有職缺（需要 JS）")
            has_name and ok("有姓名欄位") or fail("沒有姓名")
    except Exception as e:
        fail(f"例外：{e}")


if __name__ == "__main__":
    print("平台 MVP 測試開始\n")

    cust_no, job_no = test_104()
    time.sleep(1)
    test_104_job_detail(job_no)
    time.sleep(1)
    test_104_company(cust_no)
    time.sleep(1)
    test_cake()
    time.sleep(1)
    test_yourator()
    time.sleep(1)
    test_linkedin()

    print("\n\n========== 測試完成 ==========\n")
