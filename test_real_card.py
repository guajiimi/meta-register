#!/usr/bin/env python3
"""Test real card — fix: proper billing URL with project_id/team_id + address form."""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

os.environ["DISPLAY"] = ":99"
SCREENSHOTS = Path("/root/meta-register/data/screenshots")
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_us_address

async def main():
    from camoufox.async_api import AsyncCamoufox

    with open("/root/meta-register/data/output/accounts_20260714_114223_full.json") as f:
        data = json.load(f)
    account = data[0]
    cookie_dict = account["cookies"]

    cookies = []
    domain_map = {
        "datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com",
        "locale": ".auth.meta.com", "ig_did": ".instagram.com", "llm_sess": ".meta.ai",
        "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com",
        "fr": ".facebook.com", "sb": ".facebook.com",
    }
    for name, value in cookie_dict.items():
        cookies.append({"name": name, "value": value, "domain": domain_map.get(name, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False})

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    card_name = f"{account['first_name']} {account['last_name']}"
    addr = generate_us_address()
    REAL_CARD = "4889501032758307"
    REAL_EXP = "08/27"
    REAL_CVV = "424"

    print(f"Card: {REAL_CARD[:6]}****{REAL_CARD[-4:]} | IP: WireGuard US-SEA")
    print(f"Name: {card_name}")
    print(f"Address: {addr['street']}, {addr['city']}, {addr['state']} {addr['zip']}")

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        api_calls = []
        async def on_resp(resp):
            u = resp.url
            if ("api" in u or "graphql" in u or "billing" in u) and "pixel" not in u and "google" not in u:
                try:
                    body = await resp.text()
                    api_calls.append({"url": u[:200], "status": resp.status, "body": body[:1500]})
                except:
                    api_calls.append({"url": u[:200], "status": resp.status})
        page.on("response", on_resp)

        # [1] Navigate to dev.meta.ai first to get project context
        print("[1] Navigate to dev.meta.ai...")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss welcome modal if present
        for _ in range(3):
            body = await page.evaluate("document.body?.innerText || ''")
            if "Welcome" not in body: break
            els = await page.evaluate("""
                Array.from(document.querySelectorAll('*')).filter(el => {
                    return el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                           el.getBoundingClientRect().height > 20 && el.getBoundingClientRect().width > 40;
                }).map(el => ({ r: el.getBoundingClientRect() }))
            """)
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x'] + e['width']/2, e['y'] + e['height']/2)
                await asyncio.sleep(2)

        # [2] Navigate to billing — let it auto-resolve project/team
        print("[2] Billing page...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except: pass
        await asyncio.sleep(3)

        final_url = page.url
        print(f"  Final URL: {final_url}")

        # Dismiss any modal again
        for _ in range(3):
            body = await page.evaluate("document.body?.innerText || ''")
            if "Welcome" not in body: break
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

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  Page content: {body[:300]}")

        # [3] Click Add payment method
        print("[3] Add payment method...")
        try:
            btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
            await btn.click()
            await asyncio.sleep(3)
        except Exception as e:
            print(f"  ⚠ No 'Add payment method' button: {e}")

        # [4] Fill card details
        print("[4] Filling card...")
        fname = await page.query_selector('input[name="firstName"]')
        if fname:
            await fname.click(); await fname.fill(""); await fname.type(card_name, delay=30)
            print("  ✓ Name")

        cardnum = await page.query_selector('input[name="cardNumber"]')
        if cardnum:
            await cardnum.click(); await cardnum.fill("")
            for ch in REAL_CARD:
                await page.keyboard.type(ch, delay=40)
            print("  ✓ Card number")

        expiry = await page.query_selector('input[name="expiration"]')
        if expiry:
            await expiry.click(); await asyncio.sleep(0.2)
            for ch in REAL_EXP:
                await page.keyboard.type(ch, delay=60)
            print("  ✓ Expiry")

        cvv = await page.query_selector('input[name="securityCode"]')
        if cvv:
            await cvv.click(); await asyncio.sleep(0.2)
            for ch in REAL_CVV:
                await page.keyboard.type(ch, delay=60)
            print("  ✓ CVV")

        # [5] Fill address if present (after card)
        print("[5] Address form...")
        await asyncio.sleep(2)
        
        # Check for address fields
        addr_fields = {
            "address": addr["street"],
            "city": addr["city"],
            "state": addr["state"],
            "zip": addr["zip"],
            "postalCode": addr["zip"],
        }
        for field_name, value in addr_fields.items():
            el = await page.query_selector(f'input[name="{field_name}"]')
            if el:
                v = await el.input_value()
                if not v:
                    await el.click()
                    await el.fill(value)
                    print(f"  ✓ {field_name}: {value}")

        # Check for state dropdown
        state_select = await page.query_selector('select[name="state"]')
        if state_select:
            await state_select.select_option(label=addr["state"])
            print(f"  ✓ State dropdown: {addr['state']}")

        # Check for country dropdown
        country_select = await page.query_selector('select[name="country"]')
        if country_select:
            try:
                await country_select.select_option(value="US")
                print("  ✓ Country: US")
            except:
                await country_select.select_option(label="United States")
                print("  ✓ Country: United States")

        await asyncio.sleep(1)

        # Take screenshot before submit
        await page.screenshot(path=str(SCREENSHOTS / f"realcard_filled_{ts}.png"))

        # [6] Submit
        print("\n[6] Submit...")
        api_calls.clear()
        next_btn = await page.query_selector('button:has-text("Next")')
        if not next_btn:
            next_btn = await page.query_selector('button:has-text("Save")')
        if not next_btn:
            next_btn = await page.query_selector('button:has-text("Continue")')
        if not next_btn:
            next_btn = await page.query_selector('button[type="submit"]')
        
        if next_btn:
            await next_btn.click(force=True)
            print(f"  Clicked submit button")
            for i in range(20):
                await asyncio.sleep(1)
                if api_calls:
                    for c in api_calls:
                        print(f"  API [{c['status']}]: {c['url'][:100]}")
                        if 'body' in c:
                            print(f"    Body: {c['body'][:300]}")
                    api_calls.clear()
                body = await page.evaluate("document.body?.innerText || ''")
                if "Couldn't save" in body:
                    print("  ❌ REJECTED: Couldn't save card")
                    # Print full error
                    print(f"  Full text: {body[:500]}")
                    break
                elif "Incorrect" in body:
                    print("  ❌ REJECTED: Incorrect card details")
                    break
                elif "Temporarily Blocked" in body:
                    print("  ❌ RATE LIMITED")
                    break
                elif "Card details" not in body and "Add payment" not in body:
                    # Check if we moved past the card form
                    if i > 5:
                        print("  ✅ Possibly accepted!")
                        break

        await page.screenshot(path=str(SCREENSHOTS / f"realcard_result_{ts}.png"))
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[7] Result:\n{body[:1500]}")

        # [8] Check if we need to fill more (address after card)
        if "address" in body.lower() or "street" in body.lower() or "city" in body.lower():
            print("\n[8] Filling remaining address fields...")
            for field_name, value in addr_fields.items():
                el = await page.query_selector(f'input[name="{field_name}"]')
                if el:
                    v = await el.input_value()
                    if not v:
                        await el.click()
                        await el.fill(value)
                        print(f"  ✓ {field_name}: {value}")
            
            # Try submit again
            for text in ["Next", "Save", "Continue", "Submit"]:
                btn = await page.query_selector(f'button:has-text("{text}")')
                if btn:
                    await btn.click(force=True)
                    print(f"  Clicked: {text}")
                    await asyncio.sleep(5)
                    break

            body = await page.evaluate("document.body?.innerText || ''")
            print(f"  After address: {body[:500]}")
            await page.screenshot(path=str(SCREENSHOTS / f"realcard_address_{ts}.png"))

        # [9] API keys
        form = await page.query_selector('input[name="cardNumber"]')
        if not form:
            print("\n[9] Creating API key...")
            await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except: pass
            await asyncio.sleep(3)
            for _ in range(3):
                body = await page.evaluate("document.body?.innerText || ''")
                if "Welcome" not in body: break
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

            create = await page.query_selector('button:has-text("Create API key")')
            if create:
                await create.click(force=True)
                await asyncio.sleep(3)
                name_input = await page.query_selector('input[type="text"]')
                if name_input:
                    await name_input.fill("default")
                    submit = await page.query_selector('button:has-text("Create")')
                    if submit:
                        api_calls.clear()
                        await submit.click(force=True)
                        await asyncio.sleep(5)
                        if api_calls:
                            for c in api_calls:
                                print(f"  API: {c['status']} {c['url'][:100]}")
                                if 'body' in c:
                                    print(f"    {c['body'][:500]}")

            body = await page.evaluate("document.body?.innerText || ''")
            print(f"\n[9] Result:\n{body[:2000]}")
            await page.screenshot(path=str(SCREENSHOTS / f"realcard_apikey_{ts}.png"))

        print("\n[DONE]")

asyncio.run(main())
