#!/usr/bin/env python3
"""Capture and decode platform_trust_token."""
import asyncio, json, os, sys, base64, urllib.parse

os.environ["DISPLAY"] = ":99"

async def main():
    from camoufox.async_api import AsyncCamoufox
    
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    domain_map = {
        "datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com",
        "locale": ".auth.meta.com", "llm_sess": ".meta.ai",
        "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com",
    }
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False}
               for n, v in acc["cookies"].items()]

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        captured_vars = None
        async def on_req(req):
            nonlocal captured_vars
            if "billing/graphql" in req.url and req.method == "POST":
                post = req.post_data
                if post and "save_credit_card" in post:
                    parsed = urllib.parse.parse_qs(post)
                    if "variables" in parsed:
                        captured_vars = json.loads(parsed["variables"][0])
        page.on("request", on_req)

        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        for _ in range(5):
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

        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Fill card
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type("David Davis", delay=30)
        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in "4889501032758307": await page.keyboard.type(ch, delay=50)
        el = await page.query_selector('input[name="expiration"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in "08/27": await page.keyboard.type(ch, delay=60)
        el = await page.query_selector('input[name="securityCode"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in "424": await page.keyboard.type(ch, delay=60)
        await page.evaluate("""() => {
            for (const inp of document.querySelectorAll('input')) {
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {
                    if (!inp.value) { inp.value = '90001'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
                }
            }
        }""")
        await asyncio.sleep(1)

        # Submit
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(8)

        if captured_vars:
            print("=== VARIABLES ===")
            print(json.dumps(captured_vars, indent=2))
            
            # Decode platform_trust_token
            ptt = captured_vars.get("input", {}).get("platform_trust_token", "")
            if ptt:
                print(f"\n=== PLATFORM TRUST TOKEN ===")
                print(f"Length: {len(ptt)}")
                # Try base64 decode (it's a JWT-like token)
                try:
                    # Add padding
                    padded = ptt + '=' * (4 - len(ptt) % 4)
                    decoded = base64.b64decode(padded)
                    print(f"Decoded (bytes): {decoded[:200]}")
                    # Try JSON
                    try:
                        j = json.loads(decoded)
                        print(f"JSON: {json.dumps(j, indent=2)[:1000]}")
                    except:
                        # Try utf-8
                        text = decoded.decode('utf-8', errors='replace')
                        print(f"Text: {text[:500]}")
                except Exception as e:
                    print(f"Decode error: {e}")
                    # Try url-safe base64
                    try:
                        padded = ptt + '=' * (4 - len(ptt) % 4)
                        decoded = base64.urlsafe_b64decode(padded)
                        print(f"URL-safe decoded: {decoded[:200]}")
                    except Exception as e2:
                        print(f"URL-safe error: {e2}")
        else:
            print("No billing request captured")

asyncio.run(main())
