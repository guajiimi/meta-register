#!/usr/bin/env python3
"""
Full e2ee fix:
1. Capture get_server_encryption_key cert
2. Encrypt card+cvv with RSA-OAEP via WebCrypto
3. Replace $e2ee in intercepted request body
4. Forward modified request
"""
import asyncio, json, os, sys, urllib.parse, base64, re

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

    # Store encrypted values
    state = {"enc_card": None, "enc_cvv": None, "cert": None, "key_captured": False}
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Capture encryption key from response
        async def capture_key(resp):
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body
                    if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
                    d = json.loads(raw)
                    key_data = d.get("data", {}).get("get_server_encryption_key", {})
                    trust_chain = key_data.get("trust_chain", [])
                    if trust_chain:
                        state["cert"] = trust_chain[0]  # First cert = leaf cert with public key
                        state["key_captured"] = True
                        print(f"[KEY] Captured cert ({len(trust_chain[0])} chars)")
            except: pass
        page.on("response", capture_key)

        # Route handler: intercept save_credit_card and replace $e2ee
        async def fix_e2ee(route):
            req = route.request
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if ("save_credit_card" in body or "card_data" in body) and "$e2ee" in body:
                    if state["enc_card"] and state["enc_cvv"]:
                        print(f"\n[FIX] Replacing $e2ee with encrypted data!")
                        # Parse the form-encoded body
                        parsed = urllib.parse.parse_qs(body)
                        if "variables" in parsed:
                            v = json.loads(parsed["variables"][0])
                            card_data = v.get("input", {}).get("card_data", {})
                            
                            # Replace $e2ee with encrypted values
                            if card_data.get("credit_card_number", {}).get("sensitive_string_value") == "$e2ee":
                                card_data["credit_card_number"]["sensitive_string_value"] = state["enc_card"]
                            if card_data.get("csc", {}).get("sensitive_string_value") == "$e2ee":
                                card_data["csc"]["sensitive_string_value"] = state["enc_cvv"]
                            
                            # Rebuild the body
                            parsed["variables"] = [json.dumps(v)]
                            new_body = urllib.parse.urlencode(parsed, doseq=True)
                            
                            print(f"  Card encrypted: {state['enc_card'][:50]}...")
                            print(f"  CVV encrypted: {state['enc_cvv'][:50]}...")
                            
                            await route.continue_(post_data=new_body)
                            return
                    else:
                        print(f"[FIX] $e2ee detected but no encrypted data yet!")
            
            await route.continue_()
        
        await page.route("**/billing/graphql/**", fix_e2ee)

        # Load billing page (this triggers get_server_encryption_key)
        print("[1] Loading billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(5)

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

        # Encrypt card data with captured public key
        if state["cert"]:
            print(f"\n[2] Encrypting card with Meta's public key...")
            result = await page.evaluate("""
                async (args) => {
                    try {
                        const certB64 = args.cert;
                        const cardNum = args.card;
                        const cvv = args.cvv;
                        
                        // Decode certificate DER
                        const der = Uint8Array.from(atob(certB64), c => c.charCodeAt(0));
                        
                        // Import as RSA-OAEP public key
                        const key = await crypto.subtle.importKey(
                            'spki', der,
                            {name: 'RSA-OAEP', hash: 'SHA-256'},
                            false, ['encrypt']
                        );
                        
                        // Encrypt card number
                        const encCard = await crypto.subtle.encrypt(
                            {name: 'RSA-OAEP'}, key,
                            new TextEncoder().encode(cardNum)
                        );
                        
                        // Encrypt CVV
                        const encCvv = await crypto.subtle.encrypt(
                            {name: 'RSA-OAEP'}, key,
                            new TextEncoder().encode(cvv)
                        );
                        
                        return {
                            card: btoa(String.fromCharCode(...new Uint8Array(encCard))),
                            cvv: btoa(String.fromCharCode(...new Uint8Array(encCvv))),
                        };
                    } catch(e) {
                        return {error: e.message, stack: e.stack?.substring(0, 300)};
                    }
                }
            """, {"cert": state["cert"], "card": CARD, "cvv": CVV})
            
            if result.get("error"):
                print(f"  ❌ Encrypt error: {result['error']}")
                print(f"  Stack: {result.get('stack')}")
            else:
                state["enc_card"] = result["card"]
                state["enc_cvv"] = result["cvv"]
                print(f"  ✅ Encrypted!")
                print(f"  Card: {result['card'][:60]}...")
                print(f"  CVV: {result['cvv'][:60]}...")
        else:
            print("  ❌ No certificate captured!")

        # Add payment method
        print("\n[3] Adding card...")
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Fill card
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
        print("\n[4] Submit...")
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        body = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" in body:
            print("  ❌ Still rejected")
            print(f"  {body[:300]}")
        elif "Temporarily Blocked" in body:
            print("  ❌ Rate limited")
        elif "Card details" not in body:
            print("  ✅ POSSIBLY ACCEPTED!")
        
        await page.screenshot(path="data/screenshots/e2ee_fix2.png")
        print("\n[DONE]")

asyncio.run(main())
