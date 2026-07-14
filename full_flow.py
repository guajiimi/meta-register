#!/usr/bin/env python3
"""FULL browser flow: fresh email → register → onboarding → billing → add card → API key."""
import asyncio, json, os, sys, random, string, urllib.parse, base64
from datetime import datetime
from pathlib import Path

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")

CARD = "4889501032758307"
CVV = "424"
EXP = "08/27"
SCREENSHOTS = Path("data/screenshots")
OUTPUT = Path("data/output")

def fresh_email():
    """Generate email that won't conflict with dewixzpajak01 variants."""
    user = ''.join(random.choices(string.ascii_lowercase, k=6)) + str(random.randint(100,999))
    return f"{user}@gmail.com"

async def main():
    from camoufox.async_api import AsyncCamoufox

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    email = fresh_email()
    password = "MetaReg2026!"
    first = random.choice(["David", "James", "Michael", "Robert"])
    last = random.choice(["Smith", "Johnson", "Brown", "Davis"])

    print(f"Email: {email}")
    print(f"Name: {first} {last}")
    print(f"Password: {password}")

    state = {"spki_b64": None, "enc_card": None, "enc_cvv": None}
    save_resp = {"body": None}

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Capture e2ee key + save response
        async def on_resp(resp):
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body if not body.startswith("for (;;);") else body[10:]
                    d = json.loads(raw)
                    tc = d["data"]["get_server_encryption_key"]["trust_chain"]
                    if tc:
                        from cryptography import x509
                        from cryptography.hazmat.primitives import serialization
                        cert = x509.load_der_x509_certificate(base64.b64decode(tc[0]))
                        pub = cert.public_key()
                        spki = pub.public_bytes(encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo)
                        state["spki_b64"] = base64.b64encode(spki).decode()
                        print(f"  [KEY] EC-{pub.key_size} ({len(spki)} bytes)")
                if "save_credit_card" in body:
                    save_resp["body"] = body
            except: pass
        page.on("response", on_resp)

        # Route: replace $e2ee
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

        async def dismiss_modal():
            for _ in range(5):
                els = await page.evaluate("""
                    Array.from(document.querySelectorAll('*')).filter(el =>
                        el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                        el.getBoundingClientRect().height > 20 && el.getBoundingClientRect().width > 40
                    ).map(el => ({r: el.getBoundingClientRect()}))
                """)
                if els:
                    e = els[0]['r']
                    await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                    await asyncio.sleep(2)
                else: break

        # ═══ STEP 1: REGISTER ═══
        print("\n[1] Register at auth.meta.com...")
        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        await page.get_by_text("Use mobile number or email").click()
        await asyncio.sleep(3)

        inp = await page.wait_for_selector('input[type="text"]', timeout=10000)
        await inp.click(); await inp.fill("")
        await page.keyboard.type(email, delay=30)
        await asyncio.sleep(1)

        await page.get_by_text("Continue", exact=True).click()
        await asyncio.sleep(5)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  Step: {body[:80]}")

        if "Enter password instead" in body:
            # This means account exists (shouldn't for fresh email)
            print("  ❌ Account exists! Trying different email...")
            await browser.close()
            return

        # Should be "Create a password" or similar
        if "password" in body.lower() or "create" in body.lower():
            print("  → Creating password...")
            pw = await page.wait_for_selector('input[type="password"]', timeout=10000)
            await pw.fill(password)
            await asyncio.sleep(1)

            # Click Next/Continue
            btns = await page.evaluate("""
                Array.from(document.querySelectorAll('div[role="button"], button'))
                    .filter(b => b.offsetParent !== null)
                    .map(b => b.innerText.trim())
            """)
            print(f"  Buttons: {btns}")
            for text in ["Next", "Continue", "Sign up"]:
                try:
                    await page.get_by_role("button", name=text).click(timeout=3000)
                    print(f"  Clicked: {text}")
                    break
                except: continue
            await asyncio.sleep(5)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  After password: {body[:150]}")

        # Handle birthday
        if "birthday" in body.lower():
            print("  → Birthday...")
            for title, val in [("Month","3"),("Day","15"),("Year","1995")]:
                sel = await page.query_selector(f'select[title="{title}"]')
                if sel: await sel.select_option(value=val)
            for text in ["Next", "Continue", "Sign up"]:
                try:
                    await page.get_by_role("button", name=text).click(timeout=3000)
                    break
                except: continue
            await asyncio.sleep(5)
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"  After birthday: {body[:150]}")

        # Handle OTP
        if "code" in body.lower() or "confirm" in body.lower() or "verification" in body.lower():
            print("  ⏳ OTP verification needed!")
            print(f"  Email: {email}")
            await page.screenshot(path=str(SCREENSHOTS / f"otp_{ts}.png"))
            
            # Try IMAP
            sys.path.insert(0, "/root/meta-register")
            try:
                from imap_otp import read_otp
                print("  Reading OTP via IMAP...")
                otp = read_otp(timeout=120, recipient=email)
                if otp:
                    print(f"  OTP: {otp}")
                    otp_input = await page.query_selector('input[type="text"]')
                    if otp_input:
                        await otp_input.fill(otp)
                        for text in ["Next", "Continue", "Confirm"]:
                            try:
                                await page.get_by_role("button", name=text).click(timeout=3000)
                                break
                            except: continue
                        await asyncio.sleep(5)
                else:
                    print("  ❌ OTP timeout")
            except Exception as e:
                print(f"  ❌ IMAP error: {e}")
                # Save and exit
                await browser.close()
                return

        body = await page.evaluate("document.body?.innerText || ''")
        url = page.url
        print(f"  Final: {body[:150]}")
        print(f"  URL: {url}")

        # Dismiss any onboarding
        await dismiss_modal()
        await page.screenshot(path=str(SCREENSHOTS / f"registered_{ts}.png"))

        # Extract cookies
        all_cookies = await ctx.cookies()
        cks = {c['name']: c['value'] for c in all_cookies if c['name'] in ['datr','ps_l','ps_n','llm_sess','locale','fs','wd','fr','sb','c_user']}
        print(f"  Cookies: {list(cks.keys())}")

        # ═══ STEP 2: BILLING ═══
        print("\n[2] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        if "not available" in body.lower():
            print("  ❌ Geo-blocked! Need VPN.")
            await browser.close()
            return

        billing_url = page.url
        print(f"  URL: {billing_url}")
        await dismiss_modal()

        # Add payment
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=15000)
        await btn.click()
        await asyncio.sleep(5)

        # Wait for e2ee key
        for i in range(10):
            if state["spki_b64"]: break
            await asyncio.sleep(1)

        if state["spki_b64"]:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization as ser, hashes
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.backends import default_backend

            try:
                spki = base64.b64decode(state["spki_b64"])
                srv = ser.load_der_public_key(spki, backend=default_backend())
                eph = ec.generate_private_key(ec.SECP256R1(), default_backend())
                shared = eph.exchange(ec.ECDH(), srv)
                key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"MetaE2EE").derive(shared)
                nonce = os.urandom(12)
                aes = AESGCM(key)
                state["enc_card"] = base64.b64encode(nonce + aes.encrypt(nonce, CARD.encode(), None)).decode()
                state["enc_cvv"] = base64.b64encode(nonce + aes.encrypt(nonce, CVV.encode(), None)).decode()
                print(f"  [E2EE] OK!")
            except Exception as e:
                print(f"  [E2EE] Error: {e}")

        # Fill card
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{first} {last}", delay=30)
        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in CARD: await page.keyboard.type(ch, delay=50)
        el = await page.query_selector('input[name="expiration"]')
        if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in EXP]
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

        # Submit
        save_resp["body"] = None
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        if save_resp["body"]:
            raw = save_resp["body"]
            if raw.startswith("for (;;);"): raw = raw[10:]
            try:
                d = json.loads(raw)
                r = d["data"]["xfb_billing_save_credit_card"]["client_result"]
                cc = d["data"]["xfb_billing_save_credit_card"].get("credit_card")
                print(f"  Status: {r['status']} | err: {r.get('error_code')}")
                if cc: print(f"  ✅ CARD SAVED!")
                else: print(f"  ❌ {r.get('message')}")
            except: pass

        await page.screenshot(path=str(SCREENSHOTS / f"billing_{ts}.png"))

        # ═══ STEP 3: API KEY ═══
        body = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" not in body:
            print("\n[3] API key...")
            await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
            try: await page.wait_for_load_state("networkidle", timeout=15000)
            except: pass
            await asyncio.sleep(3)
            await dismiss_modal()

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
                print(f"  {body[:300]}")

        # Save
        all_cookies = await ctx.cookies()
        cks = {c['name']: c['value'] for c in all_cookies if c['name'] in ['datr','ps_l','ps_n','llm_sess','locale','fs','wd','fr','sb','c_user']}
        output = {"email": email, "password": password, "first_name": first, "last_name": last, "cookies": cks, "billing_url": billing_url, "timestamp": datetime.now().isoformat()}
        with open(OUTPUT / f"full_{ts}.json", "w") as f:
            json.dump(output, f, indent=2)

        await page.screenshot(path=str(SCREENSHOTS / f"final_{ts}.png"))
        print(f"\nSaved: {OUTPUT / f'full_{ts}.json'}")
        print("[DONE]")

asyncio.run(main())
