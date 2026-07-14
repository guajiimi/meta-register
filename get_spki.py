#!/usr/bin/env python3
import asyncio, json, os, sys, base64
os.environ["DISPLAY"] = ":99"
from cryptography import x509
from cryptography.hazmat.primitives import serialization

async def main():
    from camoufox.async_api import AsyncCamoufox
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    domain_map = {"datr": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        cert = None
        async def on_resp(resp):
            nonlocal cert
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body
                    if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
                    d = json.loads(raw)
                    tc = d["data"]["get_server_encryption_key"]["trust_chain"]
                    if tc: cert = tc[0]
            except: pass
        page.on("response", on_resp)

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

        for _ in range(10):
            if cert: break
            await asyncio.sleep(1)

        if cert:
            print(f"Cert ({len(cert)} chars): {cert[:80]}...")
            der = base64.b64decode(cert)
            c = x509.load_der_x509_certificate(der)
            pub = c.public_key()
            print(f"Key type: {type(pub).__name__}, size: {pub.key_size}")
            spki = pub.public_bytes(encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo)
            print(f"SPKI: {len(spki)} bytes")
            spki_b64 = base64.b64encode(spki).decode()
            print(f"SPKI b64: {spki_b64}")
        else:
            print("No cert")

asyncio.run(main())
