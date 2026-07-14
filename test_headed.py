#!/usr/bin/env python3
"""Test with headed Chromium + Xvfb — better fingerprint."""
import asyncio, json, os, sys, urllib.parse
from datetime import datetime

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address

async def main():
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Card: {card['formatted']} | Exp: {card['expiry']} | CVV: {card['cvv']}")

    async with async_playwright() as p:
        # HEADED mode with full Chrome (not headless shell)
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        )
        
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        await context.add_cookies(cookies)

        billing_resp = None
        async def on_resp(resp):
            nonlocal billing_resp
            if "billing/graphql" in resp.url:
                try:
                    body = await resp.text()
                    billing_resp = {"status": resp.status, "body": body}
                except: pass
        page.on("response", on_resp)

        print("[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        if "not available" in body.lower():
            print("  ❌ Geo-blocked"); await browser.close(); return

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

        print("[2] Add payment method...")
        btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Check trust token with proper origin
        trust = await page.evaluate("""
            async () => {
                const r = {};
                r.hasTrustToken = typeof document.hasTrustToken === 'function';
                r.hasPrivateStateToken = typeof document.hasPrivateStateToken === 'function';
                r.hasCrypto = typeof crypto?.subtle !== 'undefined';
                // Try to get a trust token
                try {
                    if (r.hasTrustToken) {
                        r.hasToken = await document.hasTrustToken('https://meta.ai');
                    }
                } catch(e) { r.error = e.message; }
                return r;
            }
        """)
        print(f"  Trust: {json.dumps(trust)}")

        # Fill
        print("[3] Fill...")
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(card_name, delay=30)

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

        # Submit
        print("[4] Submit...")
        billing_resp = None
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click(force=True)

        await asyncio.sleep(8)

        if billing_resp:
            body = billing_resp['body']
            if body.startswith("for (;;);"): body = body[len("for (;;);"):]
            try:
                d = json.loads(body)
                result = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
                status = result.get('status')
                err = result.get('error_code')
                cc = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("credit_card")
                print(f"  Status: {status} | error_code: {err}")
                if cc:
                    print(f"  ✅ CARD SAVED! {json.dumps(cc)}")
                else:
                    print(f"  ❌ {result.get('message')}")
            except:
                print(f"  Raw: {body[:300]}")

        await page.screenshot(path=f"data/screenshots/headed_{ts}.png")
        print(f"\n[DONE]")
        await browser.close()

asyncio.run(main())
