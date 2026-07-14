#!/usr/bin/env python3
"""
1. Capture full e2ee public key from get_server_encryption_key
2. Encrypt card via Web Crypto in page context  
3. Replace $e2ee in save_credit_card request with encrypted data
"""
import asyncio, json, os, sys, urllib.parse, base64

os.environ["DISPLAY"] = ":99"
CARD = "4889501032758307"
CVV = "424"
EXP = "08/27"

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

    encryption_key_response = None
    save_card_request_body = None
    save_card_response = None
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # STEP 1: Load billing page and capture get_server_encryption_key response
        async def on_resp(resp):
            nonlocal encryption_key_response, save_card_response
            url = resp.url
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body:
                    encryption_key_response = body
                    print(f"[KEY] Got encryption key response ({len(body)} bytes)")
                if "save_credit_card" in body:
                    save_card_response = body
                    print(f"[SAVE] Got save response")
            except: pass
        page.on("response", on_resp)

        # STEP 2: Intercept save_credit_card request to replace $e2ee
        async def intercept_save(route):
            nonlocal save_card_request_body
            req = route.request
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if "save_credit_card" in body or "card_data" in body:
                    save_card_request_body = body
                    parsed = urllib.parse.parse_qs(body)
                    if "variables" in parsed:
                        v = json.loads(parsed["variables"][0])
                        if "card_data" in v and "$e2ee" in json.dumps(v):
                            print(f"\n[INTERCEPT] $e2ee detected in save request!")
                            card_data = v["input"]["card_data"]
                            print(f"  bin: {card_data.get('bin')}")
                            print(f"  last_4: {card_data.get('last_4')}")
                            cnum = card_data.get("credit_card_number", {}).get("sensitive_string_value")
                            csc = card_data.get("csc", {}).get("sensitive_string_value")
                            print(f"  card_number val: {cnum}")
                            print(f"  csc val: {csc}")
                            
                            if cnum == "$e2ee":
                                # Try to encrypt using the page's crypto
                                encrypted_card = await page.evaluate("""
                                    async (cardNum) => {
                                        try {
                                            // Import RSA public key from PEM
                                            const pem = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3xfn/ygWep4PaL0T5oCfo7OdJm0OSqkvX3H2eA0LU/47UjY7B5Q2sRYj8N7vqBKjfGfSPz6RYjCkMv9Z3j1L3Yt8vGvI0jJ0YjCB0x+Mb8qF5p2N0hPv2HF7k8pF2p1YjY0HCY+j0OkQ9FnwKFpnJ8kJuXWQZbYjRYjCkMv9Z3j1L3Yt8vGvI0jJ0YjCB0x+Mb8qF5p2N0hPv2HF7k8pF2p1YjY0HCY+j0OkQ9FnwKFpnJ8kJuXWQZbYjRYjCkMv9Z3j1L3Yt8vGvI0jJ0YjCB0x+Mb8qF5p2N0hPv2HF7k8pF2p1YjY0HCY+j0OkQ9FnwKFpnJ8kJuXWQZbYjRwIDAQAB
-----END PUBLIC KEY-----`;
                                            // This won't work - need real key
                                            return null;
                                        } catch(e) {
                                            return {error: e.message};
                                        }
                                    }
                                """, CARD)
                                print(f"  Encrypt attempt: {encrypted_card}")
                            
            await route.continue_()
        
        await page.route("**/billing/graphql/**", intercept_save)

        print("[1] Loading billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss
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

        # Parse the encryption key response
        if encryption_key_response:
            try:
                body = encryption_key_response
                if body.startswith("for (;;);"):
                    body = body[len("for (;;);"):]
                d = json.loads(body)
                key_data = d.get("data", {}).get("get_server_encryption_key", {})
                trust_chain = key_data.get("trust_chain", [])
                print(f"\n[KEY] Trust chain entries: {len(trust_chain)}")
                for i, cert in enumerate(trust_chain):
                    print(f"  Cert {i}: {len(cert)} chars")
                    # Parse certificate to extract public key
                    cert_result = await page.evaluate("""
                        async (certB64) => {
                            try {
                                // Decode DER from base64
                                const der = Uint8Array.from(atob(certB64), c => c.charCodeAt(0));
                                
                                // Import as X.509 certificate
                                const cert = await crypto.subtle.importKey(
                                    'spki',
                                    der,
                                    {name: 'RSA-OAEP', hash: 'SHA-256'},
                                    false,
                                    ['encrypt']
                                );
                                
                                // Test encrypt
                                const testData = new TextEncoder().encode('test1234');
                                const encrypted = await crypto.subtle.encrypt(
                                    {name: 'RSA-OAEP'},
                                    cert,
                                    testData
                                );
                                
                                return {
                                    success: true,
                                    encryptedLen: encrypted.byteLength,
                                    encryptedB64: btoa(String.fromCharCode(...new Uint8Array(encrypted)))
                                };
                            } catch(e) {
                                return {success: false, error: e.message};
                            }
                        }
                    """, cert)
                    print(f"  Import result: {json.dumps(cert_result)}")
                    
                    if cert_result.get("success"):
                        print(f"\n  ✅ PUBLIC KEY WORKS! Can encrypt data!")
                        
                        # Now encrypt the real card data
                        real_card = CARD
                        real_cvv = CVV
                        
                        encrypted_card = await page.evaluate("""
                            async (args) => {
                                try {
                                    const certB64 = args.cert;
                                    const cardNum = args.card;
                                    const cvv = args.cvv;
                                    
                                    const der = Uint8Array.from(atob(certB64), c => c.charCodeAt(0));
                                    const key = await crypto.subtle.importKey(
                                        'spki', der,
                                        {name: 'RSA-OAEP', hash: 'SHA-256'},
                                        false, ['encrypt']
                                    );
                                    
                                    const encCard = await crypto.subtle.encrypt(
                                        {name: 'RSA-OAEP'}, key,
                                        new TextEncoder().encode(cardNum)
                                    );
                                    const encCvv = await crypto.subtle.encrypt(
                                        {name: 'RSA-OAEP'}, key,
                                        new TextEncoder().encode(cvv)
                                    );
                                    
                                    return {
                                        card: btoa(String.fromCharCode(...new Uint8Array(encCard))),
                                        cvv: btoa(String.fromCharCode(...new Uint8Array(encCvv))),
                                    };
                                } catch(e) {
                                    return {error: e.message, stack: e.stack?.substring(0, 200)};
                                }
                            }
                        """, {"cert": cert, "card": real_card, "cvv": real_cvv})
                        
                        print(f"\n  Encrypted card: {json.dumps(encrypted_card, indent=2)[:200]}")
                        
                        if not encrypted_card.get("error"):
                            # Store for use in intercept
                            page._encrypted_card = encrypted_card["card"]
                            page._encrypted_cvv = encrypted_card["cvv"]
                            page._encryption_done = True
                            
            except Exception as e:
                print(f"[KEY] Parse error: {e}")

        print("\n[2] Adding card...")
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
            for ch in EXP: await page.keyboard.type(ch, delay=60)
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
        print("\n[3] Submit...")
        save_card_response = None
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        if save_card_response:
            body = save_card_response
            if body.startswith("for (;;);"): body = body[len("for (;;);"):]
            try:
                d = json.loads(body)
                r = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
                cc = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("credit_card")
                print(f"  Result: {r.get('status')} | error_code: {r.get('error_code')}")
                if cc:
                    print(f"  ✅ CARD SAVED! {json.dumps(cc)}")
                else:
                    print(f"  ❌ {r.get('message')}")
            except: pass

        body_text = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" in body_text:
            print("  ❌ Card rejected")
        elif "Temporarily Blocked" in body_text:
            print("  ❌ Rate limited")

        await page.screenshot(path="data/screenshots/e2ee_fix.png")
        print("\n[DONE]")

asyncio.run(main())
