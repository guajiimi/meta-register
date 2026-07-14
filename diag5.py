#!/usr/bin/env python3
"""Debug: check buttons and form state on Meta OTP screen after code entry."""
import asyncio, os, random, time
from camoufox.async_api import AsyncCamoufox
from bot import IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS, fetch_otp

async def main():
    email_addr = "d.e.w.i.x.z.p.a.j.a.k.0.1@gmail.com"
    reg_ts = time.time()

    async with AsyncCamoufox(headless=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(5, 7))

        print("Landing URL:", page.url[:80])
        body0 = (await page.inner_text("body"))[:400]
        print(f"Landing text:\n{body0}\n")

        # Try "Use email" — might not be there if already on form
        try:
            el = await page.wait_for_selector('div[role="button"]:has-text("Use mobile number or email")', timeout=5000, state="visible")
            if el and (await el.bounding_box() or {}).get("height", 0) >= 20:
                await el.evaluate("el => el.click()")
                print("Clicked 'Use email'")
                await asyncio.sleep(3)
        except Exception:
            print("'Use email' not found — might already be on form page")

        # Check if email input is visible
        try:
            inp = await page.wait_for_selector('input[autocomplete="username"], input[inputmode="email"], input:not([type="password"]):not([type="hidden"])', timeout=5000, state="visible")
            await inp.fill(email_addr)
            print(f"Email filled: {email_addr}")
            await asyncio.sleep(0.5)

            # Click Continue
            cont = await page.wait_for_selector('div[role="button"]:has-text("Continue")', timeout=5000, state="visible")
            for _ in range(20):
                dis = await cont.get_attribute("aria-disabled")
                if dis != "true":
                    break
                await asyncio.sleep(0.5)
            await cont.evaluate("el => el.click()")
            print("Continue clicked")
            await asyncio.sleep(4)
        except Exception as e:
            print(f"Email/Continue flow error: {e}")

        # Dump all visible text on current page
        body = (await page.inner_text("body"))[:600]
        print(f"\n=== CURRENT PAGE ===\n{body}")

        # Check for any input fields
        inputs = await page.query_selector_all('input')
        print(f"\nInputs: {len(inputs)}")
        for i, inp in enumerate(inputs):
            vis = (await inp.bounding_box()) is not None
            typ = await inp.get_attribute("type")
            mode = await inp.get_attribute("inputmode")
            label = await inp.get_attribute("aria-label")
            print(f"  [{i}] type={typ} inputmode={mode} label={label} vis={vis}")

        # Check ALL buttons
        buttons = await page.query_selector_all('div[role="button"], button, a')
        print(f"\nButtons/links: {len(buttons)}")
        for i, btn in enumerate(buttons[:15]):
            txt = (await btn.inner_text()).strip()[:60]
            vis = (await btn.bounding_box()) is not None
            dis = await btn.get_attribute("aria-disabled")
            tag = await btn.evaluate('e => e.tagName')
            print(f"  [{i}] {tag} vis={vis} dis={dis} text={txt!r}")

        # Wait for OTP email
        otp_code = fetch_otp(email_addr, timeout=90, since_ts=reg_ts)
        print(f"\nOTP code: {otp_code}")

        if otp_code:
            # Try to find and fill OTP input
            otp_input = None
            for sel in ['input[type="text"]', 'input[type="tel"]', 'input[inputmode="numeric"]', 'input[aria-label*="code" i]']:
                try:
                    otp_input = await page.wait_for_selector(sel, timeout=3000, state="visible")
                    if otp_input:
                        break
                except:
                    continue
            if not otp_input:
                # Fallback: any visible empty input
                for inp_el in inputs:
                    vis = (await inp_el.bounding_box()) is not None
                    val = await inp_el.get_attribute("value") or ""
                    if vis and not val:
                        otp_input = inp_el
                        break

            if otp_input:
                await otp_input.fill(otp_code)
                print(f"OTP filled: {otp_code}")
                await asyncio.sleep(2)

                # Dump state AFTER OTP fill
                body2 = (await page.inner_text("body"))[:600]
                print(f"\n=== AFTER OTP FILL ===\n{body2}")

                buttons2 = await page.query_selector_all('div[role="button"], button')
                print(f"\nButtons after OTP: {len(buttons2)}")
                for i, btn in enumerate(buttons2[:10]):
                    txt = (await btn.inner_text()).strip()[:60]
                    vis = (await btn.bounding_box()) is not None
                    dis = await btn.get_attribute("aria-disabled")
                    print(f"  [{i}] vis={vis} dis={dis} text={txt!r}")

                # Try pressing Enter (some forms auto-submit)
                await otp_input.press("Enter")
                print("Pressed Enter on OTP input")
                await asyncio.sleep(5)

                print(f"\nURL after Enter: {page.url[:100]}")
                body3 = (await page.inner_text("body"))[:600]
                print(f"\n=== AFTER ENTER ===\n{body3}")
            else:
                print("No OTP input found!")
        else:
            print("OTP timeout!")

        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
