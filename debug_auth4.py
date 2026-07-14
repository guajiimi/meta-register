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
        page = await (await browser.new_context()).new_page()
        page.set_default_timeout(60000)

        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 1. Click email option
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Use mobile number or email")', timeout=30000)
        await btn.click()
        await asyncio.sleep(3)
        
        # 2. Fill email
        email_input = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await email_input.click()
        await email_input.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)
        
        # 3. Continue
        await page.get_by_text("Continue", exact=True).click()
        await asyncio.sleep(5)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[OTP page]: {body[:200]}")
        
        # 4. Click "Enter password instead" (use .first or role)
        await page.get_by_role("button", name="Enter password instead").click()
        await asyncio.sleep(3)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[Password page]: {body[:300]}")
        
        # 5. Fill password
        pw_input = await page.wait_for_selector('input[type="password"]', timeout=10000)
        await pw_input.fill(password)
        await asyncio.sleep(1)
        
        # 6. Log in
        await page.get_by_role("button", name="Continue").click()
        await asyncio.sleep(5)
        
        body = await page.evaluate("document.body?.innerText || ''")
        url = page.url
        print(f"\n[After login]: {body[:500]}")
        print(f"URL: {url}")
        
        # Check what happened
        if "birthday" in body.lower():
            print("\n→ Birthday page")
        elif "verification" in body.lower() or "code" in body.lower():
            print("\n→ Verification code page")
        elif "welcome" in body.lower() or "meta ai" in body.lower():
            print("\n→ Logged in!")
        elif "create" in body.lower():
            print("\n→ Create account flow")
        else:
            print(f"\n→ Unknown page")
        
        await page.screenshot(path="data/screenshots/auth_password_flow.png")
        print("\n[DONE]")

asyncio.run(main())
