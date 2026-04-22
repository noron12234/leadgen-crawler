"""
UI 對比度診斷：截圖 + 找出所有白底區塊，自動回報哪裡對比不足
用法：python tools/qa_screenshot.py
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "data" / "qa"
OUT.mkdir(parents=True, exist_ok=True)


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2500)

        # 全頁截圖
        shot = OUT / "full.png"
        await page.screenshot(path=str(shot), full_page=True)
        print(f"[OK] 全頁截圖 → {shot}")

        # 找出所有白或接近白的背景元素
        issues = await page.evaluate(r"""
() => {
  const out = [];
  const all = document.querySelectorAll('*');
  for (const el of all) {
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    if (!bg) continue;
    const m = bg.match(/rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
    if (!m) continue;
    const r = +m[1], g = +m[2], b = +m[3], a = m[4] === undefined ? 1 : +m[4];
    if (a < 0.5) continue;
    // 接近白：全部 >= 240
    if (r < 240 || g < 240 || b < 240) continue;

    const fg = cs.color;
    const fm = fg.match(/rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)/);
    const fr = fm ? +fm[1] : 0;
    const fg_ = fm ? +fm[2] : 0;
    const fb = fm ? +fm[3] : 0;
    // 字色也很亮 → 白字白底問題
    const fgBright = (fr + fg_ + fb) > 600;
    const rect = el.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) continue;
    if (rect.width * rect.height < 200) continue;

    out.push({
      tag: el.tagName,
      testid: el.getAttribute('data-testid') || '',
      baseweb: el.getAttribute('data-baseweb') || '',
      role: el.getAttribute('role') || '',
      classes: (el.className || '').toString().slice(0, 80),
      bg, fg,
      fgBright,
      w: Math.round(rect.width),
      h: Math.round(rect.height),
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      text: (el.textContent || '').trim().slice(0, 40),
    });
  }
  return out.slice(0, 40);
}
""")

        print(f"\n[找到 {len(issues)} 個白底/接近白底元素]\n")
        for i, it in enumerate(issues):
            flag = "[!] 白字白底" if it["fgBright"] else ""
            print(f"{i+1:2}. {it['tag']} "
                  f"testid='{it['testid']}' baseweb='{it['baseweb']}' "
                  f"{it['w']}x{it['h']}@({it['x']},{it['y']}) "
                  f"bg={it['bg']} fg={it['fg']} {flag}")
            if it["text"]:
                print(f"    text: {it['text']!r}")

        await browser.close()


asyncio.run(run())
