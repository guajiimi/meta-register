"""Download and analyze Meta's billing JS bundle to find e2ee encryption format."""
import asyncio, json, os, sys, re
os.environ["DISPLAY"] = ":99"

async def main():
    from camoufox.async_api import AsyncCamoufox
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    js_bundles = []
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Capture JS bundles
        async def on_resp(resp):
            url = resp.url
            if "fbcdn.net/rsrc" in url and url.endswith(".js"):
                try:
                    body = await resp.text()
                    if any(k in body for k in ['BillingProtectedString', 'e2ee', 'sensitive_string_value', 'credit_card_number']):
                        js_bundles.append({"url": url, "body": body})
                        print(f"  [JS] Found billing bundle: {len(body)} bytes")
                except: pass
        page.on("response", on_resp)

        # Load billing with add payment
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

        print(f"\n[1] Found {len(js_bundles)} billing JS bundles")
        
        for bundle in js_bundles:
            body = bundle["body"]
            url = bundle["url"]
            print(f"\n=== Bundle: {url.split('/')[-1]} ({len(body)} bytes) ===")
            
            # Search for BillingProtectedString definition
            if 'BillingProtectedString' in body:
                # Find the module definition
                idx = body.find('BillingProtectedString')
                context = body[max(0, idx-200):idx+500]
                print(f"  BillingProtectedString context:\n    {context[:600]}")
            
            # Search for e2ee encryption
            for pattern in ['sensitive_string_value', 'encrypt.*card', 'RSA.OAEP', 'AES.GCM', 'ECDH', 'spki', 'importKey']:
                matches = list(re.finditer(pattern, body, re.IGNORECASE))
                if matches:
                    for m in matches[:2]:
                        ctx_start = max(0, m.start()-100)
                        ctx_end = min(len(body), m.end()+200)
                        print(f"  [{pattern}] at {m.start()}: ...{body[ctx_start:ctx_end][:300]}...")
            
            # Save bundle for analysis
            fname = url.split('/')[-1][:50]
            with open(f"data/output/js_{fname}", "w") as f:
                f.write(body)
            print(f"  Saved: data/output/js_{fname}")

        print("\n[DONE]")

asyncio.run(main())
