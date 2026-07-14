#!/usr/bin/env python3
"""E2EE with EC P-256: ECDH key exchange + AES-GCM encryption."""
import asyncio, json, os, sys, urllib.parse, base64
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend

os.environ["DISPLAY"] = ":99"
CARD = "4889501032758307"
CVV = "424"

SPKI_B64 = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEWF+Jmen2KzaSBDLNZkBANoctVktFlWpsqyTAydM5uv8WglpjC3JmazYHxRxIGwd57njMKzsYRTNm+aS3yj8HjA=="

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

    save_response = None
    enc_card = None
    enc_cvv = None
    
    # Encrypt card data using ECDH + AES-GCM
    print("[0] Encrypting card with ECDH + AES-GCM...")
    result = await asyncio.get_event_loop().run_in_executor(None, lambda: _encrypt(SPKI_B64, CARD, CVV))
    if result.get("error"):
        print(f"  ❌ {result['error']}")
        return
    enc_card = result["card"]
    enc_cvv = result["cvv"]
    ephemeral_pub = result["ephemeral_pub"]
    print(f"  ✅ Encrypted!")
    print(f"  Ephemeral pub: {ephemeral_pub[:60]}...")
    print(f"  Enc card: {enc_card[:60]}...")
    print(f"  Enc CVV: {enc_cvv[:60]}...")
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        async def on_resp(resp):
            nonlocal save_response
            try:
                body = await resp.text()
                if "save_credit_card" in body:
                    save_response = body
            except: pass
        page.on("response", on_resp)

        # Route: replace $e2ee
        async def fix_route(route):
            req = route.request
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if "$e2ee" in body and enc_card:
                    parsed = urllib.parse.parse_qs(body)
                    if "variables" in parsed:
                        v = json.loads(parsed["variables"][0])
                        cd = v.get("input", {}).get("card_data", {})
                        if cd.get("credit_card_number", {}).get("sensitive_string_value") == "$e2ee":
                            cd["credit_card_number"]["sensitive_string_value"] = enc_card
                            cd["csc"]["sensitive_string_value"] = enc_cvv
                            parsed["variables"] = [json.dumps(v)]
                            new_body = urllib.parse.urlencode(parsed, doseq=True)
                            print("[FIX] Replaced $e2ee!")
                            await route.continue_(post_data=new_body)
                            return
            await route.continue_()
        await page.route("**/billing/graphql/**", fix_route)

        print("\n[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        for _ in range(5):
            els = await page.evaluate("""Array.from(document.querySelectorAll('*')).filter(el => el.innerText?.trim() === 'Continue' && el.offsetParent !== null && el.getBoundingClientRect().height > 20).map(el => ({r: el.getBoundingClientRect()}))""")
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                await asyncio.sleep(2)
            else: break

        print("[2] Add payment...")
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=15000)
        await btn.click()
        await asyncio.sleep(4)

        print("[3] Fill & Submit...")
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
                print(f"  Status: {r.get('status')} | error_code: {r.get('error_code')}")
                if cc:
                    print(f"  ✅ CARD SAVED! {json.dumps(cc)[:300]}")
                else:
                    print(f"  ❌ {r.get('message')}")
            except: pass

        await page.screenshot(path="data/screenshots/e2ee_ec.png")
        print("\n[DONE]")


def _encrypt(spki_b64, card, cvv):
    try:
        # Import server's EC public key
        spki_der = base64.b64decode(spki_b64)
        server_pub = serialization.load_der_public_key(spki_der, backend=default_backend())
        
        # Generate ephemeral ECDH key pair
        ephemeral_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        ephemeral_pub_der = ephemeral_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Derive shared secret
        shared_key = ephemeral_key.exchange(ec.ECDH(), server_pub)
        
        # Derive AES key using HKDF
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"MetaE2EE",
        ).derive(shared_key)
        
        # Encrypt with AES-GCM
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import os as _os
        nonce = _os.urandom(12)
        
        aesgcm = AESGCM(derived_key)
        enc_card_bytes = aesgcm.encrypt(nonce, card.encode(), None)
        enc_cvv_bytes = aesgcm.encrypt(nonce, cvv.encode(), None)
        
        # Format: nonce + ephemeral_pub + ciphertext (all base64)
        enc_card_b64 = base64.b64encode(nonce + ephemeral_pub_der + enc_card_bytes).decode()
        enc_cvv_b64 = base64.b64encode(nonce + ephemeral_pub_der + enc_cvv_bytes).decode()
        ephemeral_pub_b64 = base64.b64encode(ephemeral_pub_der).decode()
        
        return {
            "card": enc_card_b64,
            "cvv": enc_cvv_b64,
            "ephemeral_pub": ephemeral_pub_b64,
        }
    except Exception as e:
        return {"error": str(e)}


asyncio.run(main())
