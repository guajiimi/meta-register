#!/usr/bin/env python3
"""E2EE fix: capture X.509 cert, extract SPKI in Python, encrypt in browser."""
import asyncio, json, os, sys, urllib.parse, base64
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes

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

    state = {"spki_b64": None, "enc_card": None, "enc_cvv": None}
    save_response = None
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

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
                        # Parse leaf cert (last in chain) to extract SPKI
                        for cert_b64 in tc:
                            try:
                                cert_der = base64.b64decode(cert_b64)
                                cert = x509.load_der_x509_certificate(cert_der)
                                pub_key = cert.public_key()
                                spki_der = pub_key.public_bytes(
                                    encoding=serialization.Encoding.DER,
                                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                                )
                                state["spki_b64"] = base64.b64encode(spki_der).decode()
                                print(f"[KEY] Extracted SPKI ({len(spki_der)} bytes)")
                                print(f"  Subject: {cert.subject}")
                                break
                            except Exception as e:
                                print(f"[KEY] Cert parse failed: {e}")
                                continue
                if "save_credit_card" in body:
                    save_response = body
            except: pass
        page.on("response", on_resp)

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
                            print("[FIX] $e2ee replaced!")
                            await route.continue_(post_data=new_body)
                            return
            await route.continue_()
        await page.route("**/billing/graphql/**", fix_route)

        # Load billing
        print("[1] Billing...")
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

        # Click Add payment (triggers key fetch)
        print("[2] Add payment...")
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(5)

        # Wait for key
        for i in range(10):
            if state["spki_b64"]: break
            await asyncio.sleep(1)
        
        if not state["spki_b64"]:
            print("  ❌ No SPKI!")
            return

        # Encrypt in browser
        print("[3] Encrypting...")
        result = await page.evaluate("""
            async (args) => {
                try {
                    const spki = Uint8Array.from(atob(args.spki), c => c.charCodeAt(0));
                    const key = await crypto.subtle.importKey(
                        'spki', spki, {name: 'RSA-OAEP', hash: 'SHA-256'}, false, ['encrypt']
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
        """, {"spki": state["spki_b64"], "card": CARD, "cvv": CVV})
        
        if result.get("error"):
            print(f"  ❌ {result['error']}")
            return
        
        state["enc_card"] = result["card"]
        state["enc_cvv"] = result["cvv"]
        print(f"  ✅ Encrypted! Card={len(result['card'])}chars CVV={len(result['cvv'])}chars")

        # Fill card
        print("[4] Fill & Submit...")
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
                err = r.get("error_code")
                print(f"  Status: {r.get('status')} | error_code: {err}")
                if cc:
                    print(f"  ✅ CARD SAVED! {json.dumps(cc)[:300]}")
                else:
                    print(f"  ❌ {r.get('message')}")
            except: pass

        await page.screenshot(path="data/screenshots/e2ee_final.png")
        print("\n[DONE]")

asyncio.run(main())
