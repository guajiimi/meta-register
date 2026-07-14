"""Test Chrome with swtpm — check if platform_trust_token changes."""
import asyncio, json, os, sys
os.environ["DISPLAY"] = ":99"

async def main():
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]

    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--enable-features=TrustTokens",
                "--enable-features=PrivateStateTokens",
                "--tpm-based-crypto=enabled",
            ]
        )
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await ctx.new_page()
        await Stealth().apply_stealth_async(page)
        await ctx.add_cookies(cookies)
        page.set_default_timeout(60000)

        captured_vars = None
        async def on_req(req):
            nonlocal captured_vars
            if "billing/graphql" in req.url and req.method == "POST":
                post = req.post_data or ""
                if "card_data" in post:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(post)
                    if "variables" in parsed:
                        captured_vars = json.loads(parsed["variables"][0])
        page.on("request", on_req)

        # Load billing
        print("[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        if "not available" in body.lower():
            print("  ❌ Geo-blocked"); await browser.close(); return

        # Dismiss
        for _ in range(5):
            els = await page.evaluate("""Array.from(document.querySelectorAll('*')).filter(el => el.innerText?.trim() === 'Continue' && el.offsetParent !== null && el.getBoundingClientRect().height > 20).map(el => ({r: el.getBoundingClientRect()}))""")
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x']+e['width']/2, e['y']+e['height']/2)
                await asyncio.sleep(2)
            else: break

        # Check Trust Token API
        trust = await page.evaluate("""
            async () => ({
                hasTrustToken: typeof document.hasTrustToken === 'function',
                hasPrivateStateToken: typeof document.hasPrivateStateToken === 'function',
                hasCrypto: typeof crypto?.subtle !== 'undefined',
                cryptoKeys: typeof crypto?.subtle !== 'undefined' ? Object.getOwnPropertyNames(Object.getPrototypeOf(crypto.subtle)).filter(k => k.includes('Key') || k.includes('key')) : [],
            })
        """)
        print(f"  Trust: {json.dumps(trust)}")

        # Add payment
        print("\n[2] Add payment...")
        btn = await page.query_selector(':is(button, [role="button"]):has-text("Add payment method")')
        if btn:
            await btn.click()
            await asyncio.sleep(5)

        # Fill card
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
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
        captured_vars = None
        btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if btn: await btn.click(force=True)
        await asyncio.sleep(10)

        if captured_vars:
            ptt = captured_vars.get("input", {}).get("platform_trust_token", "")
            cnum = captured_vars.get("input", {}).get("card_data", {}).get("credit_card_number", {})
            print(f"\n  === REQUEST ===")
            print(f"  platform_trust_token ({len(ptt)} chars): {ptt[:100]}...")
            print(f"  card_number: {json.dumps(cnum)}")
            
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
                                print(f"  Trust token signatures: {len(sigs)}")
                                if sigs:
                                    print(f"  ✅ HAS SIGNATURES!")
                                else:
                                    print(f"  ❌ Empty signatures")
                                break
                except Exception as e:
                    print(f"  Decode error: {e}")

        body = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" in body: print("  ❌ Card rejected")
        elif "Temporarily Blocked" in body: print("  ❌ Rate limited")

        await page.screenshot(path="data/screenshots/chrome_tpm.png")
        print("\n[DONE]")
        await browser.close()

asyncio.run(main())
