#!/usr/bin/env python3
"""Add card with multiple browser strategies."""
import asyncio, json, os, sys
from datetime import datetime

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/root/meta-register")

REAL_CARD = "4889501032758307"
REAL_EXP = "08/27"
REAL_CVV = "424"

async def try_camoufox_nonvirtual():
    """Camoufox non-virtual (real headed)"""
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

    print("=== Strategy: Camoufox headed (non-virtual) ===")
    async with AsyncCamoufox(headless=False, humanize=True, block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Capture billing request/response
        billing_result = {}
        async def on_resp(resp):
            if "billing/graphql" in resp.url:
                try:
                    body = await resp.text()
                    if "save_credit_card" in body:
                        billing_result["body"] = body
                except: pass
        page.on("response", on_resp)

        # Billing page
        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss modal
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

        # Add payment
        try:
            btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
            await btn.click()
            await asyncio.sleep(4)
        except Exception as e:
            print(f"  No button: {e}")
            return False

        # Check trust token
        trust = await page.evaluate("""
            async () => {
                return {
                    hasTrustToken: typeof document.hasTrustToken === 'function',
                    hasPrivateStateToken: typeof document.hasPrivateStateToken === 'function',
                    hasCrypto: typeof crypto?.subtle !== 'undefined',
                }
            }
        """)
        print(f"  Trust: {json.dumps(trust)}")

        # Fill card
        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)

        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in REAL_CARD: await page.keyboard.type(ch, delay=40)

        el = await page.query_selector('input[name="expiration"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in REAL_EXP: await page.keyboard.type(ch, delay=60)

        el = await page.query_selector('input[name="securityCode"]')
        if el:
            await el.click(); await asyncio.sleep(0.2)
            for ch in REAL_CVV: await page.keyboard.type(ch, delay=60)

        # ZIP
        await page.evaluate("""() => {
            for (const inp of document.querySelectorAll('input')) {
                const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {
                    if (!inp.value) {
                        inp.value = '90001';
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }
            }
        }""")
        await asyncio.sleep(1)

        # Submit
        billing_result.clear()
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn: await next_btn.click(force=True)
        await asyncio.sleep(10)

        # Check result
        if billing_result.get("body"):
            body = billing_result["body"]
            if body.startswith("for (;;);"): body = body[len("for (;;);"):]
            try:
                d = json.loads(body)
                r = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
                print(f"  Result: {r.get('status')} | error_code: {r.get('error_code')}")
                cc = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("credit_card")
                if cc:
                    print(f"  ✅ CARD SAVED!")
                    return True
                print(f"  ❌ {r.get('message')}")
            except: pass
        else:
            body = await page.evaluate("document.body?.innerText || ''")
            print(f"  Page: {body[:200]}")

        await page.screenshot(path="data/screenshots/strategy_headed.png")
        return False


async def try_with_e2ee_intercept():
    """Intercept e2ee key fetch and manually encrypt card."""
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

    print("\n=== Strategy: Intercept e2ee flow ===")
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Track ALL requests to find e2ee key exchange
        e2ee_requests = []
        async def on_req(req):
            url = req.url
            if "e2ee" in url.lower() or "encrypt" in url.lower() or "key" in url.lower():
                e2ee_requests.append({"url": url[:200], "method": req.method})
            if "billing/graphql" in url and req.method == "POST":
                e2ee_requests.append({"url": "BILLING_GRAPHQL", "post": req.post_data[:500] if req.post_data else ""})
        page.on("request", on_req)

        e2ee_responses = []
        async def on_resp(resp):
            url = resp.url
            if "e2ee" in url.lower() or "encrypt" in url.lower() or "key" in url.lower():
                try:
                    body = await resp.text()
                    e2ee_responses.append({"url": url[:200], "body": body[:500]})
                except: pass
        page.on("response", on_resp)

        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        # Dismiss
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

        try:
            btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
            await btn.click()
            await asyncio.sleep(4)
        except:
            pass

        # Clear tracked requests, fill card, watch e2ee
        e2ee_requests.clear()
        e2ee_responses.clear()

        el = await page.query_selector('input[name="firstName"]')
        if el: await el.click(); await el.fill(""); await el.type(f"{acc['first_name']} {acc['last_name']}", delay=30)

        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click(); await el.fill("")
            for ch in REAL_CARD: await page.keyboard.type(ch, delay=50)
        
        await asyncio.sleep(3)

        print(f"  e2ee requests during card fill: {len(e2ee_requests)}")
        for r in e2ee_requests:
            print(f"    {r.get('method', '')} {r['url']}")
        print(f"  e2ee responses: {len(e2ee_responses)}")
        for r in e2ee_responses:
            print(f"    {r['url'][:100]}")
            print(f"    {r['body'][:200]}")

        # Check if e2ee module is loaded
        e2ee_module = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[src]');
                const scriptSrcs = Array.from(scripts).map(s => s.src);
                const e2eeScripts = scriptSrcs.filter(s => s.includes('e2ee') || s.includes('encrypt') || s.includes('sensitive'));
                
                // Check for any module that handles card encryption
                const modules = [];
                for (const key of Object.keys(window)) {
                    if (typeof window[key] === 'object' && window[key] !== null) {
                        try {
                            const str = JSON.stringify(Object.keys(window[key]));
                            if (str.includes('encrypt') || str.includes('e2ee') || str.includes('sensitive') || str.includes('card')) {
                                modules.push(key);
                            }
                        } catch(e) {}
                    }
                }
                
                return {e2eeScripts, modules, totalScripts: scriptSrcs.length};
            }
        """)
        print(f"\n  e2ee scripts: {e2ee_module['e2eeScripts']}")
        print(f"  crypto modules: {e2ee_module['modules']}")
        print(f"  total scripts: {e2ee_module['totalScripts']}")

        await page.screenshot(path="data/screenshots/e2ee_intercept.png")
        return False


async def main():
    # Strategy 1: Camoufox headed
    result = await try_camoufox_nonvirtual()
    if result:
        print("\n🎉 SUCCESS!")
        return
    
    # Strategy 2: Check e2ee flow
    await try_with_e2ee_intercept()
    
    print("\n❌ All strategies failed. Trust token issue persists.")

asyncio.run(main())
