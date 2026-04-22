"""鎖定 sidebar (30, 567) 那個 16x16 白字白底元素的完整 selector path"""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2500)

        info = await page.evaluate(r"""
() => {
  const el = document.elementFromPoint(38, 575);
  if (!el) return { found: false };
  const chain = [];
  let cur = el;
  for (let i = 0; i < 8 && cur; i++) {
    const cs = getComputedStyle(cur);
    chain.push({
      tag: cur.tagName,
      testid: cur.getAttribute('data-testid') || '',
      baseweb: cur.getAttribute('data-baseweb') || '',
      role: cur.getAttribute('role') || '',
      aria: cur.getAttribute('aria-checked') || '',
      classes: (cur.className || '').toString().slice(0, 100),
      bg: cs.backgroundColor,
      fg: cs.color,
    });
    cur = cur.parentElement;
  }
  return { found: true, chain };
}
""")

        print("DOM chain for (38, 575):")
        for i, item in enumerate(info.get("chain", [])):
            print(f"  {i}. {item['tag']} testid={item['testid']!r} baseweb={item['baseweb']!r} role={item['role']!r} aria-checked={item['aria']!r}")
            print(f"      classes: {item['classes']}")
            print(f"      bg={item['bg']}  fg={item['fg']}")

        await browser.close()


asyncio.run(run())
