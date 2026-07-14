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
        
        # Click email option
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Use mobile number or email")', timeout=30000)
        await btn.click()
        await asyncio.sleep(3)
        
        # Fill email using keyboard
        email_input = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await email_input.click()
        await asyncio.sleep(0.5)
        await email_input.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)
        
        # Verify value
        val = await email_input.input_value()
        print(f"Input value: '{val}'")
        
        # Click Continue using multiple methods
        print("Trying Continue click...")
        
        # Method 1: locator
        try:
            cont = page.get_by_text("Continue", exact=True)
            await cont.click(timeout=5000)
            print("  Method 1 (get_by_text) clicked")
        except Exception as e:
            print(f"  Method 1 failed: {e}")
        
        await asyncio.sleep(5)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\nAfter click: {body[:500]}")
        
        # Check if we moved forward
        inputs = await page.evaluate("""
            Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).map(i => ({
                type: i.type, name: i.name, id: i.id
            }))
        """)
        print(f"Inputs: {inputs}")
        
        # If still on same page, try force click
        if "mobile number or email" in body.lower():
            print("\nStill on same page. Trying force click...")
            # Find the Continue button by position
            btns = await page.evaluate("""
                Array.from(document.querySelectorAll('div[role="button"], button')).map(b => ({
                    text: b.innerText.trim(),
                    rect: b.getBoundingClientRect(),
                    tag: b.tagName,
                    visible: b.offsetParent !== null
                })).filter(b => b.visible && b.text === 'Continue')
            """)
            print(f"Continue buttons: {btns}")
            
            if btns:
                e = btns[0]['rect']
                await page.mouse.click(e['x'] + e['width']/2, e['y'] + e['height']/2)
                print("  Force clicked")
                await asyncio.sleep(5)
                body = await page.evaluate("document.body?.innerText || ''")
                print(f"  After force: {body[:500]}")
        
        await page.screenshot(path="data/screenshots/auth_click_debug.png")
        print("\n[DONE]")

asyncio.run(main())
