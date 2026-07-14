"""Find and call Meta's e2ee encryption DIRECTLY in page context."""
import asyncio, json, os, sys
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

        # Load billing page
        print("[1] Load billing...")
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

        btn = await page.wait_for_selector(':is(button, [role="button"]):has-text("Add payment method")', timeout=15000)
        await btn.click()
        await asyncio.sleep(5)

        # Try to find e2ee module via Meta's module system
        print("\n[2] Find e2ee module...")
        
        # Meta uses __d for define, but loading is via require()
        # Let's check what modules are available
        modules = await page.evaluate("""
            () => {
                const out = {};
                // Check __d (define)
                out.hasDefine = typeof __d === 'function';
                // Check require
                out.hasRequire = typeof require === 'function';
                // Check Relay
                out.hasRelay = typeof RelayDefaultEnv !== 'undefined';
                // Check for any billing-related globals
                const billing = [];
                for (const key of Object.getOwnPropertyNames(window)) {
                    if (key.toLowerCase().includes('billing') || key.toLowerCase().includes('e2ee') || 
                        key.toLowerCase().includes('protected') || key.toLowerCase().includes('encrypt')) {
                        billing.push(key);
                    }
                }
                out.billingGlobals = billing;
                return out;
            }
        """)
        print(f"  Modules: {json.dumps(modules)}")

        # Try to load BillingProtectedString via require
        result = await page.evaluate("""
            () => {
                const out = {};
                // Try require with various module names
                const names = [
                    'BillingProtectedString',
                    'BillingAddCreditCardFormUtils',
                    'BillingCreditCardNumber',
                    'BillingE2EE',
                    'E2EEManager',
                    'BillingEncryption',
                ];
                for (const name of names) {
                    try {
                        const mod = require(name);
                        out[name] = {
                            type: typeof mod,
                            keys: Object.keys(mod).slice(0, 20),
                            values: Object.entries(mod).slice(0, 5).map(([k, v]) => [k, typeof v])
                        };
                    } catch(e) {
                        out[name] = {error: e.message?.substring(0, 80)};
                    }
                }
                return out;
            }
        """)
        print(f"  Module loads: {json.dumps(result, indent=2)}")

        # If BillingProtectedString loads, check its internals
        if 'error' not in result.get('BillingProtectedString', {}):
            detail = await page.evaluate("""
                () => {
                    try {
                        const mod = require('BillingProtectedString');
                        return Object.entries(mod).map(([k, v]) => {
                            if (typeof v === 'function') {
                                return [k, v.toString().substring(0, 200)];
                            }
                            return [k, String(v).substring(0, 100)];
                        });
                    } catch(e) { return [['error', e.message]]; }
                }
            """)
            print(f"  BillingProtectedString details: {json.dumps(detail, indent=2)}")

        # Try to find the encryption key fetch and encryption flow
        print("\n[3] Check billing GraphQL handler...")
        handler = await page.evaluate("""
            () => {
                try {
                    // Try to find Relay environment
                    const relayEnv = document.querySelector('[data-content]');
                    // Try to find the billing form's React fiber
                    const form = document.querySelector('input[name="cardNumber"]');
                    if (!form) return {error: 'no card input'};
                    
                    // Walk React fiber tree
                    const key = Object.keys(form).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    if (!key) return {error: 'no react fiber'};
                    
                    let fiber = form[key];
                    const components = [];
                    let depth = 0;
                    while (fiber && depth < 30) {
                        if (fiber.type && fiber.type.displayName) {
                            components.push(fiber.type.displayName);
                        }
                        if (fiber.memoizedProps) {
                            const propKeys = Object.keys(fiber.memoizedProps);
                            if (propKeys.some(k => k.includes('encrypt') || k.includes('e2ee') || k.includes('protected'))) {
                                return {
                                    component: fiber.type?.displayName,
                                    props: propKeys.filter(k => k.includes('encrypt') || k.includes('e2ee') || k.includes('protected')),
                                };
                            }
                        }
                        fiber = fiber.return;
                        depth++;
                    }
                    return {components: components.slice(0, 15)};
                } catch(e) { return {error: e.message}; }
            }
        """)
        print(f"  React fiber: {json.dumps(handler, indent=2)}")

        print("\n[DONE]")

asyncio.run(main())
