"""Test Meta billing with CloakBrowser stealth Chromium."""
import asyncio, json, os, sys, urllib.parse
os.environ["DISPLAY"] = ":99"

CARD = "4889501032758307"
CVV = "424"
EXP = "08/27"

async def main():
    import cloakbrowser
    
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    print(f"Account: {acc['email']}")

    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    card_data = {}

    async with cloakbrowser.launch_async(headless=False) as browser:
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
                        
                        card_data["cnum"] = cnum
                        card_data["csc"] = csc
                        card_data["ptt"] = ptt
                        
                        cnum_val = cnum.get("sensitive_string_value", "")
                        print(f"\n=== REQUEST ===")
                        print(f"  card: {cnum_val[:60]}")
                        print(f"  trust_token ({len(ptt)} chars): {ptt[:60]}")
                        
                        if cnum_val == "$e2ee":
                            print(f"  ❌ $e2ee NOT encrypted")
                        elif cnum_val.startswith("fp:"):
                            print(f"  ✅ JWE encrypted!")
                        else:
                            print(f"  ? value: {cnum_val[:40]}")
        page.on("request", on_req)

        # Check trust token support
        print("\n[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        if "not available" in body.lower():
            print("  ❌ Geo-blocked!")
            await browser.close()
            return

        # Dismiss
        for _ in range(5):
            els = await page.evaluate("""Array.from(document.querySelectorAll('*')).filter(el => el.innerText?.trim() === 'Continue' && el.offsetParent !== null && el.getBoundingClientRect().height > 20).map(el => ({r: el.getBoundingClientRect()}))""")
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                await asyncio.sleep(2)
            else: break

        # Check trust token
        trust = await page.evaluate("""
            async () => ({
                hasTrustToken: typeof document.hasTrustToken === 'function',
                hasPrivateStateToken: typeof document.hasPrivateStateToken === 'function',
                hasCrypto: typeof crypto?.subtle !== 'undefined',
            })
        """)
        print(f"  Trust: {json.dumps(trust)}")

        # Add payment
        print("\n[2] Add payment...")
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
        print("  Filling card...")
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
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
        print("\n[3] Submit...")
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
        if "Couldn't save" in body:
            print("  ❌ Card rejected")
        elif "Temporarily Blocked" in body:
            print("  ❌ Rate limited")
        else:
            print(f"  {body[:200]}")

        await page.screenshot(path="data/screenshots/cloak_billing.png")
        print("\n[DONE]")
        await browser.close()

asyncio.run(main())
