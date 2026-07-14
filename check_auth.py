import asyncio, os
os.environ["DISPLAY"] = ":99"

async def main():
    from camoufox.async_api import AsyncCamoufox
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        page = await (await browser.new_context()).new_page()
        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"URL: {page.url}")
        print(f"Body: {body[:500]}")
        btns = await page.evaluate("""
            Array.from(document.querySelectorAll('button, [role="button"], a[role="button"]')).map(b => b.innerText.trim()).filter(t => t)
        """)
        print(f"Buttons: {btns}")
        await page.screenshot(path="data/screenshots/auth_page.png")
asyncio.run(main())
