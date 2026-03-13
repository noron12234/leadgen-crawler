"""
104 hrName 欄位深挖 + 完整流程測試
目標：用 wf27 篩選有零食福利的公司，取得可聯絡資訊
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests, json, time

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}
WF_CODES = {
    "wf1":"員工旅遊","wf2":"三節獎金","wf3":"年終獎金","wf7":"彈性上下班",
    "wf8":"在家上班","wf9":"週休二日","wf18":"餐費補助","wf19":"伙食津貼",
    "wf26":"健身補助","wf27":"下午茶/零食飲料","wf28":"慶生","wf29":"娛樂設施",
}
SNACK_WF = {"wf27","wf19","wf18"}

def ok(m):   print(f"  [OK]  {m}")
def fail(m): print(f"  [XX]  {m}")
def info(m): print(f"  [--]  {m}")
def sep(t):  print(f"\n{'='*60}\n  {t}\n{'='*60}")

def search_snack_companies():
    sep("用 wf27 篩選有零食/下午茶福利的公司（台北）")
    url = "https://www.104.com.tw/jobs/search/api/jobs"
    params = {
        "ro": "0", "area": "6001001000", "order": "15",
        "asc": "0", "page": "1", "perPage": "10",
        "welfare": "wf27",  # 直接篩選零食/下午茶
        "s9": "1",
    }
    h = {**H, "Referer": "https://www.104.com.tw/jobs/search/"}
    r = requests.get(url, params=params, headers=h, timeout=10)
    info(f"狀態碼：{r.status_code}")

    data = r.json()
    meta = data.get("metadata", {})
    info(f"總共有 {meta.get('total', 'N/A')} 筆職缺有零食/下午茶福利")

    raw = data.get("data", {})
    jobs = raw.get("list", []) if isinstance(raw, dict) else raw
    ok(f"本次取得 {len(jobs)} 筆")

    companies = {}
    for j in jobs:
        link = j.get("link", {})
        cust_link = link.get("cust", "") if isinstance(link, dict) else ""
        cust_id = cust_link.split("/company/")[-1].split("?")[0] if "/company/" in cust_link else j.get("custNo")

        wf_keys = list((j.get("tags") or {}).keys())
        welfare = [WF_CODES.get(k, k) for k in wf_keys if k in WF_CODES]

        companies[cust_id] = {
            "custName": j.get("custName"),
            "custId": cust_id,
            "industry": j.get("coIndustryDesc"),
            "employeeCount": j.get("employeeCount"),
            "address": j.get("jobAddrNoDesc"),
            "welfare": welfare,
        }

    for c in list(companies.values())[:5]:
        print(f"\n  {c['custName']} | {c['industry']} | {c['employeeCount']}人 | {c['address']}")
        print(f"  福利: {c['welfare']}")
        print(f"  ID: {c['custId']}")

    return list(companies.values())

def get_company_contact(cust_id, cust_name):
    sep(f"公司詳細 + hrName 欄位：{cust_name}")
    url = f"https://www.104.com.tw/company/ajax/content/{cust_id}"
    h = {**H, "Referer": f"https://www.104.com.tw/company/{cust_id}"}
    r = requests.get(url, headers=h, timeout=10)
    info(f"狀態碼：{r.status_code}")

    if r.status_code != 200:
        fail("失敗"); return None

    d = r.json().get("data", {})

    # 核心欄位
    print(f"\n  === 公司聯絡資訊 ===")
    ok(f"公司名稱：{d.get('custName')}")
    ok(f"員工人數：{d.get('empNo')}")
    ok(f"完整地址：{d.get('address')}")

    phone = d.get('phone')
    fax   = d.get('fax')
    phone and ok(f"公司電話：{phone}") or fail("公司電話：無")
    fax   and ok(f"公司傳真：{fax}")  or info("傳真：無")

    # hrName - 重點！
    hr_name = d.get('hrName')
    if hr_name:
        ok(f"HR 姓名（hrName）：{hr_name}")
    else:
        fail("hrName：空的")

    # 其他連結
    links = []
    for k in ['corpLink1','corpLink2','corpLink3']:
        v = d.get(k)
        if v: links.append(v)
    links and ok(f"公司連結：{links}") or fail("公司連結：無")

    # 公司簡介/管理
    management = d.get('management', '')
    if management and len(management) > 5:
        info(f"管理層資訊：{management[:100]}")

    # 福利（原始）
    welfare_raw = d.get('welfare', '')
    welfare_raw and info(f"福利描述：{welfare_raw[:100]}") or info("福利：無文字描述")

    print(f"\n  === 全部欄位 ===")
    info(f"{sorted(d.keys())}")

    return {
        "name": d.get('custName'),
        "phone": phone,
        "hr_name": hr_name,
        "address": d.get('address'),
        "links": links,
        "empNo": d.get('empNo'),
    }

def simulate_full_pipeline():
    sep("完整流程模擬：從搜尋到可聯絡名單")
    print("""
  流程：
  1. 用 wf27 篩選有零食/下午茶福利 → 目標公司清單
  2. 對每家公司呼叫 company detail API
  3. 取得：公司名、地址、電話、hrName
  4. 輸出可聯絡的名單
  """)

    # 搜尋
    url = "https://www.104.com.tw/jobs/search/api/jobs"
    params = {"ro":"0","area":"6001001000","order":"15","asc":"0",
              "page":"1","perPage":"5","welfare":"wf27","s9":"1"}
    h = {**H, "Referer": "https://www.104.com.tw/jobs/search/"}
    r = requests.get(url, params=params, headers=h, timeout=10)
    raw = r.json().get("data", {})
    jobs = raw.get("list", []) if isinstance(raw, dict) else raw

    results = []
    seen = set()

    for j in jobs[:5]:
        link = j.get("link", {})
        cust_id = link.get("cust","").split("/company/")[-1].split("?")[0] if isinstance(link,dict) else None
        if not cust_id or cust_id in seen:
            continue
        seen.add(cust_id)

        time.sleep(0.5)
        dr = requests.get(
            f"https://www.104.com.tw/company/ajax/content/{cust_id}",
            headers={**H,"Referer":f"https://www.104.com.tw/company/{cust_id}"},
            timeout=10
        )
        if dr.status_code != 200:
            continue

        d = dr.json().get("data", {})
        results.append({
            "公司名稱": d.get('custName'),
            "產業": d.get('industryDesc'),
            "員工人數": d.get('empNo'),
            "完整地址": d.get('address'),
            "公司電話": d.get('phone') or "無",
            "HR姓名": d.get('hrName') or "無",
            "公司連結": (d.get('corpLink1') or d.get('corpLink2') or "無"),
        })

    print(f"\n  ===== 最終名單（{len(results)} 家） =====\n")
    for i, c in enumerate(results, 1):
        print(f"  {i}. {c['公司名稱']} | {c['產業']} | {c['員工人數']}")
        print(f"     地址：{c['完整地址']}")
        print(f"     電話：{c['公司電話']}")
        print(f"     HR：{c['HR姓名']}")
        print(f"     官網：{c['公司連結']}")
        print()

    # 摘要
    has_phone = sum(1 for c in results if c['公司電話'] != "無")
    has_hr    = sum(1 for c in results if c['HR姓名'] != "無")
    has_link  = sum(1 for c in results if c['公司連結'] != "無")
    print(f"  ===== 資料完整度統計 =====")
    print(f"  有電話：{has_phone}/{len(results)}")
    print(f"  有HR姓名：{has_hr}/{len(results)}")
    print(f"  有官網連結：{has_link}/{len(results)}")

if __name__ == "__main__":
    companies = search_snack_companies()
    time.sleep(1)

    # 對前兩家深挖
    for c in companies[:2]:
        result = get_company_contact(c['custId'], c['custName'])
        time.sleep(0.8)

    simulate_full_pipeline()
    print("\n========== 完成 ==========")
