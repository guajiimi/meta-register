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
    print(f"Email: {email}")
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        page = await (await browser.new_context()).new_page()
        page.set_default_timeout(60000)

        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # Step 1: Click email option
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Use mobile number or email")', timeout=30000)
        await btn.click()
        await asyncio.sleep(3)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[After email option]\n{body[:500]}")
        await page.screenshot(path="data/screenshots/auth_step1.png")

        # Step 2: Fill email
        inputs = await page.evaluate("""
            Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).map(i => ({
                type: i.type, name: i.name, placeholder: i.placeholder, id: i.id
            }))
        """)
        print(f"\nInputs: {inputs}")

        email_input = await page.query_selector('input[type="text"], input[type="email"], input[name="email"]')
        if email_input:
            await email_input.fill(email)
            print(f"Filled email: {email}")
        else:
            print("No email input found!")
        
        await asyncio.sleep(1)
        await page.screenshot(path="data/screenshots/auth_step2.png")

        # Step 3: Click Next
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn:
            await next_btn.click()
            print("Clicked Next")
        
        # Wait and check
        for i in range(5):
            await asyncio.sleep(2)
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"\n[{i*2+2}s]\n{body[:300]}")
            
            inputs = await page.evaluate("""
                Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).map(i => ({
                    type: i.type, name: i.name, placeholder: i.placeholder
                }))
            """)
            print(f"Inputs: {inputs}")
            
            btns = await page.evaluate("""
                Array.from(document.querySelectorAll('button, [role="button"]')).filter(b => b.offsetParent !== null).map(b => b.innerText.trim())
            """)
            print(f"Buttons: {btns}")
            
            if "password" in body.lower() or "create" in body.lower() or "verification" in body.lower():
                break
        
        await page.screenshot(path="data/screenshots/auth_step3.png")
        print("\n[DONE]")

asyncio.run(main())
