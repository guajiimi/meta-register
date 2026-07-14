#!/usr/bin/env python3
"""Debug step 3: dump all input attributes after clicking 'Use email'."""
import asyncio, os, random
from camoufox.async_api import AsyncCamoufox

async def main():
    async with AsyncCamoufox(headless=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(5, 7))

        # Click "Use email" — we know this works
        sel = 'div[role="button"]:has-text("Use mobile number or email")'
        el = await page.wait_for_selector(sel, timeout=10000, state="visible")
        await el.evaluate("el => el.click()")
        await asyncio.sleep(3)

        print("=== AFTER 'Use email' CLICK ===")
        print("URL:", page.url[:100])

        # Dump ALL inputs with every attribute
        inputs = await page.query_selector_all('input')
        print(f"\nAll inputs: {len(inputs)}")
        for i, inp in enumerate(inputs):
            attrs = await inp.evaluate('''el => {
                let r = {};
                for (let a of el.attributes) r[a.name] = a.value;
                return r;
            }''')
            vis = (await inp.bounding_box()) is not None
            print(f"  [{i}] vis={vis} attrs={attrs}")

        # Also check div/textbox elements
        textboxes = await page.query_selector_all('[role="textbox"], [contenteditable="true"]')
        print(f"\nTextboxes: {len(textboxes)}")
        for i, tb in enumerate(textboxes):
            attrs = await tb.evaluate('''el => {
                let r = {};
                for (let a of el.attributes) r[a.name] = a.value;
                return r;
            }''')
            vis = (await tb.bounding_box()) is not None
            print(f"  [{i}] vis={vis} attrs={attrs}")

        # Also check buttons
        buttons = await page.query_selector_all('div[role="button"], button')
        print(f"\nButtons: {len(buttons)}")
        for i, btn in enumerate(buttons[:8]):
            txt = (await btn.inner_text()).strip()[:60]
            vis = (await btn.bounding_box()) is not None
            dis = await btn.get_attribute("aria-disabled")
            print(f"  [{i}] vis={vis} dis={dis} text={txt!r}")

        # Visible text
        body = (await page.inner_text("body"))[:400]
        print(f"\nVISIBLE:\n{body}")

        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
