#!/usr/bin/env python3
"""Find and test e2ee encryption module."""
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

        # Try to find and load e2ee modules via require/define
        result = await page.evaluate("""
            () => {
                const out = {};
                
                // Try Meta's module system (__d defines, require loads)
                try {
                    const mod = require('BillingProtectedString');
                    out.billingProtectedString = typeof mod;
                    out.keys = Object.keys(mod);
                } catch(e) {
                    out.billingProtectedString = 'not found: ' + e.message;
                }
                
                try {
                    const mod = require('BillingAddCreditCardFormUtils');
                    out.addCardUtils = typeof mod;
                    out.addCardKeys = Object.keys(mod).slice(0, 20);
                } catch(e) {
                    out.addCardUtils = 'not found: ' + e.message;
                }
                
                // Check for any e2ee module
                try {
                    const mod = require('E2EEPaymentEncryption');
                    out.e2ee = typeof mod;
                } catch(e) {
                    out.e2eeModule = 'not found';
                }
                
                // Check all available billing modules
                try {
                    // List all defined modules containing 'billing' or 'e2ee'
                    out.billingModules = [];
                    if (typeof __d === 'function') {
                        // __d is the define function, can't easily list
                    }
                    // Try common e2ee module names
                    for (const name of ['E2EEManager', 'E2EEPayment', 'E2EEKeyManager', 
                                        'BillingE2EE', 'PaymentEncryption', 'SensitiveString',
                                        'BillingProtectedString', 'BillingCreditCardNumber',
                                        'BillingCreditCardUtils']) {
                        try {
                            const m = require(name);
                            out[name] = Object.keys(m);
                        } catch(e) {}
                    }
                } catch(e) {
                    out.moduleError = e.message;
                }
                
                return out;
            }
        """)
        print(json.dumps(result, indent=2))

        # Also check if we can access the e2ee function directly
        result2 = await page.evaluate("""
            () => {
                const out = {};
                
                // Check for sensitive_string_value pattern in the billing code
                try {
                    const BillingProtectedString = require('BillingProtectedString');
                    out.protectedString = {};
                    for (const [k, v] of Object.entries(BillingProtectedString)) {
                        out.protectedString[k] = typeof v === 'function' ? v.toString().substring(0, 200) : String(v).substring(0, 100);
                    }
                } catch(e) {}
                
                // Check BillingCreditCardNumber
                try {
                    const mod = require('BillingCreditCardNumber');
                    out.cardNumber = {};
                    for (const [k, v] of Object.entries(mod)) {
                        out.cardNumber[k] = typeof v === 'function' ? v.toString().substring(0, 150) : String(v).substring(0, 100);
                    }
                } catch(e) {}
                
                return out;
            }
        """)
        print(json.dumps(result2, indent=2))

asyncio.run(main())
