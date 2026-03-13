"""
Playwright 測試：LinkedIn 不登入能看到什麼
測試公司員工搜尋功能
"""
import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

async def test_linkedin_no_login():
    from playwright.async_api import async_playwright

    print("\n=== LinkedIn Playwright 測試（不登入）===\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()

        # 1. 試試公司頁面的員工列表
        print("--- 測試 1：公司員工搜尋頁（不登入）---")
        await page.goto("https://www.linkedin.com/company/google/people/", timeout=20000)
        await page.wait_for_timeout(3000)

        url_now = page.url
        print(f"最終 URL：{url_now}")

        if "login" in url_now or "authwall" in url_now:
            print("[XX] 直接被導去登入頁 - 員工資料需要登入")
        else:
            print("[OK] 能看到內容")
            # 看看有沒有員工資料
            content = await page.content()
            has_people = "people" in content.lower() and ("hr" in content.lower() or "human" in content.lower())
            print(f"[--] 有 HR 相關內容：{has_people}")

        # 2. 試試職缺搜尋（有些不需要登入）
        print("\n--- 測試 2：職缺搜尋（不登入）---")
        await page.goto("https://www.linkedin.com/jobs/search/?keywords=HR+Manager&location=Taipei", timeout=20000)
        await page.wait_for_timeout(4000)

        url_now = page.url
        print(f"最終 URL：{url_now[:80]}")

        if "authwall" in url_now:
            print("[XX] 被封到登入牆")
        else:
            # 數職缺卡片
            cards = await page.query_selector_all(".job-search-card, .base-card, [data-job-id]")
            print(f"[OK] 找到 {len(cards)} 個職缺卡片")
            if cards:
                # 取第一張
                try:
                    title = await cards[0].query_selector(".base-search-card__title, h3")
                    company = await cards[0].query_selector(".base-search-card__subtitle, h4")
                    t_text = await title.inner_text() if title else "N/A"
                    c_text = await company.inner_text() if company else "N/A"
                    print(f"[OK] 職缺：{t_text.strip()} @ {c_text.strip()}")
                except:
                    pass

        # 3. 試試人才搜尋（無登入）
        print("\n--- 測試 3：人才搜尋（不登入）---")
        await page.goto("https://www.linkedin.com/search/results/people/?keywords=HR+Manager+Taiwan", timeout=20000)
        await page.wait_for_timeout(3000)

        url_now = page.url
        if "authwall" in url_now or "login" in url_now:
            print("[XX] 人才搜尋需要登入 - 無法不登入搜尋 HR")
        else:
            print("[OK] 可以搜尋")
            content = await page.content()
            names = await page.query_selector_all(".entity-result__title-text, .actor-name")
            print(f"[OK] 找到 {len(names)} 個人名")

        await browser.close()

async def test_cake_playwright():
    from playwright.async_api import async_playwright

    print("\n\n=== Cake.me Playwright 測試 ===\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        print("--- 測試 Cake 職缺列表 ---")
        await page.goto("https://www.cake.me/jobs?q=&location=taipei", timeout=30000)
        await page.wait_for_timeout(5000)  # 等 JS 渲染

        # 等待職缺卡片載入
        try:
            await page.wait_for_selector("[class*='JobCard'], [class*='job-card'], [data-job]", timeout=10000)
            cards = await page.query_selector_all("[class*='JobCard'], [class*='job-card']")
            print(f"[OK] 找到 {len(cards)} 個職缺卡片")

            if cards:
                c = cards[0]
                # 嘗試取資料
                title_el  = await c.query_selector("[class*='title'], h3, h2")
                company_el = await c.query_selector("[class*='company'], [class*='employer']")
                title   = await title_el.inner_text()  if title_el   else "N/A"
                company = await company_el.inner_text() if company_el else "N/A"
                print(f"[OK] 第一筆：{title.strip()} @ {company.strip()}")

                # 點進去看有沒有 HR 資訊
                try:
                    await cards[0].click()
                    await page.wait_for_timeout(3000)
                    hr_el = await page.query_selector("[class*='recruiter'], [class*='hr'], [class*='contact']")
                    if hr_el:
                        hr_text = await hr_el.inner_text()
                        print(f"[OK] HR 資訊：{hr_text.strip()[:100]}")
                    else:
                        print("[XX] 職缺詳細沒有 HR 資訊")
                except Exception as e:
                    print(f"[--] 點擊職缺失敗：{e}")

        except Exception as e:
            print(f"[XX] 等待職缺卡片失敗：{e}")
            # 看看頁面有什麼
            content = await page.content()
            print(f"[--] 頁面大小：{len(content)} bytes")
            job_count_el = await page.query_selector("[class*='job-count'], [class*='result-count']")
            if job_count_el:
                count = await job_count_el.inner_text()
                print(f"[--] 職缺數量文字：{count}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_linkedin_no_login())
    asyncio.run(test_cake_playwright())
    print("\n========== Playwright 測試完成 ==========")
