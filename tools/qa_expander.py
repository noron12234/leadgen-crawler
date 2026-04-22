"""展開 Gmail 設定 expander 截圖"""
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
        await page.wait_for_timeout(2000)
        # 切到開發信 tab
        await page.get_by_role("tab", name="開發信").click()
        await page.wait_for_timeout(1500)
        # 展開 Gmail 設定
        try:
            await page.get_by_text("Gmail 設定").click()
            await page.wait_for_timeout(1000)
        except:
            pass
        await page.screenshot(path=str(OUT / "tab_email_expanded.png"), full_page=True)
        print("[OK] 開發信 expander 展開截圖完成")
        await b.close()

asyncio.run(run())
