#!/usr/bin/env python3
"""E2EE fix with proper timing: wait for key, encrypt, then fill card."""
import asyncio, json, os, sys, urllib.parse

os.environ["DISPLAY"] = ":99"
CARD = "4889501032758307"
CVV = "424"

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

    state = {"enc_card": None, "enc_cvv": None, "cert": None}
    save_response = None
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Capture key
        async def on_resp(resp):
            nonlocal save_response
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body
                    if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
                    d = json.loads(raw)
                    tc = d.get("data", {}).get("get_server_encryption_key", {}).get("trust_chain", [])
                    if tc:
                        state["cert"] = tc[0]
                        print(f"[KEY] Got cert ({len(tc[0])} chars)")
                if "save_credit_card" in body:
                    save_response = body
            except: pass
        page.on("response", on_resp)

        # Route: replace $e2ee
        async def fix_route(route):
            req = route.request
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if "$e2ee" in body and state["enc_card"]:
                    parsed = urllib.parse.parse_qs(body)
                    if "variables" in parsed:
                        v = json.loads(parsed["variables"][0])
                        cd = v.get("input", {}).get("card_data", {})
                        if cd.get("credit_card_number", {}).get("sensitive_string_value") == "$e2ee":
                            cd["credit_card_number"]["sensitive_string_value"] = state["enc_card"]
                            cd["csc"]["sensitive_string_value"] = state["enc_cvv"]
                            parsed["variables"] = [json.dumps(v)]
                            new_body = urllib.parse.urlencode(parsed, doseq=True)
                            print("[FIX] $e2ee replaced with encrypted data!")
                            await route.continue_(post_data=new_body)
                            return
            await route.continue_()
        await page.route("**/billing/graphql/**", fix_route)

        # Load billing
        print("[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(5)

        # Dismiss modal first
        for i in range(10):
            if state["cert"]: break
            await asyncio.sleep(1)
        
        if not state["cert"]:
            print("  ❌ No key after 10s!")
            return
        
        # Dismiss modal
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

        # Encrypt
        print("[2] Encrypting card...")
        result = await page.evaluate("""
            async (args) => {
                try {
                    const der = Uint8Array.from(atob(args.cert), c => c.charCodeAt(0));
                    const key = await crypto.subtle.importKey(
                        'spki', der, {name: 'RSA-OAEP', hash: 'SHA-256'}, false, ['encrypt']
                    );
                    const encCard = await crypto.subtle.encrypt(
                        {name: 'RSA-OAEP'}, key, new TextEncoder().encode(args.card)
                    );
                    const encCvv = await crypto.subtle.encrypt(
                        {name: 'RSA-OAEP'}, key, new TextEncoder().encode(args.cvv)
                    );
                    return {
                        card: btoa(String.fromCharCode(...new Uint8Array(encCard))),
                        cvv: btoa(String.fromCharCode(...new Uint8Array(encCvv))),
                    };
                } catch(e) { return {error: e.message}; }
            }
        """, {"cert": state["cert"], "card": CARD, "cvv": CVV})
        
        if result.get("error"):
            print(f"  ❌ {result['error']}")
            return
        
        state["enc_card"] = result["card"]
        state["enc_cvv"] = result["cvv"]
        print(f"  ✅ Encrypted!")
        print(f"  Card ({len(result['card'])} chars): {result['card'][:60]}...")
        print(f"  CVV ({len(result['cvv'])} chars): {result['cvv'][:60]}...")

        # Fill card
        print("[3] Filling card...")
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in CARD: await page.keyboard.type(ch, delay=50)
        el = await page.query_selector('input[name="expiration"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in "08/27": await page.keyboard.type(ch, delay=60)
        el = await page.query_selector('input[name="securityCode"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in CVV: await page.keyboard.type(ch, delay=60)
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
        print("[4] Submit...")
        save_response = None
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        if save_response:
            raw = save_response
            if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
            try:
                d = json.loads(raw)
                r = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
                cc = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("credit_card")
                print(f"  Status: {r.get('status')} | error_code: {r.get('error_code')}")
                if cc:
                    print(f"  ✅ CARD SAVED! {json.dumps(cc)[:200]}")
                else:
                    print(f"  ❌ {r.get('message')}")
            except: pass
        else:
            body = await page.evaluate("document.body?.innerText || ''")
            if "Couldn't save" in body: print("  ❌ Rejected")
            else: print(f"  ? {body[:200]}")

        await page.screenshot(path="data/screenshots/e2ee_fix3.png")
        print("\n[DONE]")

asyncio.run(main())
