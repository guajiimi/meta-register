#!/usr/bin/env python3
"""Find ALL requests during billing page load — look for e2ee key exchange."""
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

        # Track ALL requests/responses
        all_reqs = []
        async def on_req(req):
            all_reqs.append({"method": req.method, "url": req.url[:200], "type": req.resource_type})
        page.on("request", on_req)

        all_resps = []
        async def on_resp(resp):
            if resp.status == 200 and resp.url.startswith("https://"):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct or "javascript" in ct:
                        body = await resp.text()
                        if any(k in body.lower() for k in ["e2ee", "encrypt", "sensitive", "trust_token", "platform_trust"]):
                            all_resps.append({"url": resp.url[:200], "body": body[:500]})
                except: pass
        page.on("response", on_resp)

        # Go to billing
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

        # Click add payment
        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        
        # Clear and start fresh tracking
        all_reqs.clear()
        all_resps.clear()
        
        await btn.click()
        await asyncio.sleep(5)

        print(f"=== Requests after 'Add payment' click: {len(all_reqs)} ===")
        for r in all_reqs:
            url = r['url']
            # Filter interesting ones
            if any(k in url for k in ["graphql", "e2ee", "encrypt", "key", "trust", "billing", "payment"]):
                print(f"  {r['method']} [{r['type']}] {url}")

        print(f"\n=== Responses with e2ee/encrypt/trust/sensitive: {len(all_resps)} ===")
        for r in all_resps:
            print(f"  URL: {r['url']}")
            print(f"  Body: {r['body'][:300]}")
            print()

        # Also search JS bundles for e2ee module
        print("\n=== Searching page scripts for e2ee ===")
        e2ee_info = await page.evaluate("""
            () => {
                // Check for e2ee-related globals
                const globals = {};
                for (const key of Object.getOwnPropertyNames(window)) {
                    try {
                        const v = window[key];
                        if (typeof v === 'function') {
                            const src = v.toString().substring(0, 200);
                            if (src.includes('e2ee') || src.includes('encrypt') || src.includes('sensitive_string')) {
                                globals[key] = src.substring(0, 100);
                            }
                        } else if (typeof v === 'object' && v !== null) {
                            const keys = Object.keys(v).join(',');
                            if (keys.includes('e2ee') || keys.includes('encrypt') || keys.includes('sensitive')) {
                                globals[key] = keys.substring(0, 100);
                            }
                        }
                    } catch(e) {}
                }
                
                // Check for SENSITIVE_STRING_VALUE pattern
                const body = document.body.innerHTML;
                const sensitiveIdx = body.indexOf('sensitive_string_value');
                const e2eeIdx = body.indexOf('$e2ee');
                
                return {globals, sensitiveIdx, e2eeIdx, bodyLen: body.length};
            }
        """)
        print(f"  Crypto globals: {json.dumps(e2ee_info['globals'], indent=2)}")
        print(f"  'sensitive_string_value' in DOM: {e2ee_info['sensitiveIdx']}")
        print(f"  '$e2ee' in DOM: {e2ee_info['e2eeIdx']}")

        print("\n[DONE]")

asyncio.run(main())
