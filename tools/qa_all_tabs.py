"""截所有 5 個 tab 的畫面"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "data" / "qa"
OUT.mkdir(parents=True, exist_ok=True)

TABS = ["名單管理", "LinkedIn 人物", "開發信", "歷史紀錄", "追蹤分析"]

async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        for tab_name in TABS:
            try:
                btn = page.get_by_role("tab", name=tab_name)
                await btn.click()
                await page.wait_for_timeout(1500)
                fname = OUT / f"tab_{tab_name}.png"
                await page.screenshot(path=str(fname), full_page=True)
                print(f"[OK] {tab_name} → {fname}")
            except Exception as e:
                print(f"[FAIL] {tab_name}: {e}")

        await b.close()

asyncio.run(run())
