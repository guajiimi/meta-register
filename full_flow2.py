#!/usr/bin/env python3
"""FULL browser flow v2: correct registration steps."""
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
    return ''.join(random.choices(string.ascii_lowercase, k=6)) + str(random.randint(100,999)) + "@gmail.com"

async def main():
    from camoufox.async_api import AsyncCamoufox

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    email = fresh_email()
    password = "MetaReg2026!"
    first = random.choice(["David", "James", "Michael", "Robert"])
    last = random.choice(["Smith", "Johnson", "Brown", "Davis"])

    print(f"Email: {email} | Name: {first} {last}")

    state = {"spki_b64": None, "enc_card": None, "enc_cvv": None}
    save_resp = {"body": None}

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
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
                        from cryptography import x509
                        from cryptography.hazmat.primitives import serialization
                        cert = x509.load_der_x509_certificate(base64.b64decode(tc[0]))
                        spki = cert.public_key().public_bytes(encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo)
                        state["spki_b64"] = base64.b64encode(spki).decode()
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
                            print("  [FIX] $e2ee → encrypted!")
                            await route.continue_(post_data=urllib.parse.urlencode(parsed, doseq=True))
                            return
            await route.continue_()
        await page.route("**/billing/graphql/**", fix_e2ee)

        async def dismiss():
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

        # ═══ REGISTER ═══
        print("\n[1] Register...")
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

        # "Create a new Meta account?"
        body = await page.evaluate("document.body?.innerText || ''")
        if "Create new account" in body:
            print("  → Create new account")
            await page.get_by_role("button", name="Create new account").click()
            await asyncio.sleep(5)

        # "What's your name?"
        body = await page.evaluate("document.body?.innerText || ''")
        if "name" in body.lower():
            print("  → Name...")
            inputs = await page.query_selector_all('input[type="text"]')
            if len(inputs) >= 2:
                await inputs[0].click(); await inputs[0].fill(first)
                await inputs[1].click(); await inputs[1].fill(last)
            btn = await page.get_by_role("button", name="Next").click()
            await asyncio.sleep(5)

        # Password
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  → {body[:80]}")
        if "password" in body.lower() and "create" in body.lower():
            print("  → Password...")
            pw = await page.wait_for_selector('input[type="password"]', timeout=10000)
            await pw.fill(password)
            await asyncio.sleep(1)
            await page.get_by_role("button", name="Next").click()
            await asyncio.sleep(5)

        # Birthday
        body = await page.evaluate("document.body?.innerText || ''")
        if "birthday" in body.lower():
            print("  → Birthday...")
            for title, val in [("Month","3"),("Day","15"),("Year","1995")]:
                sel = await page.query_selector(f'select[title="{title}"]')
                if sel: await sel.select_option(value=val)
            await page.get_by_role("button", name="Next").click()
            await asyncio.sleep(5)

        # OTP
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  → {body[:100]}")
        if "code" in body.lower() or "confirm" in body.lower():
            print(f"  ⏳ OTP for {email}...")
            try:
                from imap_otp import read_otp
                otp = read_otp(timeout=120, recipient=email)
                if otp:
                    print(f"  OTP: {otp}")
                    otp_input = await page.wait_for_selector('input[type="text"]', timeout=10000)
                    await otp_input.fill(otp)
                    await asyncio.sleep(1)
                    await page.get_by_role("button", name="Next").click()
                    await asyncio.sleep(5)
                else:
                    print("  ❌ OTP timeout")
                    await page.screenshot(path=str(SCREENSHOTS / f"otp_timeout_{ts}.png"))
                    await browser.close()
                    return
            except Exception as e:
                print(f"  ❌ IMAP error: {e}")
                await page.screenshot(path=str(SCREENSHOTS / f"otp_error_{ts}.png"))
                await browser.close()
                return

        # Post-registration
        body = await page.evaluate("document.body?.innerText || ''")
        url = page.url
        print(f"  ✅ Registered! URL: {url[:80]}")
        await dismiss()

        # ═══ BILLING ═══
        print("\n[2] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        if "not available" in body.lower():
            print("  ❌ Geo-blocked!")
            await browser.close()
            return

        billing_url = page.url
        print(f"  URL: {billing_url}")
        await dismiss()

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
                srv = ser.load_der_public_key(base64.b64decode(state["spki_b64"]), backend=default_backend())
                eph = ec.generate_private_key(ec.SECP256R1(), default_backend())
                shared = eph.exchange(ec.ECDH(), srv)
                key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"MetaE2EE").derive(shared)
                nonce = os.urandom(12)
                aes = AESGCM(key)
                state["enc_card"] = base64.b64encode(nonce + aes.encrypt(nonce, CARD.encode(), None)).decode()
                state["enc_cvv"] = base64.b64encode(nonce + aes.encrypt(nonce, CVV.encode(), None)).decode()
                print(f"  [E2EE] Encrypted!")
            except Exception as e:
                print(f"  [E2EE] Error: {e}")

        # Fill card
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{first} {last}", delay=30)
        el = await page.query_selector('input[name="cardNumber"]')
        if el: await el.click(); await el.fill(""); [await page.keyboard.type(ch, delay=50) for ch in CARD]
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
        btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if btn: await btn.click(force=True)
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
        else:
            body = await page.evaluate("document.body?.innerText || ''")
            if "Couldn't save" in body: print("  ❌ Rejected")
            else: print(f"  ? {body[:100]}")

        await page.screenshot(path=str(SCREENSHOTS / f"billing_{ts}.png"))

        # ═══ API KEY ═══
        body = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" not in body:
            print("\n[3] API key...")
            await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
            try: await page.wait_for_load_state("networkidle", timeout=15000)
            except: pass
            await asyncio.sleep(3)
            await dismiss()

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
        print(f"\n[DONE] Saved: full_{ts}.json")

asyncio.run(main())
