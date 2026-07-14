#!/usr/bin/env python3
"""Capture full GraphQL request body for billing save card."""
import asyncio, json, os, sys, urllib.parse

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

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Capture FULL request body
        billing_request = None
        async def on_req(req):
            nonlocal billing_request
            if "billing/graphql" in req.url and req.method == "POST":
                billing_request = {"url": req.url, "post": req.post_data, "headers": dict(req.headers)}
        page.on("request", on_req)

        billing_response = None
        async def on_resp(resp):
            nonlocal billing_response
            if "billing/graphql" in resp.url and resp.status == 200:
                try:
                    body = await resp.text()
                    billing_response = body
                except: pass
        page.on("response", on_resp)

        # Navigate
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=10000)
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

        btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Fill form
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
        await page.evaluate("""() => {
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {
                const label = inp.closest('label')?.innerText || '';
                const parent = inp.parentElement?.innerText || '';
                if ((label + parent).toLowerCase().includes('zip') || (label + parent).toLowerCase().includes('postal')) {
                    if (!inp.value) {
                        inp.value = '""" + addr["zip"] + """';
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }
            }
        }""")
        await asyncio.sleep(1)

        # Submit
        billing_request = None
        billing_response = None
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click(force=True)

        await asyncio.sleep(8)

        # Print FULL request
        if billing_request:
            print("=== FULL REQUEST ===")
            print(f"URL: {billing_request['url']}")
            post = billing_request['post']
            if post:
                # Parse form data
                parsed = urllib.parse.parse_qs(post)
                for k, v in parsed.items():
                    val = v[0] if len(v) == 1 else v
                    if len(str(val)) > 200:
                        print(f"  {k}: {str(val)[:200]}...")
                    else:
                        print(f"  {k}: {val}")
                
                # Check for variables/doc
                if 'variables' in parsed:
                    try:
                        vars_json = json.loads(parsed['variables'][0])
                        print("\n=== VARIABLES ===")
                        print(json.dumps(vars_json, indent=2))
                    except: pass
                if 'doc_id' in parsed:
                    print(f"\n  doc_id: {parsed['doc_id']}")

        # Print response
        if billing_response:
            print("\n=== RESPONSE ===")
            try:
                body = billing_response
                if body.startswith("for (;;);"):
                    body = body[len("for (;;);"):]
                d = json.loads(body)
                print(json.dumps(d, indent=2))
            except:
                print(billing_response[:500])

        await page.screenshot(path="data/screenshots/captured_request.png")
        print("\n[DONE]")

asyncio.run(main())
