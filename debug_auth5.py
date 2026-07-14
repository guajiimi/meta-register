import asyncio, os, random
os.environ["DISPLAY"] = ":99"

def gen_email():
    base = "dewixzpajak01"
    dots = list(base)
    n_dots = random.randint(2, 4)
    positions = sorted(random.sample(range(1, len(dots)), n_dots))
    for i, pos in enumerate(positions):
        dots.insert(pos + i, '.')
    return ''.join(dots) + '@gmail.com'

async def main():
    from camoufox.async_api import AsyncCamoufox
    email = gen_email()
    password = "MetaReg2026!"
    print(f"Email: {email}")
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(60000)

        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 1. Click email option
        await page.wait_for_selector(':is(button, [role="button"]):has-text("Use mobile number or email")', timeout=30000).then(lambda el: el.click())
        await asyncio.sleep(3)
        
        # 2. Fill email
        inp = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await inp.click(); await inp.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)
        
        # 3. Continue
        await page.get_by_text("Continue", exact=True).click()
        await asyncio.sleep(5)
        
        # 4. Enter password instead
        await page.get_by_role("button", name="Enter password instead").click()
        await asyncio.sleep(3)
        
        # 5. Fill password
        pw = await page.wait_for_selector('input[type="password"]', timeout=10000)
        await pw.fill(password)
        await asyncio.sleep(1)
        
        # 6. Click "Next" (on password page)
        await page.get_by_role("button", name="Next").click()
        await asyncio.sleep(5)
        
        body = await page.evaluate("document.body?.innerText || ''")
        url = page.url
        print(f"\n[Result]: {body[:500]}")
        print(f"URL: {url}")
        
        # Handle different outcomes
        for step in range(10):
            if "birthday" in body.lower() and ("year" in body.lower() or "month" in body.lower()):
                print(f"\n→ Filling birthday...")
                for title, val in [("Month", "3"), ("Day", "15"), ("Year", "1995")]:
                    sel = await page.query_selector(f'select[title="{title}"]')
                    if sel: await sel.select_option(value=val); print(f"  {title}: {val}")
                await page.get_by_role("button", name="Next").click()
                await asyncio.sleep(5)
                body = await page.evaluate("document.body?.innerText || ''")
                continue
            
            if "continue" in body.lower() and "welcome" not in body.lower():
                # Maybe a "Continue" button for onboarding
                try:
                    await page.get_by_role("button", name="Continue").click(timeout=3000)
                    await asyncio.sleep(3)
                    body = await page.evaluate("document.body?.innerText || ''")
                    continue
                except: pass
            
            break
        
        # Extract cookies
        all_cookies = await context.cookies()
        cookie_dict = {}
        for c in all_cookies:
            if c['name'] in ['datr', 'ps_l', 'ps_n', 'llm_sess', 'locale', 'fs', 'wd', 'fr', 'sb', 'c_user']:
                cookie_dict[c['name']] = c['value']
        
        print(f"\n[Final]: {body[:500]}")
        print(f"URL: {url}")
        print(f"Cookies: {list(cookie_dict.keys())}")
        
        await page.screenshot(path="data/screenshots/auth_final.png")
        print("\n[DONE]")

asyncio.run(main())
