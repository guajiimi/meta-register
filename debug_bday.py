import asyncio, os
os.environ["DISPLAY"] = ":99"

async def main():
    from camoufox.async_api import AsyncCamoufox
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        page = await (await browser.new_context()).new_page()
        page.set_default_timeout(60000)

        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await page.get_by_text("Use mobile number or email").click()
        await asyncio.sleep(3)
        inp = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await inp.click(); await inp.fill("")
        await page.keyboard.type("testxyz888@gmail.com", delay=30)
        await asyncio.sleep(1)
        await page.get_by_text("Continue", exact=True).click()
        await asyncio.sleep(5)
        await page.get_by_role("button", name="Create new account").click()
        await asyncio.sleep(5)

        # Name
        inputs = await page.query_selector_all('input[type="text"]')
        if len(inputs) >= 2:
            await inputs[0].fill("David"); await inputs[1].fill("Smith")
        await page.get_by_role("button", name="Next").click()
        await asyncio.sleep(5)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"Page: {body[:200]}")

        # Birthday - find ALL selects
        selects = await page.evaluate("""
            Array.from(document.querySelectorAll('select')).filter(s => s.offsetParent !== null).map(s => ({
                title: s.title, name: s.name, id: s.id,
                options: Array.from(s.options).slice(0, 5).map(o => ({val: o.value, text: o.text}))
            }))
        """)
        print(f"\nSelects: {json.dumps(selects, indent=2)}")
        
        import json
        # Try selecting with dispatchEvent
        for sel_info in selects:
            title = sel_info.get('title', '')
            if 'month' in title.lower():
                await page.evaluate("document.querySelector('select[title=\"Month\"]').value = '3'; document.querySelector('select[title=\"Month\"]').dispatchEvent(new Event('change', {bubbles: true}))")
                print("  Month: 3")
            elif 'day' in title.lower():
                await page.evaluate("document.querySelector('select[title=\"Day\"]').value = '15'; document.querySelector('select[title=\"Day\"]').dispatchEvent(new Event('change', {bubbles: true}))")
                print("  Day: 15")
            elif 'year' in title.lower():
                await page.evaluate("document.querySelector('select[title=\"Year\"]').value = '1995'; document.querySelector('select[title=\"Year\"]').dispatchEvent(new Event('change', {bubbles: true}))")
                print("  Year: 1995")

        await asyncio.sleep(2)
        
        # Check button state
        btn_state = await page.evaluate("""
            (() => {
                const btn = document.querySelector('div[role="button"]');
                const all = Array.from(document.querySelectorAll('div[role="button"]')).map(b => ({
                    text: b.innerText.trim(),
                    disabled: b.getAttribute('aria-disabled'),
                    visible: b.offsetParent !== null
                }));
                return all;
            })()
        """)
        print(f"\nButtons: {json.dumps(btn_state)}")

        await page.screenshot(path="data/screenshots/bday_debug.png")
        print("\n[DONE]")

asyncio.run(main())
