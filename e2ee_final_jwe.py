"""Meta e2ee encryption with EXACT concat KDF from JS bundle."""
import asyncio, json, os, sys, base64, urllib.parse, struct, hashlib
from datetime import datetime
os.environ["DISPLAY"] = ":99"

CARD = "4889501032758307"
CVV = "424"

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def big_endian_u32(n: int) -> bytes:
    return struct.pack('>I', n)

def concat_kdf(shared_secret: bytes, alg: str, apu: str, apv: str, key_bits: int = 256) -> bytes:
    """NIST SP 800-56A Single-Step KDF (exact Meta implementation)."""
    counter = big_endian_u32(1)
    key_len = big_endian_u32(key_bits)
    
    parts = [counter, shared_secret]
    for info in [alg, apu, apv]:
        info_bytes = info.encode()
        parts.append(big_endian_u32(len(info_bytes)))
        parts.append(info_bytes)
    parts.append(key_len)
    
    return b''.join(parts)

async def encrypt_card(spki_der: bytes, card_number: str, csc: str):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization as ser, hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.backends import default_backend

    # 1. Import server's EC public key
    server_pub = ser.load_der_public_key(spki_der, backend=default_backend())
    
    # 2. Generate ephemeral ECDH key pair
    ephemeral = ec.generate_private_key(ec.SECP256R1(), default_backend())
    ephemeral_pub_spki = ephemeral.public_key().public_bytes(
        encoding=ser.Encoding.DER, format=ser.PublicFormat.SubjectPublicKeyInfo
    )
    ephemeral_pub_pem = ephemeral.public_key().public_bytes(
        encoding=ser.Encoding.PEM, format=ser.PublicFormat.SubjectPublicKeyInfo
    ).decode().strip()
    
    # 3. ECDH → 256 bits
    shared_secret = ephemeral.exchange(ec.ECDH(), server_pub)
    
    # 4. Get kid fingerprint (SHA-256 of SPKI → base64url → "fp:...")
    kid_hash = hashlib.sha256(ephemeral_pub_spki).digest()
    kid = "fp:" + b64url(kid_hash)
    
    # 5. Get server key fingerprint
    server_hash = hashlib.sha256(spki_der).digest()
    server_fp = "fp:" + b64url(server_hash)
    
    # 6. Concat KDF
    kdf_input = concat_kdf(shared_secret, "A256GCM", kid, server_fp, 256)
    
    # 7. SHA-256 → AES key
    aes_key = hashlib.sha256(kdf_input).digest()
    
    # 8. Build JOSE header
    jose_header = {
        "alg": "ECDH-ES",
        "apu": kid,
        "apv": server_fp,
        "enc": "A256GCM",
        "epk": {
            "crv": "P-256",
            "kty": "EC",
            "pem": ephemeral_pub_pem
        }
    }
    
    # 9. Build additional data
    header_b64 = b64url(json.dumps(jose_header).encode())
    ad_string = header_b64 + "." + b64url(kid.encode())
    additional_data = ad_string.encode()
    
    # 10. Encrypt with AES-256-GCM
    iv = os.urandom(12)
    aesgcm = AESGCM(aes_key)
    plaintext = card_number.encode()
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext, additional_data)
    
    # 11. Split ciphertext and tag
    tag = ciphertext_with_tag[-16:]
    ciphertext = ciphertext_with_tag[:-16]
    
    # 12. Build JWE
    jwe = kid + "." + ".".join([
        b64url(json.dumps(jose_header).encode()),
        b64url(b""),
        b64url(iv),
        b64url(ciphertext),
        b64url(tag)
    ])
    
    return jwe

async def main():
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from camoufox.async_api import AsyncCamoufox
    
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    state = {"spki_der": None, "enc_card": None, "enc_cvv": None}
    save_resp = {"body": None}
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        async def on_resp(resp):
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body if not body.startswith("for (;;);") else body[10:]
                    d = json.loads(raw)
                    tc = d["data"]["get_server_encryption_key"]["trust_chain"]
                    if tc:
                        cert = x509.load_der_x509_certificate(base64.b64decode(tc[0]))
                        spki = cert.public_key().public_bytes(
                            encoding=serialization.Encoding.DER,
                            format=serialization.PublicFormat.SubjectPublicKeyInfo
                        )
                        state["spki_der"] = spki
                        print(f"  [KEY] EC-{cert.public_key().key_size} ({len(spki)} bytes)")
                if "save_credit_card" in body:
                    save_resp["body"] = body
            except: pass
        page.on("response", on_resp)

        async def fix_e2ee(route):
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
                            print("  [FIX] $e2ee → JWE!")
                            await route.continue_(post_data=urllib.parse.urlencode(parsed, doseq=True))
                            return
            await route.continue_()
        await page.route("**/billing/graphql/**", fix_e2ee)

        print("[1] Billing...")
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

        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=15000)
        await btn.click()
        await asyncio.sleep(5)

        for i in range(10):
            if state["spki_der"]: break
            await asyncio.sleep(1)

        if state["spki_der"]:
            print("[2] Encrypting...")
            state["enc_card"] = await encrypt_card(state["spki_der"], CARD, CVV)
            state["enc_cvv"] = await encrypt_card(state["spki_der"], CVV, CVV)
            print(f"  Card: {len(state['enc_card'])} chars")
            print(f"  CVV: {len(state['enc_cvv'])} chars")

        print("[3] Fill & Submit...")
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
        el = await page.query_selector('input[name="cardNumber"]')
        if el: await el.click(); await el.fill(""); [await page.keyboard.type(ch, delay=50) for ch in CARD]
        el = await page.query_selector('input[name="expiration"]')
        if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in "08/27"]
        el = await page.query_selector('input[name="securityCode"]')
        if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in CVV]
        await page.evaluate("""() => {
            for (const inp of document.querySelectorAll('input')) {
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal'))
                    if (!inp.value) { inp.value = '90001'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
            }
        }""")
        await asyncio.sleep(1)

        save_resp["body"] = None
        btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if btn: await btn.click(force=True)
        await asyncio.sleep(10)

        if save_resp["body"]:
            raw = save_resp["body"]
            if raw.startswith("for (;;);"): raw = raw[10:]
            d = json.loads(raw)
            r = d["data"]["xfb_billing_save_credit_card"]["client_result"]
            cc = d["data"]["xfb_billing_save_credit_card"].get("credit_card")
            print(f"  Status: {r['status']} | err: {r.get('error_code')}")
            if cc:
                print(f"  ✅ CARD SAVED!")
            else:
                print(f"  ❌ {r.get('message')}")
        else:
            body = await page.evaluate("document.body?.innerText || ''")
            if "Couldn't save" in body: print("  ❌ Rejected")

        await page.screenshot(path="data/screenshots/e2ee_final.png")
        print("\n[DONE]")

asyncio.run(main())
