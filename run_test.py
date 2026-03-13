import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import logging
logging.basicConfig(level=logging.WARNING)

from crawlers.crawler_104 import crawl_snack_companies

print("開始爬取... 台北市 x wf27 x 第1頁")
print("=" * 90)

results = crawl_snack_companies(areas=["6001001000"], max_pages=1, delay=0.5)

print(f"\n共爬取 {len(results)} 家公司\n")
header = "{:<24} {:<12} {:<40} {}".format("公司名稱","HR姓名","Email","電話")
print(header)
print("-" * 100)
for c in results:
    name  = (c["cust_name"] or "")[:22]
    hr    = (c.get("hr_name") or "-")[:10]
    email = (c.get("email") or "-")[:38]
    phone = c.get("phone") or "-"
    row = "{:<24} {:<12} {:<40} {}".format(name, hr, email, phone)
    print(row)

has_email = sum(1 for c in results if c.get("email") and "@" in c.get("email",""))
has_phone = sum(1 for c in results if c.get("phone"))
has_hr    = sum(1 for c in results if c.get("hr_name"))

print()
print("=" * 90)
print("有 Email  ：{}/{}  ({}%)".format(has_email, len(results), round(has_email/len(results)*100)))
print("有電話    ：{}/{}  ({}%)".format(has_phone, len(results), round(has_phone/len(results)*100)))
print("有HR姓名  ：{}/{}  ({}%)".format(has_hr, len(results), round(has_hr/len(results)*100)))
