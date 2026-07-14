#!/usr/bin/env python3
"""Inject session cookies → billing → add card → create API key."""
import asyncio, json, os, sys
from datetime import datetime

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_card, generate_us_address

async def main():
    from camoufox.async_api import AsyncCamoufox

    # Load existing account
    with open("data/output/accounts_20260714_114223_full.json") as f:
        data = json.load(f)
    acc = data[0]
    print(f"Account: {acc['email']} ({acc['first_name']} {acc['last_name']})")

    # Build cookies
    cookie_dict = acc["cookies"]
    domain_map = {
        "datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com",
        "locale": ".auth.meta.com", "ig_did": ".instagram.com", "llm_sess": ".meta.ai",
        "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com",
        "fr": ".facebook.com", "sb": ".facebook.com",
    }
    cookies = []
    for name, value in cookie_dict.items():
        cookies.append({
            "name": name, "value": value,
            "domain": domain_map.get(name, ".meta.ai"),
            "path": "/", "secure": True, "httpOnly": False
        })

    card = generate_card("visa")
    addr = generate_us_address()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Card: {card['formatted']} | Exp: {card['expiry']} | CVV: {card['cvv']}")

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()
        page.set_default_timeout(60000)

        # ── 1. DEV.META.AI ──
        print("\n[1] dev.meta.ai...")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss welcome modal
        for _ in range(5):
            els = await page.evaluate("""
                Array.from(document.querySelectorAll('*')).filter(el => {
                    return el.innerText?.trim() === 'Continue' && el.offsetParent !== null &&
                           el.getBoundingClientRect().height > 20 && el.getBoundingClientRect().width > 40;
                }).map(el => ({ r: el.getBoundingClientRect() }))
            """)
            if els:
                e = els[0]['r']
                await page.mouse.click(e['x'] + e['width']/2, e['y'] + e['height']/2)
                await asyncio.sleep(2)
            else: break

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  OK: {'Dashboard' in body or 'Playground' in body}")
        print(f"  URL: {page.url}")

        # ── 2. BILLING ──
        print("\n[2] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        final_url = page.url
        print(f"  URL: {final_url}")

        # Dismiss modal
        for _ in range(3):
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

        body = await page.evaluate("document.body?.innerText || ''")
        has_payment = "No payment method" in body
        print(f"  Needs payment: {has_payment}")

        # ── 3. ADD CARD ──
        print("\n[3] Add card...")
        try:
            add_btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
            await add_btn.click()
            await asyncio.sleep(4)
        except Exception as e:
            print(f"  No button: {e}")

        # Fill card
        for name, val in [("firstName", f"{acc['first_name']} {acc['last_name']}")]:
            el = await page.query_selector(f'input[name="{name}"]')
            if el: await el.click(); await el.fill(""); await el.type(val, delay=30)

        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in card["number"]: await page.keyboard.type(ch, delay=40)

        el = await page.query_selector('input[name="expiration"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in card["expiry"]: await page.keyboard.type(ch, delay=60)

        el = await page.query_selector('input[name="securityCode"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in card["cvv"]: await page.keyboard.type(ch, delay=60)

        # ZIP
        await page.evaluate(f"""() => {{
            for (const inp of document.querySelectorAll('input')) {{
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {{
                    if (!inp.value) {{
                        inp.value = '{addr["zip"]}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            }}
        }}""")
        await asyncio.sleep(1)

        # Submit card
        print("  Submitting...")
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        body = await page.evaluate("document.body?.innerText || ''")
        if "Couldn't save" in body:
            print("  ❌ Card rejected (trust_token issue)")
        elif "Temporarily Blocked" in body:
            print("  ❌ Rate limited")
        elif "Card details" not in body:
            print("  ✅ Card accepted!")
        else:
            print(f"  ? Unknown: {body[:100]}")

        await page.screenshot(path=f"data/screenshots/inject_billing_{ts}.png")

        # ── 4. API KEY ──
        print("\n[4] API keys...")
        await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss modal
        for _ in range(3):
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

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  {body[:200]}")

        # Try Create API key
        create_btn = await page.query_selector(':is(button, [role="button"]):has-text("Create API key")')
        if create_btn:
            disabled = await create_btn.is_disabled()
            print(f"  Create button: disabled={disabled}")
            if not disabled:
                await create_btn.click(force=True)
                await asyncio.sleep(3)
                name_input = await page.query_selector('input[type="text"]')
                if name_input:
                    await name_input.fill("default")
                    submit = await page.query_selector(':is(button, [role="button"]):has-text("Create")')
                    if submit:
                        await submit.click(force=True)
                        await asyncio.sleep(5)
                body = await page.evaluate("document.body?.innerText || ''")
                print(f"  Result: {body[:500]}")
        else:
            print("  No Create API key button (needs payment first)")

        await page.screenshot(path=f"data/screenshots/inject_apikey_{ts}.png")

        # ── 5. Save ──
        all_cookies = await context.cookies()
        out_cookies = {}
        for c in all_cookies:
            if c['name'] in ['datr', 'ps_l', 'ps_n', 'llm_sess', 'locale', 'fs', 'wd', 'fr', 'sb', 'c_user']:
                out_cookies[c['name']] = c['value']

        output = {
            "email": acc['email'], "password": acc['password'],
            "first_name": acc['first_name'], "last_name": acc['last_name'],
            "cookies": out_cookies,
            "billing_url": final_url,
            "timestamp": datetime.now().isoformat(),
        }
        with open(f"data/output/inject_{ts}.json", "w") as f:
            json.dump(output, f, indent=2)

        print(f"\n[DONE]")

asyncio.run(main())
