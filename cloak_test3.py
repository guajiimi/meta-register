"""CloakBrowser: full card submission test."""
import asyncio, json, os, sys, urllib.parse
os.environ["DISPLAY"] = ":99"

async def main():
    import cloakbrowser
    
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]

    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    browser = await cloakbrowser.launch_async(headless=False, humanize=True)
    ctx = await browser.new_context()
    await ctx.add_cookies(cookies)
    page = await ctx.new_page()
    page.set_default_timeout(60000)

    all_graphql = []
    async def on_req(req):
        if "billing/graphql" in req.url and req.method == "POST":
            body = req.post_data or ""
            all_graphql.append(body[:500])
    page.on("request", on_req)

    save_resp = {"body": None}
    async def on_resp(resp):
        try:
            body = await resp.text()
            if "save_credit_card" in body:
                save_resp["body"] = body
        except: pass
    page.on("response", on_resp)

    print("[1] Billing...")
    await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
    try: await page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    await asyncio.sleep(3)

    body = await page.evaluate("document.body?.innerText || ''")
    print(f"  Body: {body[:150]}")

    if "not available" in body.lower():
        print("  ❌ Geo-blocked"); await browser.close(); return

    # Dismiss modal
    for _ in range(5):
        els = await page.evaluate("""Array.from(document.querySelectorAll('*')).filter(el => el.innerText?.trim() === 'Continue' && el.offsetParent !== null && el.getBoundingClientRect().height > 20).map(el => ({r: el.getBoundingClientRect()}))""")
        if els:
            e = els[0]['r']
            await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
            await asyncio.sleep(2)
        else: break

    # Click Add payment method
    print("\n[2] Add payment...")
    clicked = await page.evaluate("""() => {
        const btns = document.querySelectorAll('div[role="button"], button, [role="button"]');
        for (const b of btns) {
            if (b.innerText.includes('Add payment method')) {
                b.click();
                return b.innerText.trim();
            }
        }
        return 'NOT FOUND';
    }""")
    print(f"  Clicked: {clicked}")
    await asyncio.sleep(5)

    # Check if form appeared
    inputs = await page.evaluate("""
        Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).map(i => i.name)
    """)
    print(f"  Inputs: {inputs}")

    if "cardNumber" not in inputs:
        print("  ⚠ Card form not visible, trying again...")
        await page.screenshot(path="data/screenshots/cloak_noform.png")
        # Maybe the button needs a different click
        await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                if (el.innerText === 'Add payment method' && el.offsetParent !== null) {
                    el.click();
                    return el.tagName + '.' + el.className?.substring(0, 30);
                }
            }
        }""")
        await asyncio.sleep(5)
        inputs = await page.evaluate("""
            Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null).map(i => i.name)
        """)
        print(f"  Inputs after retry: {inputs}")

    # Fill card
    print("\n[3] Fill card...")
    el = await page.query_selector('input[name="firstName"]')
    if el:
        await el.click(); await el.fill("")
        await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
        print("  ✓ Name")
    
    el = await page.query_selector('input[name="cardNumber"]')
    if el:
        await el.click(); await el.fill("")
        for ch in "4889501032758307": await page.keyboard.type(ch, delay=50)
        print("  ✓ Card")
    
    el = await page.query_selector('input[name="expiration"]')
    if el:
        await el.click(); await asyncio.sleep(0.2)
        for ch in "08/27": await page.keyboard.type(ch, delay=60)
        print("  ✓ Expiry")
    
    el = await page.query_selector('input[name="securityCode"]')
    if el:
        await el.click(); await asyncio.sleep(0.2)
        for ch in "424": await page.keyboard.type(ch, delay=60)
        print("  ✓ CVV")

    await page.evaluate("""() => {
        for (const inp of document.querySelectorAll('input')) {
            const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
            if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal'))
                if (!inp.value) { inp.value = '90001'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
        }
    }""")
    print("  ✓ ZIP")
    await asyncio.sleep(1)

    # Submit
    print("\n[4] Submit...")
    all_graphql.clear()
    save_resp["body"] = None
    
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('div[role="button"], button');
        for (const b of btns) { if (b.innerText.trim() === 'Next') { b.click(); return true; } }
        return false;
    }""")
    await asyncio.sleep(10)

    # Check results
    print(f"\n  GraphQL requests: {len(all_graphql)}")
    for i, body in enumerate(all_graphql):
        has_e2ee = "$e2ee" in body
        has_card = "card_data" in body
        print(f"  [{i}] e2ee={has_e2ee} card={has_card}")
        if has_card:
            # Parse variables
            import urllib.parse
            parsed = urllib.parse.parse_qs(body)
            if "variables" in parsed:
                v = json.loads(parsed["variables"][0])
                cd = v.get("input", {}).get("card_data", {})
                cnum = cd.get("credit_card_number", {}).get("sensitive_string_value", "")
                ptt = v.get("input", {}).get("platform_trust_token", "")
                print(f"    card_value: {cnum[:80]}")
                print(f"    trust_token ({len(ptt)} chars)")
                
                if cnum == "$e2ee":
                    print(f"    ❌ $e2ee NOT encrypted")
                elif cnum.startswith("fp:"):
                    print(f"    ✅ JWE encrypted!")
                
                if ptt:
                    import base64
                    try:
                        padded = ptt + '=' * (4 - len(ptt) % 4)
                        raw = base64.b64decode(padded)
                        text = raw.decode('utf-8', errors='replace')
                        start = text.find('{')
                        if start >= 0:
                            depth = 0
                            for ci, c in enumerate(text[start:]):
                                if c == '{': depth += 1
                                elif c == '}': depth -= 1
                                if depth == 0:
                                    j = json.loads(text[start:start+ci+1])
                                    sigs = j.get("signatures", [])
                                    print(f"    signatures: {len(sigs)}")
                                    break
                    except: pass

    if save_resp["body"]:
        raw = save_resp["body"]
        if raw.startswith("for (;;);"): raw = raw[10:]
        d = json.loads(raw)
        r = d["data"]["xfb_billing_save_credit_card"]["client_result"]
        cc = d["data"]["xfb_billing_save_credit_card"].get("credit_card")
        print(f"\n  Status: {r['status']} | err: {r.get('error_code')}")
        if cc: print(f"  ✅ CARD SAVED!")
        else: print(f"  ❌ {r.get('message')}")

    body = await page.evaluate("document.body?.innerText || ''")
    if "Couldn't save" in body: print("  ❌ Rejected")
    elif "Temporarily Blocked" in body: print("  ❌ Rate limited")

    await page.screenshot(path="data/screenshots/cloak_final.png")
    print("\n[DONE]")
    await browser.close()

asyncio.run(main())
