"""
平台深度測試 Round 2 - 根據第一輪結果修正
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests, json, time, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

def ok(msg):   print(f"  [OK]  {msg}")
def fail(msg): print(f"  [XX]  {msg}")
def info(msg): print(f"  [--]  {msg}")
def sep(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")

# ============================================================
# 104 修正版：不帶 keyword 參數
# ============================================================
def test_104_fixed():
    sep("104 職缺搜尋 API (修正版)")

    # 嘗試不同的 endpoint 格式
    urls_to_try = [
        ("官方搜尋API v2", "https://www.104.com.tw/jobs/search/api/jobs", {
            "ro": "0", "area": "6001001000", "order": "15",
            "asc": "0", "page": "1", "perPage": "5",
        }),
        ("帶 keyword 空白的方法", "https://www.104.com.tw/jobs/search/api/jobs", {
            "ro": "0", "kwop": "7", "keyword": " ",
            "area": "6001001000", "order": "15",
            "asc": "0", "page": "1", "perPage": "5",
        }),
    ]

    headers = {**HEADERS,
               "Referer": "https://www.104.com.tw/jobs/search/",
               "Accept": "application/json, text/plain, */*",
               "X-Requested-With": "XMLHttpRequest"}

    for name, url, params in urls_to_try:
        info(f"嘗試：{name}")
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            info(f"  狀態碼：{r.status_code}")
            if r.status_code == 200:
                data = r.json()
                jobs = data.get("data", {}).get("list", [])
                ok(f"  取得 {len(jobs)} 筆職缺！")
                if jobs:
                    j = jobs[0]
                    ok(f"  公司名稱：{j.get('custName')}")
                    ok(f"  員工人數：{j.get('coSize')}")
                    ok(f"  地址：{j.get('jobAddrNoDesc')}")
                    ok(f"  福利：{(j.get('welfare') or {}).get('tag', [])}")
                    ok(f"  custNo：{j.get('custNo')}")
                    ok(f"  jobNo：{j.get('jobNo')}")
                    info(f"  欄位：{sorted(j.keys())}")
                    return j.get('custNo'), j.get('jobNo')
            elif r.status_code != 200:
                fail(f"  失敗：{r.text[:150]}")
        except Exception as e:
            fail(f"  例外：{e}")
        time.sleep(0.5)
    return None, None

def test_104_company_v2(cust_no):
    sep(f"104 公司 API (custNo={cust_no})")
    if not cust_no:
        fail("跳過"); return

    for path in [f"/company/ajax/content/{cust_no}", f"/company/profile/{cust_no}"]:
        url = f"https://www.104.com.tw{path}"
        h = {**HEADERS, "Referer": f"https://www.104.com.tw/company/{cust_no}"}
        try:
            r = requests.get(url, headers=h, timeout=10)
            info(f"路徑 {path} -> {r.status_code}")
            if r.status_code == 200:
                try:
                    d = r.json().get("data", {})
                    ok(f"公司名稱：{d.get('custName')}")
                    ok(f"員工人數：{d.get('empNo')}")
                    ok(f"地址：{d.get('address') or d.get('addr')}")
                    ok(f"電話：{d.get('phone') or d.get('contactPhone') or '沒有'}")
                    ok(f"信箱：{d.get('email') or d.get('contactEmail') or '沒有'}")
                    ok(f"官網：{d.get('website') or '沒有'}")
                    info(f"欄位：{sorted(d.keys())}")
                    return
                except:
                    info(f"  不是 JSON，可能是 HTML，大小：{len(r.text)}")
        except Exception as e:
            fail(f"例外：{e}")
        time.sleep(0.3)

# ============================================================
# Cake - 解析 SSR HTML 裡的 JSON
# ============================================================
def test_cake_deep():
    sep("Cake.me - 深度解析 (1.6MB SSR)")

    url = "https://www.cake.me/jobs?q=&location=taipei&page=1"
    h = {**HEADERS, "Referer": "https://www.cake.me/"}

    try:
        r = requests.get(url, headers=h, timeout=15)
        info(f"狀態碼：{r.status_code}，大小：{len(r.text):,} bytes")

        soup = BeautifulSoup(r.text, "html.parser")

        # 找 Next.js 的 __NEXT_DATA__
        next_data = soup.find("script", id="__NEXT_DATA__")
        if next_data:
            ok("找到 __NEXT_DATA__（Next.js SSR）！")
            try:
                data = json.loads(next_data.string)
                # 找 jobs 資料
                props = data.get("props", {}).get("pageProps", {})
                jobs = (props.get("jobs") or
                        props.get("jobList") or
                        props.get("data", {}).get("jobs") or
                        [])

                if jobs:
                    ok(f"取得 {len(jobs)} 筆職缺！")
                    j = jobs[0]
                    print()
                    ok(f"職缺名稱：{j.get('title') or j.get('job_title')}")
                    ok(f"公司名稱：{j.get('company', {}).get('name') or j.get('companyName')}")
                    ok(f"公司地址：{j.get('company', {}).get('address') or j.get('location')}")
                    ok(f"員工人數：{j.get('company', {}).get('size') or j.get('companySize')}")
                    ok(f"公司官網：{j.get('company', {}).get('website') or '沒有'}")

                    # 最重要：HR 資訊
                    hr = j.get("hr") or j.get("recruiter") or j.get("contact")
                    if hr:
                        ok(f"HR 姓名：{hr.get('name') or hr.get('display_name')}")
                        ok(f"HR 職稱：{hr.get('title') or hr.get('position')}")
                        ok(f"HR Cake URL：{hr.get('url') or hr.get('profile_url')}")
                    else:
                        fail("HR 資訊：沒有（或在其他路徑）")

                    print()
                    info(f"職缺欄位：{sorted(j.keys())}")
                    if j.get('company'):
                        info(f"公司欄位：{sorted(j['company'].keys())}")
                else:
                    fail(f"jobs 是空的，pageProps keys：{list(props.keys())[:10]}")
                    # 印出整個結構幫助 debug
                    info(f"整個 pageProps keys：{list(props.keys())}")

            except json.JSONDecodeError as e:
                fail(f"JSON 解析錯誤：{e}")
        else:
            fail("沒有 __NEXT_DATA__，不是 Next.js 或是 CSR")
            # 試試其他 script tag
            scripts = soup.find_all("script", type="application/json")
            info(f"找到 {len(scripts)} 個 application/json script")

    except Exception as e:
        fail(f"例外：{e}")

# ============================================================
# Yourator - 解析 SSR
# ============================================================
def test_yourator_deep():
    sep("Yourator - 深度解析")

    url = "https://www.yourator.co/jobs"
    h = {**HEADERS, "Referer": "https://www.yourator.co/"}

    try:
        r = requests.get(url, headers=h, timeout=15)
        info(f"狀態碼：{r.status_code}，大小：{len(r.text):,} bytes")

        soup = BeautifulSoup(r.text, "html.parser")

        # 找 Nuxt 或 Next 資料
        next_data = soup.find("script", id="__NEXT_DATA__")
        nuxt_data = soup.find("script", id="__NUXT_DATA__")
        nuxt_state = soup.find("script", string=re.compile("window.__nuxt__"))

        next_data and ok("找到 __NEXT_DATA__（Next.js）") or info("沒有 __NEXT_DATA__")
        nuxt_data and ok("找到 __NUXT_DATA__（Nuxt.js）") or info("沒有 __NUXT_DATA__")
        nuxt_state and ok("找到 window.__nuxt__（Nuxt）") or info("沒有 window.__nuxt__")

        # 看所有 script
        all_scripts = soup.find_all("script")
        info(f"共 {len(all_scripts)} 個 script 標籤")

        # 找有 job 關鍵字的 script
        for s in all_scripts:
            txt = s.string or ""
            if len(txt) > 200 and ("job" in txt.lower() or "position" in txt.lower()):
                info(f"找到含 job 的 script，前100字：{txt[:100]}")
                break

        # 看 HTML 結構
        job_containers = (soup.find_all(class_=re.compile("job")) +
                         soup.find_all(attrs={"data-job": True}))
        info(f"HTML 中有 job 相關元素：{len(job_containers)} 個")

        # 試試別的 URL
        api_url = "https://www.yourator.co/api/v2/companies?per=5&page=1"
        ar = requests.get(api_url, headers=h, timeout=8)
        info(f"公司 API 嘗試 -> {ar.status_code}")
        if ar.status_code == 200:
            try:
                d = ar.json()
                ok(f"公司 API 有資料！keys={list(d.keys())}")
            except:
                pass

    except Exception as e:
        fail(f"例外：{e}")

# ============================================================
# 實際可用的 104 HTML 版本
# ============================================================
def test_104_html():
    sep("104 - HTML 職缺頁面（備用方案）")
    url = "https://www.104.com.tw/jobs/search/?area=6001001000&order=15&asc=0&page=1&mode=s"
    h = {**HEADERS, "Referer": "https://www.104.com.tw/"}

    try:
        r = requests.get(url, headers=h, timeout=10)
        info(f"狀態碼：{r.status_code}，大小：{len(r.text):,} bytes")

        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data:
                ok("104 也是 Next.js SSR！")
                data = json.loads(next_data.string)
                info(f"pageProps keys：{list(data.get('props',{}).get('pageProps',{}).keys())[:8]}")
            else:
                info("104 是傳統 SSR 或需要 AJAX")
    except Exception as e:
        fail(f"例外：{e}")

if __name__ == "__main__":
    print("深度測試開始\n")
    cust_no, job_no = test_104_fixed()
    time.sleep(1)
    if cust_no:
        test_104_company_v2(cust_no)
        time.sleep(1)
    test_104_html()
    time.sleep(1)
    test_cake_deep()
    time.sleep(1)
    test_yourator_deep()
    print("\n========== 深度測試完成 ==========\n")
