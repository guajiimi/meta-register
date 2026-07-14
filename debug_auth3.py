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
        
        # Click email option
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Use mobile number or email")', timeout=30000)
        await btn.click()
        await asyncio.sleep(3)
        
        # Fill email
        email_input = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await email_input.click()
        await email_input.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)
        
        # Click Continue
        cont = page.get_by_text("Continue", exact=True)
        await cont.click(timeout=5000)
        await asyncio.sleep(5)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[After Continue]: {body[:300]}")
        
        # Look for "Enter password instead"
        if "password instead" in body.lower():
            print("\nClicking 'Enter password instead'...")
            pw_link = page.get_by_text("Enter password instead")
            await pw_link.click(timeout=5000)
            await asyncio.sleep(3)
            
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"\n[After password link]: {body[:300]}")
            
            # Fill password
            pw_input = await page.wait_for_selector('input[type="password"]', timeout=10000)
            await pw_input.fill(password)
            await asyncio.sleep(1)
            
            # Click Continue/Log in
            for text in ["Continue", "Log in", "Log In"]:
                try:
                    btn = page.get_by_text(text, exact=True)
                    await btn.click(timeout=3000)
                    print(f"Clicked: {text}")
                    break
                except: continue
            
            await asyncio.sleep(5)
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"\n[After login]: {body[:500]}")
            print(f"URL: {page.url}")
            
            # Check for birthday or OTP
            if "birthday" in body.lower():
                print("\nBirthday needed!")
                # Select month/day/year
                selects = await page.evaluate("""
                    Array.from(document.querySelectorAll('select')).filter(s => s.offsetParent !== null).map(s => ({
                        title: s.title, name: s.name, id: s.id
                    }))
                """)
                print(f"Selects: {selects}")
            
            if "verification" in body.lower() or "code" in body.lower():
                print("\nVerification code needed!")
            
            # Save cookies
            cookies = await (await browser.contexts)[0].cookies()
            print(f"\nCookies: {[c['name'] for c in cookies]}")
        
        await page.screenshot(path="data/screenshots/auth_password.png")
        print("\n[DONE]")

asyncio.run(main())
