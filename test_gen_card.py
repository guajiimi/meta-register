#!/usr/bin/env python3
"""Test generated card — intercept full request/response."""
import asyncio, json, os, sys
from datetime import datetime

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

    print(f"Card: {card['formatted']} | Exp: {card['expiry']} | CVV: {card['cvv']}")

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Intercept billing graphql
        requests_log = []
        async def on_req(req):
            if "graphql" in req.url and "billing" in req.url:
                try:
                    post = req.post_data
                    requests_log.append({"url": req.url[:150], "post": post[:2000] if post else ""})
                except: pass
        page.on("request", on_req)

        responses_log = []
        async def on_resp(resp):
            if "graphql" in resp.url and "billing" in resp.url:
                try:
                    body = await resp.text()
                    responses_log.append({"url": resp.url[:150], "status": resp.status, "body": body[:2000]})
                except: pass
        page.on("response", on_resp)

        # Navigate
        print("[1] Billing...")
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

        # Add payment method
        print("[2] Add payment method...")
        try:
            btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
            await btn.click()
            await asyncio.sleep(4)
        except Exception as e:
            print(f"  Error: {e}")

        # Fill form
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

        # ZIP
        await page.evaluate(f"""
            () => {{
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
            }}
        """)
        await asyncio.sleep(1)

        # Submit
        print("[4] Submit...")
        requests_log.clear()
        responses_log.clear()
        
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click(force=True)

        for i in range(15):
            await asyncio.sleep(1)
            if responses_log:
                for r in responses_log:
                    print(f"\n  === RESPONSE [{r['status']}] ===")
                    # Parse JSON
                    try:
                        body = r["body"]
                        if body.startswith("for (;;);"):
                            body = body[len("for (;;);"):]
                        d = json.loads(body)
                        print(json.dumps(d, indent=2)[:1500])
                    except:
                        print(f"  Raw: {r['body'][:500]}")
                responses_log.clear()
            if requests_log:
                for r in requests_log:
                    print(f"\n  === REQUEST ===")
                    try:
                        post = r["post"]
                        if post:
                            # Try parse as form data or JSON
                            try:
                                d = json.loads(post)
                                print(json.dumps(d, indent=2)[:1500])
                            except:
                                print(f"  Form: {post[:500]}")
                    except: pass
                requests_log.clear()

            body = await page.evaluate("document.body?.innerText || ''")
            if "Couldn't save" in body or "Incorrect" in body:
                print(f"\n  ❌ REJECTED")
                break
            elif "Temporarily Blocked" in body:
                print(f"\n  ❌ RATE LIMIT")
                break

        await page.screenshot(path="data/screenshots/gen_card_result.png")
        print(f"\n[DONE]")

asyncio.run(main())
