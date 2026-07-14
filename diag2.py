#!/usr/bin/env python3
"""Fix: test clicking 'Use email' link properly, then verify email input appears."""
import asyncio, os, random
from camoufox.async_api import AsyncCamoufox

async def main():
    async with AsyncCamoufox(headless=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(5, 8))
        print("Page loaded:", page.url)

        # Dump ALL clickable elements on landing
        print("\n--- ALL role=button, a, [onclick] ---")
        for sel in ['div[role="button"]', 'a', '[onclick]']:
            els = await page.query_selector_all(sel)
            for i, el in enumerate(els[:15]):
                txt = (await el.inner_text()).strip()[:80]
                box = await el.bounding_box()
                href = await el.get_attribute("href")
                print(f"  {sel}[{i}] text={txt!r} href={href!r} box={box}")

        # Look for anything with "email" or "number" in text
        print("\n--- Elements containing 'email' or 'number' ---")
        all_els = await page.query_selector_all('*')
        for el in all_els[:200]:
            try:
                txt = (await el.inner_text()).strip().lower()
                if ('email' in txt or 'number' in txt or 'mobile' in txt) and len(txt) < 100:
                    tag = await el.evaluate('e => e.tagName')
                    box = await el.bounding_box()
                    print(f"  {tag} text={txt!r} box={box}")
            except:
                pass

        # Try clicking with coordinates if we find the "Use email" link
        print("\n--- Trying to click via text locator ---")
        try:
            link = await page.query_selector('a:has-text("Use mobile number or email")')
            if link:
                print("  Found via 'a:has-text'")
                await link.scroll_into_view_if_needed()
                box = await link.bounding_box()
                print(f"  Box: {box}")
                # Use JavaScript click for reliability
                await link.evaluate('el => el.click()')
                print("  JS click fired")
            else:
                # Try partial text
                link = await page.query_selector('[href*="email"], [data-testid*="email"]')
                if link:
                    print(f"  Found via href/data-testid")
                    await link.evaluate('el => el.click()')
                else:
                    # Fallback: click by coordinates where text appears
                    print("  No link found via selectors, trying page.click with coordinates")
                    await page.click('text="Use mobile number or email"')
        except Exception as e:
            print(f"  Click failed: {e}")

        await asyncio.sleep(random.uniform(3, 5))
        print("\n--- AFTER CLICK STATE ---")
        print("  URL:", page.url)
        inputs = await page.query_selector_all('input')
        print(f"  Inputs: {len(inputs)}")
        for i, inp in enumerate(inputs):
            typ = await inp.get_attribute("type")
            name = await inp.get_attribute("name")
            vis = (await inp.bounding_box()) is not None
            print(f"    [{i}] type={typ!r} name={name!r} visible={vis}")

        # Check if "Account creation form" text appeared
        body = (await page.inner_text("body"))[:2000].lower()
        print(f"\n  Page contains 'create': {'create' in body}")
        print(f"  Page contains 'account': {'account' in body}")
        print(f"  Page contains 'confirm': {'confirm' in body}")
        print(f"  Page contains 'birthday': {'birthday' in body}")

        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
