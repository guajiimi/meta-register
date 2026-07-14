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

        key_data = None
        async def on_resp(resp):
            nonlocal key_data
            try:
                body = await resp.text()
                if "get_server_encryption_key" in body and "trust_chain" in body:
                    raw = body
                    if raw.startswith("for (;;);"): raw = raw[len("for (;;);"):]
                    key_data = json.loads(raw)
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
            if key_data: break
            await asyncio.sleep(1)

        if key_data:
            raw = json.dumps(key_data)
            d = json.loads(raw)
            kek = d.get("data", {}).get("get_server_encryption_key", {})
            print(f"Keys: {list(kek.keys())}")
            tc = kek.get("trust_chain", [])
            print(f"Trust chain: {len(tc)} certs")
            for i, c in enumerate(tc):
                print(f"  Cert {i}: {len(c)} chars")
            
            # Try importing each cert
            for i, c in enumerate(tc):
                result = await page.evaluate("""
                    async (certB64) => {
                        try {
                            const der = Uint8Array.from(atob(certB64), ch => ch.charCodeAt(0));
                            const key = await crypto.subtle.importKey(
                                'spki', der, {name: 'RSA-OAEP', hash: 'SHA-256'}, false, ['encrypt']
                            );
                            const test = await crypto.subtle.encrypt(
                                {name: 'RSA-OAEP'}, key, new TextEncoder().encode('test')
                            );
                            return {ok: true, len: test.byteLength};
                        } catch(e) {
                            return {ok: false, error: e.message};
                        }
                    }
                """, c)
                print(f"  Cert {i} import: {result}")
            
            # Also check if there's a separate public_key field
            print(f"\nAll fields: {json.dumps({k: type(v).__name__ for k, v in kek.items()})}")
            for k, v in kek.items():
                if isinstance(v, str) and len(v) > 100:
                    print(f"  {k}: ({len(v)} chars) {v[:80]}...")
                elif not isinstance(v, (list, dict)):
                    print(f"  {k}: {v}")

asyncio.run(main())
