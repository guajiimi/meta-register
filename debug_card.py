#!/usr/bin/env python3
"""Debug: inspect all input fields on billing card form."""
import asyncio, json, os, sys
from datetime import datetime

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")
from card_gen import generate_us_address

async def main():
    from camoufox.async_api import AsyncCamoufox

    with open("data/output/accounts_20260714_114223_full.json") as f:
        data = json.load(f)
    account = data[0]
    cookie_dict = account["cookies"]

    cookies = []
    domain_map = {
        "datr": ".auth.meta.com", "fs": ".auth.meta.com", "dbln": ".auth.meta.com",
        "locale": ".auth.meta.com", "ig_did": ".instagram.com", "llm_sess": ".meta.ai",
        "ps_l": ".auth.meta.com", "ps_n": ".auth.meta.com", "wd": ".auth.meta.com",
        "fr": ".facebook.com", "sb": ".facebook.com",
    }
    for name, value in cookie_dict.items():
        cookies.append({"name": name, "value": value, "domain": domain_map.get(name, ".meta.ai"), "path": "/", "secure": True, "httpOnly": False})

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Intercept API calls
        async def on_resp(resp):
            u = resp.url
            if ("graphql" in u or "billing" in u or "payment" in u or "stripe" in u) and "pixel" not in u:
                try:
                    body = await resp.text()
                    print(f"  API [{resp.status}]: {u[:120]}")
                    print(f"    Body: {body[:500]}")
                except:
                    print(f"  API [{resp.status}]: {u[:120]}")
        page.on("response", on_resp)

        # Navigate
        print("[1] dev.meta.ai...")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=10000)
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
            else:
                break

        print("[2] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=10000)
        except: pass
        await asyncio.sleep(3)
        print(f"  URL: {page.url}")

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
            else:
                break

        print("[3] Add payment method...")
        try:
            btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
            await btn.click()
            await asyncio.sleep(4)
        except Exception as e:
            print(f"  Error: {e}")

        # DEBUG: List ALL input fields
        print("\n[DEBUG] All input/select fields:")
        fields = await page.evaluate("""
            Array.from(document.querySelectorAll('input, select, textarea')).map(el => ({
                tag: el.tagName,
                type: el.type,
                name: el.name,
                id: el.id,
                placeholder: el.placeholder,
                value: el.value,
                ariaLabel: el.getAttribute('aria-label'),
                className: el.className?.substring(0, 80),
                visible: el.offsetParent !== null,
            }))
        """)
        for f in fields:
            if f['visible']:
                print(f"  {f['tag']} name={f['name']} id={f['id']} type={f['type']} placeholder={f['placeholder']} value={f['value'][:30]} aria={f['ariaLabel']}")

        # Fill card
        addr = generate_us_address()
        card_name = f"{account['first_name']} {account['last_name']}"
        
        print(f"\n[4] Filling card: 488950****8307")
        
        # Fill each field explicitly
        for field_info in fields:
            if not field_info['visible']:
                continue
            name = field_info['name']
            if name == 'firstName':
                el = await page.query_selector(f'input[name="{name}"]')
                if el:
                    await el.click(); await el.fill("")
                    await el.type(card_name, delay=30)
                    print(f"  ✓ firstName: {card_name}")
            elif name == 'cardNumber':
                el = await page.query_selector(f'input[name="{name}"]')
                if el:
                    await el.click(); await el.fill("")
                    for ch in "4889501032758307":
                        await page.keyboard.type(ch, delay=40)
                    print(f"  ✓ cardNumber: 488950****8307")
            elif name == 'expiration':
                el = await page.query_selector(f'input[name="{name}"]')
                if el:
                    await el.click(); await asyncio.sleep(0.2)
                    for ch in "08/27":
                        await page.keyboard.type(ch, delay=60)
                    print(f"  ✓ expiration: 08/27")
            elif name == 'securityCode':
                el = await page.query_selector(f'input[name="{name}"]')
                if el:
                    await el.click(); await asyncio.sleep(0.2)
                    for ch in "424":
                        await page.keyboard.type(ch, delay=60)
                    print(f"  ✓ securityCode: 424")
            elif name in ('postalCode', 'zip', 'postal_code', 'zipcode'):
                el = await page.query_selector(f'input[name="{name}"]')
                if el:
                    v = await el.input_value()
                    if not v:
                        await el.click(); await el.fill(addr['zip'])
                        print(f"  ✓ {name}: {addr['zip']}")
                    else:
                        print(f"  = {name}: {v} (already filled)")

        # Check for ZIP by aria-label or placeholder
        zip_el = await page.query_selector('input[aria-label*="ZIP" i], input[placeholder*="ZIP" i], input[aria-label*="postal" i], input[placeholder*="postal" i]')
        if zip_el:
            v = await zip_el.input_value()
            if not v:
                await zip_el.click(); await zip_el.fill(addr['zip'])
                print(f"  ✓ ZIP (aria/placeholder): {addr['zip']}")
            else:
                print(f"  = ZIP: {v} (already filled)")

        # Also try by nearby text
        zip_filled = await page.evaluate(f"""
            () => {{
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    const label = inp.closest('label')?.innerText || '';
                    const parent = inp.parentElement?.innerText || '';
                    if ((label + parent).toLowerCase().includes('zip') || (label + parent).toLowerCase().includes('postal')) {{
                        if (!inp.value) {{
                            inp.value = '{addr["zip"]}';
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return 'filled: ' + inp.name;
                        }}
                        return 'already: ' + inp.value;
                    }}
                }}
                return 'not found';
            }}
        """)
        print(f"  ZIP by text: {zip_filled}")

        await asyncio.sleep(1)
        await page.screenshot(path="data/screenshots/debug_filled.png")

        # Re-check fields after filling
        print("\n[DEBUG] Fields after filling:")
        fields2 = await page.evaluate("""
            Array.from(document.querySelectorAll('input')).filter(el => el.offsetParent !== null).map(el => ({
                name: el.name, value: el.value, placeholder: el.placeholder
            }))
        """)
        for f in fields2:
            print(f"  {f['name']}: '{f['value']}' (placeholder: {f['placeholder']})")

        # Submit
        print("\n[5] Submit...")
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn:
            await next_btn.click(force=True)
            for i in range(15):
                await asyncio.sleep(1)
                body = await page.evaluate("document.body?.innerText || ''")
                if "Couldn't save" in body:
                    # Get error details
                    err = await page.evaluate("""
                        () => {
                            const els = document.querySelectorAll('[role="alert"], .error, [class*="error"], [class*="Error"]');
                            return Array.from(els).map(e => e.innerText).filter(t => t.length > 0).join(' | ');
                        }
                    """)
                    print(f"  ❌ REJECTED (detail: {err})")
                    break
                elif "Temporarily Blocked" in body:
                    print("  ❌ RATE LIMITED")
                    break

        await page.screenshot(path="data/screenshots/debug_result.png")
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"\n[6] Final:\n{body[:500]}")
        print("\n[DONE]")

asyncio.run(main())
