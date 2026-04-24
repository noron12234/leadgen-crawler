"""
seed_fake_leads.py — CLI wrapper for demo_data

本地：  python tools/seed_fake_leads.py
Fly：   fly ssh console -C "python /app/tools/seed_fake_leads.py"
清除：  加 --clear
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from demo_data import (
    build_demo_companies, seed_demo_companies, clear_demo_companies,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="刪除所有 seed 測試公司")
    ap.add_argument("--inbox", help="主要收件信箱（必填，除 --clear 外）")
    ap.add_argument("--inbox2", default=None, help="次要收件信箱（可選）")
    args = ap.parse_args()

    if args.clear:
        n = clear_demo_companies()
        print(f"已刪除 {n} 筆測試公司（source=seed_test）")
        return

    if not args.inbox:
        ap.error("請用 --inbox 指定主要收件信箱（例：--inbox you@gmail.com）")

    print("=" * 60)
    print(f"灌入 10 筆假公司（email 分流至 {args.inbox}"
          + (f" / {args.inbox2}" if args.inbox2 else "") + "）")
    print("=" * 60)
    new_n, upd_n = seed_demo_companies(
        inbox_primary=args.inbox, inbox_secondary=args.inbox2,
        crawled_by="seed_script",
    )
    print(f"新增 {new_n} 筆，更新 {upd_n} 筆\n")
    for i, c in enumerate(
        build_demo_companies(inbox_primary=args.inbox, inbox_secondary=args.inbox2), 1
    ):
        print(f"  {i:02d}. {c['cust_name']:<30}  →  {c['email']}")
    print("\n下一步：")
    print("  1. 打開 https://leadgen-app.fly.dev")
    print("  2. 用 baralla 登入 → 開發信 tab")
    print("  3. 設定寄件 Gmail + App Password")
    print("  4. 勾選上面 10 筆「測試公司」→ 寄送")
    print(f"  5. 去 {args.inbox} 收信、打開、點連結")
    print("  6. 回到「📈 追蹤分析」tab 看統計動起來")


if __name__ == "__main__":
    main()
