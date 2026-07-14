#!/usr/bin/env python3
"""Test card form with real BIN-generated card."""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

os.environ["DISPLAY"] = ":99"
SCREENSHOTS = Path("/root/meta-register/data/screenshots")
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address

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
    card = generate_card("visa")
    addr = generate_us_address()
    card_name = f"{account['first_name']} {account['last_name']}"
    print(f"Card: {card['formatted']} | BIN: {card['bin']} | Bank: {card['bank']} | Exp: {card['expiry']} | CVV: {card['cvv']}")
    print(f"Addr: {addr['street']}, {addr['city']}, {addr['state']} {addr['zip']}")

    async with AsyncCamoufox(headless=False) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        api_calls = []
        def on_resp(resp):
            u = resp.url
            if ("api" in u or "graphql" in u or "billing" in u) and "pixel" not in u and "google" not in u and "reddit" not in u:
                api_calls.append({"url": u[:200], "status": resp.status, "method": resp.request.method})
        page.on("response", on_resp)

        # Billing page
        print("\n[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)

        # Dismiss modal
        for _ in range(5):
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

        # Open card form
        print("[2] Card form...")
        btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=5000)
        await btn.click()
        await asyncio.sleep(3)

        # Fill form
        print("[3] Filling...")
        fname = await page.query_selector('input[name="firstName"]')
        if fname:
            await fname.click()
            await fname.fill("")
            await fname.type(card_name, delay=30)

        cardnum = await page.query_selector('input[name="cardNumber"]')
        if cardnum:
            await cardnum.click()
            await cardnum.fill("")
            for ch in card["number"]:
                await page.keyboard.type(ch, delay=40)

        expiry = await page.query_selector('input[name="expiration"]')
        if expiry:
            await expiry.click()
            await asyncio.sleep(0.3)
            for ch in card["expiry"]:
                await page.keyboard.type(ch, delay=60)

        cvv = await page.query_selector('input[name="securityCode"]')
        if cvv:
            await cvv.click()
            await asyncio.sleep(0.3)
            for ch in card["cvv"]:
                await page.keyboard.type(ch, delay=60)

        postal = await page.query_selector('input[name="postalCode"]')
        if postal:
            val = await postal.input_value()
            if not val:
                await postal.fill(addr["zip"])

        await asyncio.sleep(1)
        await page.screenshot(path=str(SCREENSHOTS / f"bin_filled_{ts}.png"))

        # Verify
        vals = await page.evaluate("""
            Array.from(document.querySelectorAll('input')).map(el => ({
                name: el.name, value: el.value, valid: el.validity?.valid
            }))
        """)
        for v in vals:
            print(f"  [{v['name']}] = '{v['value']}' {'✅' if v['valid'] else '❌'}")

        # Submit
        print("\n[4] Submit...")
        api_calls.clear()
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn:
            disabled = await next_btn.get_attribute("aria-disabled")
            print(f"  Disabled: {disabled}")
            if disabled != "true":
                await next_btn.click(force=True)
                for i in range(15):
                    await asyncio.sleep(1)
                    if api_calls:
                        for c in api_calls:
                            print(f"  API: {c['method']} {c['status']} {c['url'][:100]}")
                        api_calls.clear()
                    body = await page.evaluate("document.body?.innerText || ''")
                    if "Couldn't save" in body or "Incorrect" in body:
                        print("  ❌ REJECTED")
                        break
                    elif "Card details" not in body or "payment method" not in body.lower():
                        # Check if form is gone
                        form = await page.query_selector('input[name="cardNumber"]')
                        if not form:
                            print("  ✅ CARD SAVED!")
                            break

        await page.screenshot(path=str(SCREENSHOTS / f"bin_result_{ts}.png"))
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[5] Result:\n{body[:1000]}")

        # If saved, try create API key
        if "Couldn't save" not in body and "Incorrect" not in body:
            print("\n[6] Creating API key...")
            await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)
            
            # Dismiss modal
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
                    await asyncio.sleep(1)
                    submit = await page.query_selector('button:has-text("Create"), button:has-text("Generate")')
                    if submit:
                        api_calls.clear()
                        await submit.click(force=True)
                        await asyncio.sleep(5)
                        if api_calls:
                            for c in api_calls:
                                print(f"  API: {c['method']} {c['status']} {c['url'][:100]}")
            
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"\n[6] API key result:\n{body[:1500]}")
            await page.screenshot(path=str(SCREENSHOTS / f"bin_apikey_{ts}.png"))

        print("\n[DONE]")

asyncio.run(main())
