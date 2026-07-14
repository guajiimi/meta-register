#!/usr/bin/env python3
"""Debug: minimal click test — is the selector matching the right element?"""
import asyncio, os, random
from camoufox.async_api import AsyncCamoufox

async def main():
    async with AsyncCamoufox(headless=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(5, 7))
        print("Landing:", page.url[:80])

        sel = 'div[role="button"]:has-text("Use mobile number or email")'
        all_matches = await page.query_selector_all(sel)
        print(f"\nSelector matches: {len(all_matches)}")
        for i, el in enumerate(all_matches):
            box = await el.bounding_box()
            vis = await el.is_visible()
            txt = (await el.inner_text()).strip()[:60]
            h = box['height'] if box else -1
            w = box['width'] if box else -1
            print(f"  [{i}] h={h:.0f}px w={w:.0f}px vis={vis} text={txt!r}")

        if all_matches:
            el = all_matches[0]
            box = await el.bounding_box()
            print(f"\nClicking via evaluate ...")
            await el.evaluate("el => el.click()")
            await asyncio.sleep(4)
            print(f"Page after click: {page.url[:80]}")
            inputs = await page.query_selector_all('input')
            print(f"Inputs: {len(inputs)}")
            for i, inp in enumerate(inputs):
                vis = (await inp.bounding_box()) is not None
                typ = await inp.get_attribute('type')
                print(f"  [{i}] type={typ} vis={vis}")

        # Dump visible text
        body = (await page.inner_text("body"))[:400]
        print(f"\nVISIBLE TEXT:\n{body}")
        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
