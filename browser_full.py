#!/usr/bin/env python3
"""Full browser flow: register → onboarding → billing → API key.
All in Camoufox browser, no API shortcuts."""
import asyncio, json, os, sys, random, string
from pathlib import Path
from datetime import datetime

os.environ["DISPLAY"] = ":99"
SCREENSHOTS = Path("/root/meta-register/data/screenshots")
OUTPUT = Path("/root/meta-register/data/output")
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address

# Email generator
def gen_email():
    base = "dewixzpajak01"
    dots = list(base)
    # Random dot placement
    n_dots = random.randint(2, 4)
    positions = sorted(random.sample(range(1, len(dots)), n_dots))
    for i, pos in enumerate(positions):
        dots.insert(pos + i, '.')
    return ''.join(dots) + '@gmail.com'

async def main():
    from camoufox.async_api import AsyncCamoufox

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    email = gen_email()
    first_name = random.choice(["David", "James", "Michael", "Robert", "John"])
    last_name = random.choice(["Smith", "Johnson", "Williams", "Brown", "Davis"])
    password = "MetaReg2026!"
    card = generate_card("visa")
    addr = generate_us_address()

    print(f"Email: {email}")
    print(f"Name: {first_name} {last_name}")
    print(f"Card: {card['formatted']}")

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(60000)

        def snap(name):
            path = SCREENSHOTS / f"full_{name}_{ts}.png"
            return page.screenshot(path=str(path))

        # ===== STEP 1: REGISTER =====
        print("\n[1] Register...")
        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Click "Use mobile number or email"
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Use mobile number or email")', timeout=30000)
        await btn.click()
        await asyncio.sleep(2)

        # Enter email
        email_input = await page.wait_for_selector('input[type="text"]', timeout=5000)
        await email_input.fill(email)
        await asyncio.sleep(0.5)

        # Click Next
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click()
        await asyncio.sleep(3)

        # Enter password
        pw_input = await page.wait_for_selector('input[type="password"]', timeout=10000)
        await pw_input.fill(password)
        await asyncio.sleep(0.5)

        # Click Continue
        cont = await page.query_selector('button:has-text("Continue")')
        if cont: await cont.click()
        await asyncio.sleep(3)

        # Fill birthday (if present)
        body = await page.evaluate("document.body?.innerText || ''")
        if "birthday" in body.lower() or "birth" in body.lower():
            print("  Filling birthday...")
            # Month
            month_select = await page.query_selector('select[title="Month"]')
            if month_select: await month_select.select_option(value="3")
            # Day
            day_select = await page.query_selector('select[title="Day"]')
            if day_select: await day_select.select_option(value="15")
            # Year
            year_select = await page.query_selector('select[title="Year"]')
            if year_select: await year_select.select_option(value="1995")

            cont = await page.query_selector('button:has-text("Continue")')
            if cont: await cont.click()
            await asyncio.sleep(3)

        # OTP verification
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  Status: {body[:200]}")

        if "verification" in body.lower() or "code" in body.lower() or "confirm" in body.lower():
            print("  ⏳ OTP required — waiting for email...")
            # TODO: IMAP OTP reading
            # For now, screenshot and wait
            await snap("otp_needed")
            print("  ❌ OTP flow needs IMAP integration. Screenshot saved.")
            print(f"\n  Email: {email}")
            print(f"  Password: {password}")
            print(f"\n[DONE - needs OTP]")

            # Wait for user to provide OTP or auto-read
            await asyncio.sleep(5)
            await snap("otp_page")
            return

        # If already past OTP (auto-login from existing session)
        await snap("post_register")
        print("  Register done!")

        # ===== STEP 2: ONBOARDING =====
        print("\n[2] Onboarding...")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss welcome
        for _ in range(5):
            body = await page.evaluate("document.body?.innerText || ''")
            if "Welcome" not in body and "Continue" not in body[:50]: break
            els = await page.evaluate("""
                Array.from(document.querySelectorAll('*')).filter(el => {
                    return el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                           el.getBoundingClientRect().height > 20;
                }).map(el => ({ r: el.getBoundingClientRect() }))
            """)
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x'] + e['width']/2, e['y'] + e['height']/2)
                await asyncio.sleep(2)
            else: break

        await snap("onboarding_done")

        # ===== STEP 3: BILLING =====
        print("\n[3] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        final_url = page.url
        print(f"  URL: {final_url}")

        # Dismiss modal
        for _ in range(3):
            els = await page.evaluate("""
                Array.from(document.querySelectorAll('*')).filter(el => {
                    return el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                           el.getBoundingClientRect().height > 20;
                }).map(el => ({ r: el.getBoundingClientRect() }))
            """)
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x'] + e['width']/2, e['y'] + e['height']/2)
                await asyncio.sleep(2)
            else: break

        # Add payment
        try:
            add_btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
            await add_btn.click()
            await asyncio.sleep(4)
        except:
            print("  No add payment button")

        # Fill card
        print("  Filling card...")
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{first_name} {last_name}", delay=30)

        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in card["number"]: await page.keyboard.type(ch, delay=40)

        el = await page.query_selector('input[name="expiration"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in card["expiry"]: await page.keyboard.type(ch, delay=60)

        el = await page.query_selector('input[name="securityCode"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in card["cvv"]: await page.keyboard.type(ch, delay=60)

        # ZIP
        await page.evaluate(f"""() => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                const label = inp.closest('label')?.innerText || '';
                const parent = inp.parentElement?.innerText || '';
                if ((label + parent).toLowerCase().includes('zip') || (label + parent).toLowerCase().includes('postal')) {{
                    if (!inp.value) {{
                        inp.value = '{addr["zip"]}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            }}
        }}""")
        await asyncio.sleep(1)
        await snap("card_filled")

        # Submit
        print("  Submitting card...")
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(8)

        body = await page.evaluate("document.body?.innerText || ''")
        await snap("card_result")

        if "Couldn't save" in body:
            print("  ❌ Card rejected")
            print(f"  {body[:300]}")
            # Extract cookies and save for manual billing
            all_cookies = await context.cookies()
            cookie_dict = {}
            for c in all_cookies:
                if c['name'] in ['datr', 'ps_l', 'ps_n', 'llm_sess', 'locale', 'fs', 'wd', 'fr', 'sb']:
                    cookie_dict[c['name']] = c['value']
            
            output = {
                "email": email, "password": password,
                "first_name": first_name, "last_name": last_name,
                "cookies": cookie_dict, "final_url": page.url,
                "billing_url": final_url,
                "status": "needs_manual_billing",
                "timestamp": datetime.now().isoformat(),
            }
            out_file = OUTPUT / f"browser_{ts}.json"
            with open(out_file, "w") as f:
                json.dump(output, f, indent=2)
            print(f"\n  Saved: {out_file}")
            print(f"  Billing URL: {final_url}")
            print(f"  Add card manually, then run create_apikey.py")
            print(f"\n[DONE - needs manual billing]")
            return

        if "Temporarily Blocked" in body:
            print("  ❌ Rate limited")
            return

        print("  ✅ Card accepted!")

        # ===== STEP 4: API KEY =====
        print("\n[4] Creating API key...")
        await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss modal
        for _ in range(3):
            els = await page.evaluate("""
                Array.from(document.querySelectorAll('*')).filter(el => {
                    return el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                           el.getBoundingClientRect().height > 20;
                }).map(el => ({ r: el.getBoundingClientRect() }))
            """)
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x'] + e['width']/2, e['y'] + e['height']/2)
                await asyncio.sleep(2)
            else: break

        create_btn = await page.query_selector('button:has-text("Create API key")')
        if create_btn:
            await create_btn.click(force=True)
            await asyncio.sleep(3)
            name_input = await page.query_selector('input[type="text"]')
            if name_input:
                await name_input.fill("default")
                submit = await page.query_selector('button:has-text("Create")')
                if submit:
                    await submit.click(force=True)
                    await asyncio.sleep(5)

        body = await page.evaluate("document.body?.innerText || ''")
        await snap("apikey_result")

        # Extract API key
        api_key = None
        key_els = await page.evaluate("""
            Array.from(document.querySelectorAll('[class*="key"], [data-testid*="key"], code, pre, span')).filter(el => {
                const t = el.innerText || '';
                return t.startsWith('Bearer ') || t.startsWith('eyJ') || (t.length > 30 && /^[A-Za-z0-9_-]+$/.test(t));
            }).map(el => el.innerText.trim())
        """)
        if key_els:
            api_key = key_els[0]

        # Extract cookies
        all_cookies = await context.cookies()
        cookie_dict = {}
        for c in all_cookies:
            if c['name'] in ['datr', 'ps_l', 'ps_n', 'llm_sess', 'locale', 'fs', 'wd', 'fr', 'sb']:
                cookie_dict[c['name']] = c['value']

        output = {
            "email": email, "password": password,
            "first_name": first_name, "last_name": last_name,
            "cookies": cookie_dict,
            "api_key": api_key,
            "final_url": page.url,
            "status": "complete" if api_key else "no_api_key",
            "timestamp": datetime.now().isoformat(),
        }
        out_file = OUTPUT / f"browser_full_{ts}.json"
        with open(out_file, "w") as f:
            json.dump(output, f, indent=2)

        print(f"\n  API Key: {api_key or 'NOT FOUND'}")
        print(f"  Saved: {out_file}")
        print(f"\n{'🎉 FULL SUCCESS!' if api_key else '⚠️ No API key found'}")

asyncio.run(main())
