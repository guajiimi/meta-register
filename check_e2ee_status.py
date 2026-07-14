"""Check if $e2ee is actually being replaced by Meta's JS."""
import asyncio, json, os, sys, urllib.parse
os.environ["DISPLAY"] = ":99"

async def main():
    from camoufox.async_api import AsyncCamoufox
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        async def on_req(req):
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if "card_data" in body:
                    parsed = urllib.parse.parse_qs(body)
                    if "variables" in parsed:
                        v = json.loads(parsed["variables"][0])
                        cd = v.get("input", {}).get("card_data", {})
                        cnum = cd.get("credit_card_number", {})
                        csc = cd.get("csc", {})
                        ptt = v.get("input", {}).get("platform_trust_token", "")
                        
                        print(f"\n=== CARD SUBMISSION ===")
                        print(f"  card_number: {json.dumps(cnum)}")
                        print(f"  csc: {json.dumps(csc)}")
                        print(f"  trust_token ({len(ptt)} chars): {ptt[:80]}...")
                        
                        # Check if $e2ee
                        cnum_val = cnum.get("sensitive_string_value", "")
                        if cnum_val == "$e2ee":
                            print(f"  ❌ card_number is $e2ee (NOT encrypted)")
                        elif cnum_val.startswith("fp:"):
                            print(f"  ✅ card_number is JWE encrypted!")
                        else:
                            print(f"  ? card_number value: {cnum_val[:80]}")
                        
                        # Decode trust token
                        if ptt:
                            import base64
                            try:
                                padded = ptt + '=' * (4 - len(ptt) % 4)
                                raw = base64.b64decode(padded)
                                text = raw.decode('utf-8', errors='replace')
                                start = text.find('{')
                                if start >= 0:
                                    depth = 0
                                    for i, c in enumerate(text[start:]):
                                        if c == '{': depth += 1
                                        elif c == '}': depth -= 1
                                        if depth == 0:
                                            j = json.loads(text[start:start+i+1])
                                            sigs = j.get("signatures", [])
                                            print(f"  trust_token signatures: {len(sigs)}")
                                            if sigs:
                                                print(f"  ✅ HAS SIGNATURES!")
                                            else:
                                                print(f"  ❌ Empty signatures")
                                            break
                            except Exception as e:
                                print(f"  trust_token decode error: {e}")
        page.on("request", on_req)

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

        # Use JS to click Add payment method
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('div[role="button"], button');
            for (const b of btns) {
                if (b.innerText.includes('Add payment method')) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(5)

        # Fill card
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type("David Davis", delay=30)
        el = await page.query_selector('input[name="cardNumber"]')
        if el: await el.click(); await el.fill(""); [await page.keyboard.type(ch, delay=50) for ch in "4889501032758307"]
        el = await page.query_selector('input[name="expiration"]')
        if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in "08/27"]
        el = await page.query_selector('input[name="securityCode"]')
        if el: await el.click(); await asyncio.sleep(0.2); [await page.keyboard.type(ch, delay=60) for ch in "424"]
        await page.evaluate("""() => {
            for (const inp of document.querySelectorAll('input')) {
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal'))
                    if (!inp.value) { inp.value = '90001'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
            }
        }""")
        await asyncio.sleep(1)

        # Submit
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('div[role="button"], button');
            for (const b of btns) {
                if (b.innerText.trim() === 'Next') {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(10)

        body = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" in body: print("\n  ❌ Card rejected")
        elif "Temporarily Blocked" in body: print("\n  ❌ Rate limited")
        
        print("\n[DONE]")

asyncio.run(main())
