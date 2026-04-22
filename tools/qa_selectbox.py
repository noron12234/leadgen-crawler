"""點開 selectbox dropdown 截圖，找白字白底"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "data" / "qa"

async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2500)

        # 截「關閉」狀態
        await page.screenshot(path=str(OUT / "selectbox_closed.png"))

        # 點開 selectbox
        try:
            sel = page.locator('[data-testid="stSelectbox"]').first
            await sel.click()
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(OUT / "selectbox_open.png"), full_page=False)
            print("[OK] selectbox open → selectbox_open.png")
        except Exception as e:
            print(f"[FAIL] {e}")

        await b.close()

asyncio.run(run())
