#!/usr/bin/env python3
"""Full browser flow: register via auth.meta.com → billing → add card → API key.
Intercept $e2ee and replace with properly encrypted data."""
import asyncio, json, os, sys, random, string, urllib.parse, base64
from datetime import datetime
from pathlib import Path

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address

SCREENSHOTS = Path("data/screenshots")
OUTPUT = Path("data/output")

CARD = "4889501032758307"
CVV = "424"
EXP = "08/27"

def gen_email():
    base = "dewixzpajak01"
    dots = list(base)
    n = random.randint(2, 4)
    pos = sorted(random.sample(range(1, len(dots)), n))
    for i, p in enumerate(pos): dots.insert(p+i, '.')
    return ''.join(dots) + '@gmail.com'

async def main():
    from camoufox.async_api import AsyncCamoufox

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    email = gen_email()
    password = "MetaReg2026!"
    first = random.choice(["David", "James", "Michael"])
    last = random.choice(["Smith", "Johnson", "Brown"])
    addr = generate_us_address()

    print(f"Email: {email}")
    print(f"Name: {first} {last}")

    state = {"spki_b64": None, "enc_card": None, "enc_cvv": None, "step": "register"}
    save_resp = {"body": None}

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Capture e2ee key
        async def on_resp(resp):
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body
                    if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
                    d = json.loads(raw)
                    tc = d["data"]["get_server_encryption_key"]["trust_chain"]
                    if tc:
                        # Parse cert with Python
                        from cryptography import x509
                        from cryptography.hazmat.primitives import serialization
                        cert_der = base64.b64decode(tc[0])
                        cert = x509.load_der_x509_certificate(cert_der)
                        pub = cert.public_key()
                        spki = pub.public_bytes(
                            encoding=serialization.Encoding.DER,
                            format=serialization.PublicFormat.SubjectPublicKeyInfo
                        )
                        state["spki_b64"] = base64.b64encode(spki).decode()
                        print(f"  [KEY] EC-{pub.key_size} SPKI ({len(spki)} bytes)")
                if "save_credit_card" in body and state["step"] == "billing":
                    save_resp["body"] = body
            except Exception as e:
                pass
        page.on("response", on_resp)

        # Route: replace $e2ee with encrypted data
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
                            new_body = urllib.parse.urlencode(parsed, doseq=True)
                            print("  [FIX] $e2ee → encrypted!")
                            await route.continue_(post_data=new_body)
                            return
            await route.continue_()
        await page.route("**/billing/graphql/**", fix_e2ee)

        async def snap(name):
            await page.screenshot(path=str(SCREENSHOTS / f"full_{name}_{ts}.png"))

        # ═══════════════════════════════════════════════════
        # STEP 1: REGISTER
        # ═══════════════════════════════════════════════════
        print("\n[1] Register...")
        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Click "Use mobile number or email"
        await page.get_by_text("Use mobile number or email").click()
        await asyncio.sleep(3)

        # Fill email
        inp = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await inp.click(); await inp.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)

        # Continue
        await page.get_by_text("Continue", exact=True).click()
        await asyncio.sleep(5)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  After email: {body[:100]}")

        # Check if it's OTP or password page
        if "Enter password instead" in body:
            print("  → Password option available")
            await page.get_by_role("button", name="Enter password instead").click()
            await asyncio.sleep(3)
            
            pw = await page.wait_for_selector('input[type="password"]', timeout=10000)
            await pw.fill(password)
            await asyncio.sleep(1)
            
            # Click "Next" on password page
            btns = await page.evaluate("""
                Array.from(document.querySelectorAll('div[role="button"], button'))
                    .filter(b => b.offsetParent !== null && (b.innerText.trim() === 'Next' || b.innerText.trim() === 'Continue' || b.innerText.trim() === 'Log in'))
                    .map(b => ({text: b.innerText.trim(), rect: b.getBoundingClientRect()}))
            """)
            if btns:
                e = btns[0]['rect']
                await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                print(f"  Clicked: {btns[0]['text']}")
            await asyncio.sleep(5)
        elif "code" in body.lower() or "verification" in body.lower():
            print("  → OTP required! Need IMAP.")
            # TODO: IMAP OTP
            await snap("otp")
            print("  ❌ Can't proceed without OTP. Save cookies and exit.")
            await browser.close()
            return

        body = await page.evaluate("document.body?.innerText || ''")
        url = page.url
        print(f"  After login: {body[:200]}")
        print(f"  URL: {url}")

        # Handle post-login screens (birthday, etc.)
        for _ in range(5):
            body = await page.evaluate("document.body?.innerText || ''")
            if "birthday" in body.lower():
                print("  → Filling birthday...")
                for title, val in [("Month","3"),("Day","15"),("Year","1995")]:
                    sel = await page.query_selector(f'select[title="{title}"]')
                    if sel: await sel.select_option(value=val)
                btn = await page.query_selector(':is(div[role="button"], button):has-text("Next")')
                if btn: await btn.click()
                await asyncio.sleep(5)
                continue
            if "Welcome" in body or "Continue" in body:
                els = await page.evaluate("""
                    Array.from(document.querySelectorAll('*')).filter(el =>
                        el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                        el.getBoundingClientRect().height > 20
                    ).map(el => ({r: el.getBoundingClientRect()}))
                """)
                if els:
                    e = els[0]['r']
                    await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                    await asyncio.sleep(2)
                    continue
            break

        # Extract cookies
        all_cookies = await ctx.cookies()
        cookie_dict = {}
        for c in all_cookies:
            if c['name'] in ['datr','ps_l','ps_n','llm_sess','locale','fs','wd','fr','sb','c_user']:
                cookie_dict[c['name']] = c['value']
        print(f"  Cookies: {list(cookie_dict.keys())}")

        # ═══════════════════════════════════════════════════
        # STEP 2: BILLING
        # ═══════════════════════════════════════════════════
        print("\n[2] Billing...")
        state["step"] = "billing"
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        billing_url = page.url
        print(f"  URL: {billing_url}")

        # Dismiss
        for _ in range(5):
            els = await page.evaluate("""
                Array.from(document.querySelectorAll('*')).filter(el =>
                    el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                    el.getBoundingClientRect().height > 20
                ).map(el => ({r: el.getBoundingClientRect()}))
            """)
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                await asyncio.sleep(2)
            else: break

        # Add payment
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=15000)
        await btn.click()
        await asyncio.sleep(5)

        # Wait for e2ee key
        for i in range(10):
            if state["spki_b64"]: break
            await asyncio.sleep(1)

        if state["spki_b64"]:
            # Encrypt card
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization as ser, hashes
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.backends import default_backend

            try:
                spki_der = base64.b64decode(state["spki_b64"])
                server_pub = ser.load_der_public_key(spki_der, backend=default_backend())
                ephemeral = ec.generate_private_key(ec.SECP256R1(), default_backend())
                shared = ephemeral.exchange(ec.ECDH(), server_pub)
                key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"MetaE2EE").derive(shared)
                nonce = os.urandom(12)
                aes = AESGCM(key)
                enc_c = base64.b64encode(nonce + aes.encrypt(nonce, CARD.encode(), None)).decode()
                enc_v = base64.b64encode(nonce + aes.encrypt(nonce, CVV.encode(), None)).decode()
                state["enc_card"] = enc_c
                state["enc_cvv"] = enc_v
                print(f"  [E2EE] Encrypted! Card={len(enc_c)}chars CVV={len(enc_v)}chars")
            except Exception as e:
                print(f"  [E2EE] Error: {e}")
        else:
            print("  [E2EE] No key captured!")

        # Fill card
        print("  Filling card...")
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{first} {last}", delay=30)
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
        await page.evaluate(f"""() => {{
            for (const inp of document.querySelectorAll('input')) {{
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {{
                    if (!inp.value) {{ inp.value = '{addr["zip"]}'; inp.dispatchEvent(new Event('input', {{bubbles: true}})); }}
                }}
            }}
        }}""")
        await asyncio.sleep(1)

        # Submit
        save_resp["body"] = None
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        if save_resp["body"]:
            raw = save_resp["body"]
            if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
            try:
                d = json.loads(raw)
                r = d["data"]["xfb_billing_save_credit_card"]["client_result"]
                cc = d["data"]["xfb_billing_save_credit_card"].get("credit_card")
                print(f"  Status: {r.get('status')} | err: {r.get('error_code')}")
                if cc:
                    print(f"  ✅ CARD SAVED!")
                else:
                    print(f"  ❌ {r.get('message')}")
            except: pass

        await snap("billing")

        # ═══════════════════════════════════════════════════
        # STEP 3: API KEY
        # ═══════════════════════════════════════════════════
        body = await page.evaluate("document.body?.innerText || ''")
        if "Card details" not in body and "Couldn't save" not in body:
            print("\n[3] Creating API key...")
            await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
            try: await page.wait_for_load_state("networkidle", timeout=15000)
            except: pass
            await asyncio.sleep(3)

            for _ in range(3):
                els = await page.evaluate("""
                    Array.from(document.querySelectorAll('*')).filter(el =>
                        el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                        el.getBoundingClientRect().height > 20
                    ).map(el => ({r: el.getBoundingClientRect()}))
                """)
                if els:
                    e = els[0]['r']
                    await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                    await asyncio.sleep(2)
                else: break

            create = await page.query_selector(':is(button, [role="button"]):has-text("Create API key")')
            if create and not await create.is_disabled():
                await create.click(force=True)
                await asyncio.sleep(3)
                name_inp = await page.query_selector('input[type="text"]')
                if name_inp:
                    await name_inp.fill("default")
                    sub = await page.query_selector(':is(button, [role="button"]):has-text("Create")')
                    if sub: await sub.click(force=True)
                    await asyncio.sleep(5)
                body = await page.evaluate("document.body?.innerText || ''")
                print(f"  Result: {body[:300]}")

        # Save output
        all_cookies = await ctx.cookies()
        cookie_dict = {}
        for c in all_cookies:
            if c['name'] in ['datr','ps_l','ps_n','llm_sess','locale','fs','wd','fr','sb','c_user']:
                cookie_dict[c['name']] = c['value']

        output = {
            "email": email, "password": password,
            "first_name": first, "last_name": last,
            "cookies": cookie_dict, "billing_url": billing_url,
            "timestamp": datetime.now().isoformat(),
        }
        with open(OUTPUT / f"browser_{ts}.json", "w") as f:
            json.dump(output, f, indent=2)

        await snap("final")
        print(f"\nSaved: {OUTPUT / f'browser_{ts}.json'}")
        print("[DONE]")

asyncio.run(main())
