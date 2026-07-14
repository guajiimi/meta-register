#!/usr/bin/env python3
"""Check if e2ee actually encrypts card data or leaves $e2ee placeholder."""
import asyncio, json, os, sys, urllib.parse

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

        # Intercept using route() to see raw request body
        billing_posts = []
        async def intercept_route(route):
            req = route.request
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if "variables" in body:
                    parsed = urllib.parse.parse_qs(body)
                    if "variables" in parsed:
                        v = parsed["variables"][0]
                        if "card_data" in v:
                            billing_posts.append(v)
            await route.continue_()
        
        await page.route("**/billing/graphql/**", intercept_route)

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
        billing_posts.clear()
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        for v in billing_posts:
            data = json.loads(v)
            card = data.get("input", {}).get("card_data", {})
            cnum = card.get("credit_card_number", {})
            csc = card.get("csc", {})
            
            print(f"=== INTERCEPTED CARD DATA ===")
            print(f"  card_number: {json.dumps(cnum)}")
            print(f"  csc: {json.dumps(csc)}")
            print(f"  bin: {card.get('bin')}")
            print(f"  last_4: {card.get('last_4')}")
            
            # Check if $e2ee was replaced
            cnum_val = cnum.get("sensitive_string_value", "")
            csc_val = csc.get("sensitive_string_value", "")
            
            if cnum_val == "$e2ee":
                print(f"\n  ❌ ENCRYPTION FAILED — still $e2ee placeholder!")
                print(f"  Card number was NEVER encrypted client-side!")
            elif cnum_val.startswith("$"):
                print(f"\n  ❌ ENCRYPTION FAILED — {cnum_val[:50]}")
            else:
                print(f"\n  ✅ Card encrypted: {cnum_val[:80]}...")
                print(f"  CSC encrypted: {csc_val[:80]}...")

asyncio.run(main())
