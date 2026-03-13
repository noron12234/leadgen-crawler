import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import logging
logging.basicConfig(level=logging.WARNING)

from crawlers.crawler_104 import crawl_snack_companies

print("開始爬取... 台北市 x wf27(零食/下午茶) x 第1頁")
print("=" * 90)

results = crawl_snack_companies(areas=["6001001000"], max_pages=1, delay=0.5)

print(f"\n共爬取 {len(results)} 家公司\n")
print(f"{'公司名稱':<24} {'HR姓名':<12} {'Email':<40} {'電話'}")
print("-" * 100)
for c in results:
    name = (c["cust_name"] or "")[:22]
    hr   = (c.get("hr_name") or "—")[:10]
    email = (c.get("email") or "—")[:38]
    phone = c.get("phone") or "—"
    print(f"{name:<24} {hr:<12} {email:<40} {phone}")

has_email = sum(1 for c in results if c.get("email") and "@" in c.get("email",""))
has_phone = sum(1 for c in results if c.get("phone"))
has_hr    = sum(1 for c in results if c.get("hr_name"))

print()
print("=" * 90)
print(f"有 Email  ：{has_email}/{len(results)}  ({has_email/len(results)*100:.0f}%)")
print(f"有電話    ：{has_phone}/{len(results)}  ({has_phone/len(results)*100:.0f}%)")
print(f"有HR姓名  ：{has_hr}/{len(results)}  ({has_hr/len(results)*100:.0f}%)")
