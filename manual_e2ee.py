#!/usr/bin/env python3
"""Intercept billing request, find e2ee public key, encrypt card manually."""
import asyncio, json, os, sys, urllib.parse, base64

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

    # Track all graphql requests and find e2ee key
    all_graphql = []
    e2ee_key_data = None
    
    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

        # Intercept all responses for e2ee key
        async def on_resp(resp):
            global e2ee_key_data
            url = resp.url
            try:
                body = await resp.text()
                # Look for e2ee key in any response
                if 'publicKey' in body or 'public_key' in body or 'e2eeKey' in body:
                    e2ee_key_data = {"url": url[:200], "body": body[:1000]}
                    print(f"[E2EE KEY FOUND] {url[:100]}")
                    print(f"  {body[:300]}")
                if 'e2eePublicKey' in body or 'E2EEPublicKey' in body:
                    e2ee_key_data = {"url": url[:200], "body": body[:1000]}
                    print(f"[E2EE PUBKEY] {url[:100]}")
                # Check graphql responses for e2ee key
                if 'graphql' in url and ('e2ee' in body.lower() or 'encrypt' in body.lower() or 'public_key' in body.lower()):
                    print(f"[GRAPHQL E2EE] {url[:100]}")
                    print(f"  {body[:500]}")
            except: pass
        page.on("response", on_resp)

        # Also intercept the request and MODIFY it
        intercepted = []
        async def intercept_route(route):
            req = route.request
            if "billing/graphql" in req.url and req.method == "POST":
                body = req.post_data or ""
                if "card_data" in body and "$e2ee" in body:
                    intercepted.append(body)
                    print(f"\n[INTERCEPTED] $e2ee in request!")
                    # Don't continue yet - we'll try to fix it
                    # For now, just log and continue
                    await route.continue_()
                else:
                    await route.continue_()
            else:
                await route.continue_()
        
        await page.route("**/billing/graphql/**", intercept_route)

        await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

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

        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Search for e2ee key in page's global state
        key_search = await page.evaluate("""
            () => {
                const out = {};
                
                // Search for e2ee public key in server-side rendered data
                const scripts = document.querySelectorAll('script:not([src])');
                for (const s of scripts) {
                    const t = s.textContent;
                    // Look for base64-encoded RSA public key near e2ee
                    const patterns = [
                        /e2ee.*?([A-Za-z0-9+/]{100,}={0,2})/i,
                        /public[_]?key.*?([A-Za-z0-9+/]{100,}={0,2})/i,
                        /-----BEGIN PUBLIC KEY-----(.+?)-----END PUBLIC KEY-----/s,
                        /([A-Za-z0-9+/]{200,}={0,2})/g,
                    ];
                    for (const p of patterns) {
                        const m = t.match(p);
                        if (m) {
                            out.pattern = p.toString();
                            out.match = m[1]?.substring(0, 100);
                            out.context = t.substring(Math.max(0, m.index - 50), m.index + m[0].length + 50).substring(0, 200);
                            break;
                        }
                    }
                }
                
                // Check __comet_req data for e2ee key
                try {
                    const csr = document.querySelector('[data-content-len]');
                    if (csr) out.hasCSR = true;
                } catch(e) {}
                
                // Search for Relay store data
                try {
                    // Meta stores data in Relay environment
                    const relayEnv = document.querySelector('#__relay_data__');
                    if (relayEnv) out.hasRelayData = true;
                } catch(e) {}
                
                return out;
            }
        """)
        print(f"\nKey search: {json.dumps(key_search, indent=2)}")

        # Try the fetch API to get e2ee key directly
        e2ee_fetch = await page.evaluate("""
            async () => {
                try {
                    // Try to fetch e2ee public key from Meta's API
                    const urls = [
                        '/api/billing/e2ee_public_key/',
                        '/api/e2ee/public_key/',
                        '/api/graphql/',
                    ];
                    const results = [];
                    for (const url of urls) {
                        try {
                            const r = await fetch(url, {
                                method: 'POST',
                                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                                body: 'doc_id=0&query_name=BillingE2EEPublicKeyQuery'
                            });
                            const text = await r.text();
                            results.push({url, status: r.status, body: text.substring(0, 300)});
                        } catch(e) {
                            results.push({url, error: e.message});
                        }
                    }
                    return results;
                } catch(e) {
                    return [{error: e.message}];
                }
            }
        """)
        print(f"\nE2EE API fetch: {json.dumps(e2ee_fetch, indent=2)}")

        print(f"\nIntercepted requests: {len(intercepted)}")
        print(f"E2EE key data: {json.dumps(e2ee_key_data, indent=2) if e2ee_key_data else 'None'}")

asyncio.run(main())
