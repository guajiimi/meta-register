import asyncio, os, random, string
os.environ["DISPLAY"] = ":99"

def fresh_email():
    user = ''.join(random.choices(string.ascii_lowercase, k=6)) + str(random.randint(100,999))
    return f"{user}@gmail.com"

async def main():
    from camoufox.async_api import AsyncCamoufox
    email = fresh_email()
    print(f"Email: {email}")
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        page = await (await browser.new_context()).new_page()
        page.set_default_timeout(60000)

        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        await page.get_by_text("Use mobile number or email").click()
        await asyncio.sleep(3)
        
        inp = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await inp.click(); await inp.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)
        
        await page.get_by_text("Continue", exact=True).click()
        await asyncio.sleep(5)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[1] {body[:300]}")
        
        btns = await page.evaluate("""
            Array.from(document.querySelectorAll('div[role="button"], button'))
                .filter(b => b.offsetParent !== null)
                .map(b => b.innerText.trim())
        """)
        print(f"Buttons: {btns}")
        
        await page.screenshot(path="data/screenshots/register_step1.png")
        
        # Try clicking Create/Sign up
        for text in ["Create account", "Create", "Sign up", "Next", "Continue"]:
            try:
                await page.get_by_role("button", name=text).click(timeout=3000)
                print(f"Clicked: {text}")
                await asyncio.sleep(5)
                break
            except: continue
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[2] {body[:300]}")
        
        btns = await page.evaluate("""
            Array.from(document.querySelectorAll('div[role="button"], button'))
                .filter(b => b.offsetParent !== null)
                .map(b => b.innerText.trim())
        """)
        print(f"Buttons: {btns}")
        
        inputs = await page.evaluate("""
            Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).map(i => ({
                type: i.type, name: i.name, id: i.id
            }))
        """)
        print(f"Inputs: {inputs}")
        
        await page.screenshot(path="data/screenshots/register_step2.png")
        
        # If password field visible, fill it
        pw = await page.query_selector('input[type="password"]')
        if pw:
            print("\nPassword field found!")
            await pw.fill("MetaReg2026!")
        
        print("\n[DONE]")

asyncio.run(main())
