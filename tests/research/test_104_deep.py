"""
104 深度測試：公司頁資料 + 福利解碼 + 找到可聯絡資訊
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests, json, time, re

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}

# 104 福利代碼對照表（從官方網站整理）
WF_CODES = {
    "wf1": "員工旅遊", "wf2": "三節獎金", "wf3": "年終獎金",
    "wf4": "股票選擇權", "wf5": "紅利分潤", "wf6": "員工分紅",
    "wf7": "彈性上下班", "wf8": "在家上班", "wf9": "週休二日",
    "wf10": "補充保險", "wf11": "勞保", "wf12": "健保",
    "wf13": "退休金", "wf14": "育嬰留職", "wf15": "哺乳室",
    "wf16": "員工宿舍", "wf17": "交通補助", "wf18": "餐費補助",
    "wf19": "伙食津貼", "wf20": "制服提供", "wf21": "停車位",
    "wf22": "員工教育訓練", "wf23": "職務晉升", "wf24": "結婚禮金",
    "wf25": "生育補助", "wf26": "員工健身房/健身補助",
    "wf27": "下午茶/零食飲料", "wf28": "慶生活動", "wf29": "娛樂設施",
    "wf30": "寵物友善", "wf31": "多元性別友善", "wf32": "外籍人士友善",
    "wf33": "身障友善", "wf34": "應屆生友善", "wf35": "學生兼職"
}

# 「茶水間/零食」相關的代碼
SNACK_CODES = {"wf27", "wf19", "wf18"}  # 下午茶/零食, 伙食津貼, 餐費補助

def ok(m):   print(f"  [OK]  {m}")
def fail(m): print(f"  [XX]  {m}")
def info(m): print(f"  [--]  {m}")
def sep(t):  print(f"\n{'='*60}\n  {t}\n{'='*60}")

def get_jobs_with_welfare():
    sep("104 職缺搜尋 + 福利解碼")

    url = "https://www.104.com.tw/jobs/search/api/jobs"
    # 加入 s9=1 篩選有零食/茶水間福利的公司
    params = {
        "ro": "0", "area": "6001001000", "order": "15",
        "asc": "0", "page": "1", "perPage": "10",
        "s9": "1",  # 只看全職
    }
    h = {**H, "Referer": "https://www.104.com.tw/jobs/search/"}
    r = requests.get(url, params=params, headers=h, timeout=10)
    info(f"狀態碼：{r.status_code}")

    if r.status_code != 200:
        fail("失敗"); return []

    data = r.json()
    raw = data.get("data", {})
    jobs = raw.get("list", []) if isinstance(raw, dict) else raw

    ok(f"取得 {len(jobs)} 筆職缺")
    results = []
    for j in jobs[:3]:
        wf_keys = list((j.get("tags") or {}).keys())
        snack_wf = [WF_CODES.get(k, k) for k in wf_keys if k in SNACK_CODES]
        all_wf = [WF_CODES.get(k, k) for k in wf_keys if k in WF_CODES]

        link = j.get("link", {})
        cust_link = link.get("cust", "") if isinstance(link, dict) else ""
        # 從 cust link 取公司 ID
        cust_id = cust_link.split("/company/")[-1].split("?")[0] if "/company/" in cust_link else None

        results.append({
            "custName": j.get("custName"),
            "custNo": j.get("custNo"),
            "custId": cust_id,
            "coIndustryDesc": j.get("coIndustryDesc"),
            "employeeCount": j.get("employeeCount"),
            "address": j.get("jobAddrNoDesc"),
            "jobName": j.get("jobName"),
            "welfare_snack": snack_wf,
            "welfare_all": all_wf,
        })
        print(f"\n  公司：{j.get('custName')} | {j.get('coIndustryDesc')} | {j.get('employeeCount')}人")
        print(f"  地址：{j.get('jobAddrNoDesc')}")
        print(f"  零食相關福利：{snack_wf if snack_wf else '無'}")
        print(f"  全部福利：{all_wf}")
        print(f"  公司連結ID：{cust_id}")

    return results

def test_company_page(cust_id):
    sep(f"104 公司頁面 API (id={cust_id})")
    if not cust_id:
        fail("跳過"); return None

    # 嘗試公司詳細資訊 API
    for path in [
        f"https://www.104.com.tw/company/ajax/content/{cust_id}",
        f"https://www.104.com.tw/company/profile/ajax/{cust_id}",
    ]:
        h = {**H, "Referer": f"https://www.104.com.tw/company/{cust_id}"}
        r = requests.get(path, headers=h, timeout=10)
        info(f"路徑：{path.split('104.com.tw')[-1]} -> {r.status_code}")

        if r.status_code == 200:
            try:
                d = r.json().get("data", {})
                print()
                ok(f"公司名稱：{d.get('custName')}")
                ok(f"員工人數：{d.get('empNo') or d.get('employeeCount')}")
                ok(f"詳細地址：{d.get('address') or d.get('addr')}")
                ok(f"公司電話：{d.get('phone') or d.get('contactPhone') or '沒有'}")
                ok(f"公司信箱：{d.get('email') or d.get('contactEmail') or '沒有'}")
                ok(f"公司官網：{d.get('website') or d.get('websiteLink') or '沒有'}")
                ok(f"Facebook：{d.get('facebook') or '沒有'}")
                print()
                info(f"全部欄位：{sorted(d.keys())}")
                return d
            except Exception as e:
                fail(f"解析錯誤：{e}，raw：{r.text[:200]}")
        time.sleep(0.3)
    return None

def test_company_page_html(cust_id):
    sep(f"104 公司 HTML 頁面（找官網連結）")
    if not cust_id:
        fail("跳過"); return

    url = f"https://www.104.com.tw/company/{cust_id}"
    h = {**H, "Referer": "https://www.104.com.tw/"}
    r = requests.get(url, headers=h, timeout=10)
    info(f"狀態碼：{r.status_code}，大小：{len(r.text):,} bytes")

    if r.status_code == 200:
        # 找官網連結、電話、地址
        text = r.text
        # 找官網 URL
        website_match = re.findall(r'https?://(?!www\.104|www\.linkedin)[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(?:/[^\s"<>]*)?', text)
        clean_websites = [u for u in website_match if "104.com" not in u and "facebook.com" not in u][:5]
        ok(f"找到的外部連結：{clean_websites}")

        # 找電話
        phones = re.findall(r'0[2-9]-?\d{4}-?\d{4}|\+886-?\d{1,2}-?\d{4}-?\d{4}', text)
        phones and ok(f"電話號碼：{list(set(phones))[:3]}") or fail("沒有電話")

        # 有沒有公司信箱
        emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
        clean_emails = [e for e in emails if "104.com" not in e][:5]
        clean_emails and ok(f"信箱：{clean_emails}") or fail("沒有公開信箱")

def test_104_snack_filter():
    sep("104 直接用福利代碼篩選零食/下午茶公司")

    # 嘗試用 welfare 參數直接篩選
    for wf_code in ["wf27", "wf19"]:
        url = "https://www.104.com.tw/jobs/search/api/jobs"
        params = {
            "ro": "0", "area": "6001001000", "order": "15",
            "asc": "0", "page": "1", "perPage": "5",
            "welfare": wf_code,
        }
        h = {**H, "Referer": "https://www.104.com.tw/jobs/search/"}
        r = requests.get(url, params=params, headers=h, timeout=10)
        info(f"福利篩選 {wf_code}({WF_CODES.get(wf_code)}) -> 狀態：{r.status_code}")
        if r.status_code == 200:
            raw = r.json().get("data", {})
            jobs = raw.get("list", []) if isinstance(raw, dict) else raw
            ok(f"找到 {len(jobs)} 筆有此福利的職缺") if jobs else fail("沒有資料")
        time.sleep(0.3)

if __name__ == "__main__":
    print("104 深度測試\n")
    jobs = get_jobs_with_welfare()
    time.sleep(1)
    if jobs:
        cust_id = jobs[0].get("custId")
        cust_no = jobs[0].get("custNo")
        company_data = test_company_page(cust_id or cust_no)
        time.sleep(0.5)
        test_company_page_html(cust_id or cust_no)
    time.sleep(1)
    test_104_snack_filter()
    print("\n========== 完成 ==========")
