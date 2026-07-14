"""Test Meta billing with CloakBrowser."""
import asyncio, json, os, sys, urllib.parse
os.environ["DISPLAY"] = ":99"

CARD = "4889501032758307"

async def main():
    import cloakbrowser
    
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    print(f"Account: {acc['email']}")

    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    # launch_async returns a Browser object
    browser = await cloakbrowser.launch_async(headless=False, humanize=True)
    ctx = await browser.new_context()
    await ctx.add_cookies(cookies)
    page = await ctx.new_page()
    page.set_default_timeout(60000)

    req_data = {}

    async def on_req(req):
        if "billing/graphql" in req.url and req.method == "POST":
            body = req.post_data or ""
            if "card_data" in body:
                parsed = urllib.parse.parse_qs(body)
                if "variables" in parsed:
                    v = json.loads(parsed["variables"][0])
                    cd = v.get("input", {}).get("card_data", {})
                    cnum = cd.get("credit_card_number", {}).get("sensitive_string_value", "")
                    ptt = v.get("input", {}).get("platform_trust_token", "")
                    req_data["cnum"] = cnum
                    req_data["ptt"] = ptt
    page.on("request", on_req)

    resp_data = {}
    async def on_resp(resp):
        if "billing/graphql" in resp.url:
            try:
                body = await resp.text()
                if "save_credit_card" in body:
                    resp_data["body"] = body
            except: pass
    page.on("response", on_resp)

    # Load billing
    print("\n[1] Billing...")
    await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
    try: await page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    await asyncio.sleep(3)

    body = await page.evaluate("document.body?.innerText || ''")
    if "not available" in body.lower():
        print("  ❌ Geo-blocked!")
        await browser.close()
        return

    print(f"  URL: {page.url[:80]}")
    print(f"  Body: {body[:150]}")

    # Dismiss
    for _ in range(5):
        els = await page.evaluate("""Array.from(document.querySelectorAll('*')).filter(el => el.innerText?.trim() === 'Continue' && el.offsetParent !== null && el.getBoundingClientRect().height > 20).map(el => ({r: el.getBoundingClientRect()}))""")
        if els:
            e = els[0]['r']
            await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
            await asyncio.sleep(2)
        else: break

    # Check trust token
    trust = await page.evaluate("""
        async () => ({
            hasTrustToken: typeof document.hasTrustToken === 'function',
            hasPrivateStateToken: typeof document.hasPrivateStateToken === 'function',
        })
    """)
    print(f"  Trust: {json.dumps(trust)}")

    # Add payment
    print("\n[2] Add payment...")
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('div[role="button"], button');
        for (const b of btns) {
            if (b.innerText.includes('Add payment method')) { b.click(); return true; }
        }
        return false;
    }""")
    await asyncio.sleep(5)

    # Fill card
    el = await page.query_selector('input[name="firstName"]')
    if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
    el = await page.query_selector('input[name="cardNumber"]')
    if el: await el.click(); await el.fill(""); [await page.keyboard.type(ch, delay=50) for ch in CARD]
    el = await page.query_selector('input[name="expiration"]')
    if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in "08/27"]
    el = await page.query_selector('input[name="securityCode"]')
    if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in "424"]
    await page.evaluate("""() => {
        for (const inp of document.querySelectorAll('input')) {
            const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
            if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal'))
                if (!inp.value) { inp.value = '90001'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
        }
    }""")
    await asyncio.sleep(1)

    # Submit
    print("\n[3] Submit...")
    resp_data.clear()
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('div[role="button"], button');
        for (const b of btns) { if (b.innerText.trim() === 'Next') { b.click(); return true; } }
        return false;
    }""")
    await asyncio.sleep(10)

    # Results
    cnum = req_data.get("cnum", "")
    ptt = req_data.get("ptt", "")
    print(f"\n  card_number: {cnum[:60]}")
    print(f"  trust_token ({len(ptt)} chars): {ptt[:60]}")
    
    if cnum == "$e2ee":
        print(f"  ❌ $e2ee NOT encrypted")
    elif cnum.startswith("fp:"):
        print(f"  ✅ JWE encrypted!")
    
    if ptt:
        import base64
        try:
            padded = ptt + '=' * (4 - len(ptt) % 4)
            raw = base64.b64decode(padded)
            text = raw.decode('utf-8', errors='replace')
            start = text.find('{')
            if start >= 0:
                depth = 0
                for i, c in enumerate(text[start:]):
                    if c == '{': depth += 1
                    elif c == '}': depth -= 1
                    if depth == 0:
                        j = json.loads(text[start:start+i+1])
                        sigs = j.get("signatures", [])
                        print(f"  trust_token signatures: {len(sigs)}")
                        if sigs: print(f"  ✅ HAS SIGNATURES!")
                        else: print(f"  ❌ Empty signatures")
                        break
        except: pass

    if resp_data.get("body"):
        raw = resp_data["body"]
        if raw.startswith("for (;;);"): raw = raw[10:]
        d = json.loads(raw)
        r = d["data"]["xfb_billing_save_credit_card"]["client_result"]
        cc = d["data"]["xfb_billing_save_credit_card"].get("credit_card")
        print(f"\n  Status: {r['status']} | err: {r.get('error_code')}")
        if cc: print(f"  ✅ CARD SAVED!")
        else: print(f"  ❌ {r.get('message')}")

    await page.screenshot(path="data/screenshots/cloak_result.png")
    print("\n[DONE]")
    await browser.close()

asyncio.run(main())
