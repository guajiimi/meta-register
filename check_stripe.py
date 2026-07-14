#!/usr/bin/env python3
"""Check if Stripe.js is loaded and card tokenization happens."""
import asyncio, json, os, sys

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")

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

        # Track ALL network requests
        all_reqs = []
        async def on_req(req):
            url = req.url
            if any(k in url for k in ["stripe", "token", "payment", "card", "billing"]):
                post = req.post_data or ""
                all_reqs.append({"method": req.method, "url": url[:200], "post": post[:500]})
        page.on("request", on_req)

        all_resps = []
        async def on_resp(resp):
            url = resp.url
            if any(k in url for k in ["stripe", "token", "payment", "card", "billing"]):
                try:
                    body = await resp.text()
                    all_resps.append({"url": url[:200], "status": resp.status, "body": body[:500]})
                except: pass
        page.on("response", on_resp)

        print("[1] Billing...")
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
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
            else: break

        print("[2] Add payment method...")
        btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Check for Stripe/iframe/iframes
        print("\n[3] Check iframes & scripts...")
        iframes = await page.evaluate("""
            () => {
                const frames = document.querySelectorAll('iframe');
                return Array.from(frames).map(f => ({
                    src: f.src?.substring(0, 200),
                    name: f.name,
                    id: f.id,
                    title: f.title,
                }));
            }
        """)
        print(f"  iframes: {len(iframes)}")
        for f in iframes:
            print(f"    {f}")

        # Check for Stripe.js
        stripe_check = await page.evaluate("""
            () => {
                return {
                    hasStripe: typeof Stripe !== 'undefined',
                    hasStripeElements: typeof StripeElements !== 'undefined',
                    stripeVersion: typeof Stripe !== 'undefined' ? Stripe.version : null,
                    hasReactStripe: typeof window.__stripe !== 'undefined',
                }
            }
        """)
        print(f"  Stripe: {stripe_check}")

        # Check for __stripe_js, payment_element, etc.
        scripts = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[src]');
                return Array.from(scripts).map(s => s.src).filter(s => 
                    s.includes('stripe') || s.includes('payment') || s.includes('braintree') || s.includes('adyen')
                );
            }
        """)
        print(f"  Payment scripts: {scripts}")

        # Check input fields - are they in iframe?
        input_info = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input');
                return Array.from(inputs).filter(i => i.offsetParent !== null).map(i => {
                    const rect = i.getBoundingClientRect();
                    return {
                        name: i.name,
                        type: i.type,
                        placeholder: i.placeholder,
                        inIframe: window.self !== window.top,
                        rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
                        autocomplete: i.autocomplete,
                    };
                });
            }
        """)
        print(f"\n  Visible inputs: {len(input_info)}")
        for inp in input_info:
            print(f"    {inp['name']} type={inp['type']} ac={inp['autocomplete']} rect={inp['rect']}")

        # Track requests during card fill
        all_reqs.clear()
        all_resps.clear()

        print("\n[4] Fill card number (watching network)...")
        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in "4867841205316251":
                await page.keyboard.type(ch, delay=50)
        
        await asyncio.sleep(3)
        
        if all_reqs:
            print("  Requests during card fill:")
            for r in all_reqs:
                print(f"    {r['method']} {r['url']}")
                if r['post']: print(f"      {r['post'][:200]}")
        else:
            print("  No network requests during card fill")

        # Fill rest
        el = await page.query_selector('input[name="expiration"]')
        if el: await el.click(); await asyncio.sleep(0.2); 
        for ch in "11/27": await page.keyboard.type(ch, delay=60)

        el = await page.query_selector('input[name="securityCode"]')
        if el: await el.click(); await asyncio.sleep(0.2)
        for ch in "267": await page.keyboard.type(ch, delay=60)

        # ZIP
        await page.evaluate("""() => {
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {
                const label = inp.closest('label')?.innerText || '';
                const parent = inp.parentElement?.innerText || '';
                if ((label + parent).toLowerCase().includes('zip') || (label + parent).toLowerCase().includes('postal')) {
                    if (!inp.value) {
                        inp.value = '90001';
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }
            }
        }""")

        await asyncio.sleep(1)

        # Now check all requests/responses
        print(f"\n[5] All tracked requests: {len(all_reqs)}")
        for r in all_reqs:
            print(f"  {r['method']} {r['url'][:150]}")
        print(f"  All tracked responses: {len(all_resps)}")
        for r in all_resps:
            print(f"  [{r['status']}] {r['url'][:150]}")

        # Submit
        all_reqs.clear()
        all_resps.clear()
        print("\n[6] Submit...")
        next_btn = await page.query_selector('button:has-text("Next")')
        if next_btn: await next_btn.click(force=True)

        await asyncio.sleep(5)
        print(f"  Requests: {len(all_reqs)}")
        for r in all_reqs:
            print(f"  {r['method']} {r['url'][:150]}")
            if r['post']: print(f"    Post: {r['post'][:300]}")
        print(f"  Responses: {len(all_resps)}")
        for r in all_resps:
            print(f"  [{r['status']}] {r['url'][:150]}")
            print(f"    Body: {r['body'][:300]}")

        await page.screenshot(path="data/screenshots/stripe_check.png")
        print("\n[DONE]")

asyncio.run(main())
