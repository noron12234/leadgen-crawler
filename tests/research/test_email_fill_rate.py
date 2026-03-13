"""測試 104 職缺詳細頁 contact.email 填充率"""
import sys, requests, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

r = requests.get("https://www.104.com.tw/jobs/search/api/jobs",
    params={"ro":"0","area":"6001001000","order":"15","asc":"0",
            "page":"1","perPage":"20","welfare":"wf27","s9":"1"},
    headers={**H,"Referer":"https://www.104.com.tw/jobs/search/"}, timeout=15)
raw = r.json().get("data", {})
jobs = raw.get("list", []) if isinstance(raw, dict) else raw

has_email = 0
has_hr = 0
results = []

print(f"測試 {len(jobs[:15])} 筆職缺...\n")
for j in jobs[:15]:
    link = j.get("link", {})
    job_url = link.get("job", "") if isinstance(link, dict) else ""
    job_id = job_url.split("/job/")[-1].split("?")[0] if "/job/" in job_url else ""
    cust_name = j.get("custName", "")
    if not job_id:
        continue

    time.sleep(0.4)
    dr = requests.get(f"https://www.104.com.tw/job/ajax/content/{job_id}",
        headers={**H, "Referer": job_url}, timeout=10)
    if dr.status_code != 200:
        continue

    contact = dr.json().get("data", {}).get("contact", {}) or {}
    email = contact.get("email", "")
    hr_name = contact.get("hrName", "")
    phone_list = contact.get("phone") or []

    if email and "@" in email:
        has_email += 1
    if hr_name:
        has_hr += 1

    results.append({"公司": cust_name, "HR": hr_name, "email": email, "phone": phone_list})
    print(f"  {cust_name[:22]:<22} | HR:{hr_name:<12} | email:{email:<35} | tel:{phone_list}")

print(f"\n=== 統計（{len(results)} 筆）===")
print(f"有 email:   {has_email}/{len(results)} ({has_email/max(len(results),1)*100:.0f}%)")
print(f"有 HR 姓名: {has_hr}/{len(results)} ({has_hr/max(len(results),1)*100:.0f}%)")
