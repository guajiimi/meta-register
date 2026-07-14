#!/usr/bin/env python3
"""Test without VPN - direct VPS IP."""
import asyncio, json, os, sys

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address

async def main():
    from camoufox.async_api import AsyncCamoufox

    with open("data/output/accounts_20260714_114223_full.json") as f:
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

    card = generate_card("visa")
    addr = generate_us_address()
    card_name = f"{account['first_name']} {account['last_name']}"

    print(f"Card: {card['formatted']} | No VPN (direct VPS)")

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Navigate
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=10000)
        except: pass
        await asyncio.sleep(5)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"Page text: {body[:500]}")
        print(f"URL: {page.url}")

        await page.screenshot(path="data/screenshots/no_vpn_billing.png")

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

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\nAfter dismiss: {body[:500]}")

        # Check all buttons
        btns = await page.evaluate("""
            Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => b.innerText.trim())
        """)
        print(f"\nButtons: {btns}")

        print("\n[DONE]")

asyncio.run(main())
