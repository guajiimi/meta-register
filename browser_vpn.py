import asyncio, json, os, sys
os.environ["DISPLAY"] = ":99"
CARD = "4889501032758307"

async def main():
    from camoufox.async_api import AsyncCamoufox
    with open("data/output/accounts_20260714_114223_full.json") as f:
        acc = json.load(f)[0]
    
    domain_map = {"datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com", "locale": ".auth.meta.com", "llm_sess": ".meta.ai", "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com"}
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False} for n, v in acc["cookies"].items()]

    save_resp = {"body": None}

    async with AsyncCamoufox(headless=False, humanize=True, block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        async def on_resp(resp):
            try:
                body = await resp.text()
                if "save_credit_card" in body:
                    save_resp["body"] = body
            except: pass
        page.on("response", on_resp)

        print("[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  URL: {page.url[:80]}")
        print(f"  Body: {body[:200]}")

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

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  After dismiss: {body[:200]}")

        # Add payment
        print("\n[2] Add payment method...")
        btn = await page.query_selector(':is(button, [role="button"]):has-text("Add payment method")')
        if btn:
            await btn.click()
            await asyncio.sleep(5)
            print("  Clicked!")
        else:
            print("  ⚠ No button found")
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"  {body[:300]}")

        # Fill card
        print("\n[3] Fill card...")
        el = await page.query_selector('input[name="firstName"]')
        if el:
            await el.click(); await el.fill("")
            await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)
            print("  ✓ Name")
        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in CARD: await page.keyboard.type(ch, delay=50)
            print("  ✓ Card number")
        el = await page.query_selector('input[name="expiration"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in "08/27": await page.keyboard.type(ch, delay=60)
            print("  ✓ Expiry")
        el = await page.query_selector('input[name="securityCode"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in "424": await page.keyboard.type(ch, delay=60)
            print("  ✓ CVV")
        await page.evaluate("""() => {
            for (const inp of document.querySelectorAll('input')) {
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal'))
                    if (!inp.value) { inp.value = '90001'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
            }
        }""")
        print("  ✓ ZIP")
        await asyncio.sleep(1)

        # Submit
        print("\n[4] Submit...")
        save_resp["body"] = None
        btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if btn:
            await btn.click(force=True)
            print("  Clicked Next!")
        await asyncio.sleep(10)

        if save_resp["body"]:
            raw = save_resp["body"]
            if raw.startswith("for (;;);"): raw = raw[10:]
            d = json.loads(raw)
            r = d["data"]["xfb_billing_save_credit_card"]["client_result"]
            cc = d["data"]["xfb_billing_save_credit_card"].get("credit_card")
            print(f"\n  === RESULT ===")
            print(f"  Status: {r['status']}")
            print(f"  Error: {r.get('error_code')}")
            if cc:
                print(f"  ✅ CARD SAVED!")
            else:
                print(f"  ❌ {r.get('message')}")
        else:
            body = await page.evaluate("document.body?.innerText || ''")
            if "Couldn't save" in body: print("  ❌ Card rejected")
            elif "Temporarily Blocked" in body: print("  ❌ Rate limited")
            else: print(f"  Page: {body[:300]}")

        await page.screenshot(path="data/screenshots/browser_vpn.png")
        print("\n[DONE]")

asyncio.run(main())
