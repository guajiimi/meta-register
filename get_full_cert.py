#!/usr/bin/env python3
import asyncio, json, os, sys
os.environ["DISPLAY"] = ":99"

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

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        full_key_response = None
        async def on_resp(resp):
            nonlocal full_key_response
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    full_key_response = body
            except: pass
        page.on("response", on_resp)

        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

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

        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(5)

        for i in range(10):
            if full_key_response: break
            await asyncio.sleep(1)

        if full_key_response:
            raw = full_key_response
            if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
            d = json.loads(raw)
            tc = d["data"]["get_server_encryption_key"]["trust_chain"]
            
            print(f"Trust chain: {len(tc)} certs")
            for i, c in enumerate(tc):
                print(f"\nCert {i}: {len(c)} chars")
                print(f"  First 80: {c[:80]}")
                print(f"  Last 80: {c[-80:]}")
                
                # Try to decode and parse
                import base64
                from cryptography import x509
                try:
                    der = base64.b64decode(c)
                    print(f"  DER length: {len(der)}")
                    cert = x509.load_der_x509_certificate(der)
                    print(f"  Subject: {cert.subject}")
                    print(f"  Issuer: {cert.issuer}")
                    print(f"  Not valid after: {cert.not_valid_after_utc}")
                    
                    pub = cert.public_key()
                    spki = pub.public_bytes(
                        encoding=serialization.Encoding.DER,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                    print(f"  SPKI length: {len(spki)}")
                    print(f"  Key type: {pub.key_size}-bit {pub.__class__.__name__}")
                except Exception as e:
                    print(f"  Error: {e}")

asyncio.run(main())
