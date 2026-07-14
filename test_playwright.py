#!/usr/bin/env python3
"""Test with Playwright + stealth (not Camoufox) — better Trust Token support."""
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
    print(f"IP: WireGuard US-SEA")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        )
        
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        await context.add_cookies(cookies)

        # Intercept billing graphql
        billing_req = None
        billing_resp = None
        
        async def on_req(req):
            nonlocal billing_req
            if "billing/graphql" in req.url and req.method == "POST":
                billing_req = {"url": req.url, "post": req.post_data, "headers": dict(req.headers)}
        page.on("request", on_req)

        async def on_resp(resp):
            nonlocal billing_resp
            if "billing/graphql" in resp.url:
                try:
                    body = await resp.text()
                    billing_resp = {"status": resp.status, "body": body}
                except: pass
        page.on("response", on_resp)

        # Navigate
        print("[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  Page: {body[:200]}")
        print(f"  URL: {page.url}")

        if "not available" in body.lower():
            print("  ❌ Geo-blocked!")
            await browser.close()
            return

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

        # Add payment method
        print("[2] Add payment method...")
        try:
            btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
            await btn.click()
            await asyncio.sleep(4)
        except Exception as e:
            print(f"  Error: {e}")
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"  Page: {body[:300]}")
            await browser.close()
            return

        # Check trust token
        trust_check = await page.evaluate("""
            async () => {
                const result = {};
                result.hasTrustToken = typeof document.hasTrustToken === 'function';
                result.hasPrivateStateToken = typeof document.hasPrivateStateToken === 'function';
                if (result.hasTrustToken) {
                    try {
                        result.trustToken = await document.hasTrustToken('https://dev.meta.ai');
                    } catch(e) {
                        result.trustTokenError = e.message;
                    }
                }
                // Check crypto
                result.hasCrypto = typeof crypto !== 'undefined' && typeof crypto.subtle !== 'undefined';
                try {
                    const key = await crypto.subtle.generateKey({name: 'AES-GCM', length: 256}, true, ['encrypt']);
                    const iv = crypto.getRandomValues(new Uint8Array(12));
                    const enc = await crypto.subtle.encrypt({name: 'AES-GCM', iv}, key, new TextEncoder().encode('test'));
                    result.cryptoWorks = true;
                } catch(e) {
                    result.cryptoWorks = false;
                    result.cryptoError = e.message;
                }
                return result;
            }
        """)
        print(f"  Trust: {json.dumps(trust_check)}")

        # Fill card
        print("[3] Fill card...")
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

        # Submit
        print("[4] Submit...")
        billing_req = None
        billing_resp = None
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click(force=True)

        await asyncio.sleep(8)

        # Print request
        if billing_req:
            post = billing_req['post']
            if post:
                parsed = urllib.parse.parse_qs(post)
                if 'variables' in parsed:
                    try:
                        vars_json = json.loads(parsed['variables'][0])
                        print(f"\n  Variables:")
                        print(json.dumps(vars_json, indent=2)[:1000])
                    except: pass

        # Print response
        if billing_resp:
            body = billing_resp['body']
            if body.startswith("for (;;);"):
                body = body[len("for (;;);"):]
            try:
                d = json.loads(body)
                result = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
                print(f"\n  Result: {result.get('status')} | error_code: {result.get('error_code')}")
                print(f"  Message: {result.get('message')}")
                if result.get('status') == 'ERROR':
                    print(f"  ❌ REJECTED")
                elif result.get('credit_card'):
                    print(f"  ✅ CARD SAVED!")
            except:
                print(f"  Raw: {body[:300]}")

        await page.screenshot(path=f"data/screenshots/playwright_{ts}.png")
        print(f"\n[DONE]")
        await browser.close()

asyncio.run(main())
