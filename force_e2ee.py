#!/usr/bin/env python3
"""Find e2ee encryption key and force encrypt card data before submit."""
import asyncio, json, os, sys, urllib.parse

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
    cookies = [{"name": n, "value": v, "domain": domain_map.get(n, ".meta.ai"), "path": "/", "secure": True, "httpOnly":False}
               for n, v in acc["cookies"].items()]

    async with AsyncCamoufox(headless="virtual", humanize=True, os="windows", block_webrtc=True) as browser:
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(60000)

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

        # Find the e2ee public key from Meta's JS modules
        e2ee_info = await page.evaluate("""
            () => {
                const out = {};
                
                // Search all script tags for e2ee key
                const scripts = document.querySelectorAll('script:not([src])');
                for (const s of scripts) {
                    const t = s.textContent;
                    if (t.includes('e2ee') || t.includes('E2EE') || t.includes('publicKey') || t.includes('public_key')) {
                        // Find key patterns
                        const keyMatch = t.match(/(?:public_?key|publicKey|encryption_?key)["'\s:=]+["']([A-Za-z0-9+/=]{50,})["']/i);
                        if (keyMatch) out.foundKey = keyMatch[1].substring(0, 100);
                        
                        const e2eeMatch = t.match(/e2ee[^;]{0,200}/i);
                        if (e2eeMatch) out.e2eeContext = e2eeMatch[0];
                    }
                }
                
                // Search for e2ee in loaded JS modules (via __d defines)
                // Try to find BillingProtectedString implementation
                try {
                    // Meta's module system stores in __d buffer
                    const mods = [];
                    const origDefine = window.__d;
                    if (origDefine) {
                        out.hasModuleSystem = true;
                    }
                } catch(e) {}
                
                // Check for fetch/XHR hooks that might handle e2ee
                out.fetchType = typeof window.fetch;
                out.xhrType = typeof XMLHttpRequest;
                
                // Check for __billingE2EE or similar
                for (const key of Object.getOwnPropertyNames(window)) {
                    const lower = key.toLowerCase();
                    if (lower.includes('billing') || lower.includes('e2ee') || lower.includes('payment')) {
                        try {
                            const v = window[key];
                            out['window_' + key] = typeof v;
                        } catch(e) {}
                    }
                }
                
                return out;
            }
        """)
        print("E2EE info:")
        print(json.dumps(e2ee_info, indent=2))

        # Try to find the e2ee module by intercepting require calls
        # Inject a shim to capture all module definitions
        modules_found = await page.evaluate("""
            () => {
                const out = [];
                // Search for modules that contain 'e2ee' or 'protect' or 'sensitive'
                // Meta bundles modules with __d(name, deps, factory, ...)
                // We can search the page's JavaScript for these patterns
                
                // Check all inline scripts
                const scripts = document.querySelectorAll('script:not([src])');
                let found = [];
                for (const s of scripts) {
                    const text = s.textContent;
                    // Look for BillingProtectedString definition
                    const matches = text.match(/__d\("([^"]*(?:Protect|E2EE|Sensitive|Encrypt)[^"]*)"/gi);
                    if (matches) found.push(...matches);
                    
                    // Look for e2ee key URL
                    const keyUrls = text.match(/https?:\/\/[^"'\s]*(?:e2ee|encrypt|key)[^"'\s]*/gi);
                    if (keyUrls) found.push(...keyUrls.map(u => 'URL: ' + u));
                }
                
                // Also check external script URLs
                const extScripts = document.querySelectorAll('script[src]');
                for (const s of extScripts) {
                    if (s.src.includes('billing') || s.src.includes('payment')) {
                        found.push('SCRIPT: ' + s.src);
                    }
                }
                
                return found;
            }
        """)
        print(f"\nModules/scripts found: {json.dumps(modules_found, indent=2)}")

        # Most importantly: search the billing JS bundle for e2ee key exchange URL
        print("\nSearching billing bundles for e2ee patterns...")
        billing_scripts = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[src]');
                return Array.from(scripts)
                    .map(s => s.src)
                    .filter(s => s.includes('billing') || s.includes('Billing') || s.includes('payment') || s.includes('Payment'))
                    .slice(0, 10);
            }
        """)
        print(f"Billing scripts: {json.dumps(billing_scripts, indent=2)}")

        print("\n[DONE]")

asyncio.run(main())
