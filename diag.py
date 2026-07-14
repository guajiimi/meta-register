#!/usr/bin/env python3
"""Diagnostic: walk through Meta registration, dump DOM at each step."""
import asyncio, sys, os, random
sys.path.insert(0, os.path.dirname(__file__))

from camoufox.async_api import AsyncCamoufox
from bot import IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS, random_name, random_birthday

async def main():
    email_addr = sys.argv[1] if len(sys.argv) > 1 else "d.e.wi.xz.paja.k.01@gmail.com"
    password = "T3stP@ss_" + str(random.randint(1000,9999))
    first, last = random_name()
    month, day, year = random_birthday()

    print(f"Email: {email_addr}")
    print(f"Name: {first} {last}")
    print(f"Password: {password}")
    print(f"Birthday: {month} {day}, {year}")
    print("="*60)

    async with AsyncCamoufox(headless=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(4, 7))

        # ---- Step 1: dump landing page
        print("\n[STEP 1] LANDING PAGE")
        print("  URL:", page.url)
        btn = await page.query_selector('text="Use mobile number or email"')
        print(f"  'Use email' button found: {btn is not None}")
        if btn:
            box = await btn.bounding_box()
            print(f"  Bounding box: {box}")

        # Click "Use email"
        if btn:
            await btn.click()
            await asyncio.sleep(random.uniform(2, 4))

        # ---- Step 2: after clicking "Use email"
        print("\n[STEP 2] AFTER 'USE EMAIL' CLICK")
        print("  URL:", page.url)
        email_input = await page.query_selector('input[aria-label*="email" i], input[type="email"]')
        print(f"  Email input found: {email_input is not None}")

        # Enter email
        if email_input:
            await email_input.fill(email_addr)
            continue_btn = await page.query_selector('div[role="button"]:has-text("Continue")')
            print(f"  Continue button found: {continue_btn is not None}")
            if continue_btn:
                await continue_btn.click()
                await asyncio.sleep(random.uniform(3, 5))

        # ---- Step 3: check what loaded after Continue
        print("\n[STEP 3] AFTER CONTINUE (form state)")
        print("  URL:", page.url)
        page_text = (await page.inner_text("body")).lower()

        # Look for all comboboxes
        cbs = await page.query_selector_all('div[role="combobox"]')
        print(f"  Comboboxes found: {len(cbs)}")
        for i, cb in enumerate(cbs):
            label = await cb.get_attribute("aria-label")
            val = await cb.get_attribute("aria-valuenow") or await cb.inner_text()
            box = await cb.bounding_box()
            print(f"    [{i}] label={label!r} val={val!r} visible={box is not None}")

        # Look for text inputs
        inputs = await page.query_selector_all('input[type="text"], input[type="password"]')
        print(f"  Text inputs found: {len(inputs)}")
        for i, inp in enumerate(inputs):
            name = await inp.get_attribute("name")
            ph = await inp.get_attribute("placeholder")
            label = await inp.get_attribute("aria-label")
            vis = (await inp.bounding_box()) is not None
            print(f"    [{i}] name={name!r} ph={ph!r} label={label!r} visible={vis}")

        # Look for ALL role=button elements
        buttons = await page.query_selector_all('div[role="button"], button')
        print(f"  Buttons found: {len(buttons)}")
        for i, btn in enumerate(buttons):
            txt = (await btn.inner_text()).strip()[:60]
            box = await btn.bounding_box()
            disabled = await btn.get_attribute("aria-disabled")
            print(f"    [{i}] text={txt!r} disabled={disabled} visible={box is not None} box={box}")

        # Check for "Save login info" checkbox
        checkbox = await page.query_selector('div[role="checkbox"], input[type="checkbox"]')
        print(f"  Checkbox found: {checkbox is not None}")
        if checkbox:
            checked = await checkbox.get_attribute("aria-checked")
            label = await checkbox.get_attribute("aria-label")
            print(f"    aria-checked={checked!r} aria-label={label!r}")

        # ---- Step 4: fill birthday, name, password
        print("\n[STEP 4] FILLING FORM...")
        month_cbs = await page.query_selector_all('div[role="combobox"]')
        if len(month_cbs) >= 3:
            # Birthday
            for idx, (label, value) in enumerate([(None, month), (None, day), (None, year)]):
                cb = month_cbs[idx]
                await cb.click()
                await asyncio.sleep(0.4)
                opts = []
                for lb in await page.query_selector_all('[role="listbox"]'):
                    if await lb.get_attribute("aria-hidden") == "true" or not await lb.is_visible():
                        continue
                    opts = await lb.query_selector_all('[role="option"]')
                    if opts: break
                for opt in opts:
                    if value.lower() in (await opt.inner_text()).strip().lower():
                        await opt.scroll_into_view_if_needed()
                        await opt.click()
                        break
                await asyncio.sleep(0.4)
                print(f"  Birthday field {idx} clicked: {value}")

            # Name
            name_inputs = await page.query_selector_all('input[type="text"]')
            if len(name_inputs) >= 2:
                await name_inputs[0].fill(first)
                await name_inputs[1].fill(last)
                print(f"  Name filled: {first} {last}")

            # Password
            pw_input = await page.query_selector('input[type="password"]')
            if pw_input:
                await pw_input.fill(password)
                print(f"  Password filled")

        await asyncio.sleep(1)

        # ---- Step 5: DUMP FINAL STATE — this is the critical diagnostic
        print("\n[STEP 5] PRE-CONFIRM PAGE STATE (CRITICAL)")
        print("  URL:", page.url)

        # Re-check all buttons after filling
        buttons2 = await page.query_selector_all('div[role="button"], button')
        print(f"  Buttons after fill: {len(buttons2)}")
        for i, btn in enumerate(buttons2):
            txt = (await btn.inner_text()).strip()[:60]
            box = await btn.bounding_box()
            disabled = await btn.get_attribute("aria-disabled")
            print(f"    [{i}] text={txt!r} disabled={disabled} visible={box is not None} box={box}")

        # Re-check checkbox
        checkbox2 = await page.query_selector('div[role="checkbox"], input[type="checkbox"]')
        if checkbox2:
            checked = await checkbox2.get_attribute("aria-checked")
            print(f"  Checkbox: aria-checked={checked!r}")

        # Find Confirm button
        confirm_btn = None
        for btn in buttons2:
            txt = (await btn.inner_text()).strip().lower()
            if "confirm" in txt:
                confirm_btn = btn
                break
        print(f"  Confirm button found: {confirm_btn is not None}")

        # ---- Click Confirm with verification
        print("\n[STEP 6] CLICKING CONFIRM + VERIFY")
        url_before = page.url
        if confirm_btn:
            await confirm_btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            await confirm_btn.click()
            print("  Click issued, waiting 5s...")
            await asyncio.sleep(5)

            url_after = page.url
            print(f"  URL before: {url_before}")
            print(f"  URL after:  {url_after}")
            print(f"  URL changed: {url_before != url_after}")

            # Dump new buttons/content
            buttons3 = await page.query_selector_all('div[role="button"], button')
            print(f"  Buttons after Confirm: {len(buttons3)}")
            for i, btn in enumerate(buttons3[:8]):
                txt = (await btn.inner_text()).strip()[:60]
                disabled = await btn.get_attribute("aria-disabled")
                print(f"    [{i}] text={txt!r} disabled={disabled}")

            # Check for OTP input
            otp_inputs = await page.query_selector_all('input[aria-label*="code" i], input[aria-label*="otp" i], input[aria-label*="verification" i]')
            print(f"  OTP inputs found: {len(otp_inputs)}")

            # Full visible text
            visible_text = await page.inner_text("body")
            print(f"\n  VISIBLE TEXT (first 600 chars):\n  {visible_text[:600]}")
        else:
            print("  Confirm button NOT found — cannot proceed")

        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
