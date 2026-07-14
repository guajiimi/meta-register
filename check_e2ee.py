#!/usr/bin/env python3
"""Check if Meta's e2ee encryption works in Camoufox."""
import asyncio, json, os, sys

os.environ["DISPLAY"] = ":99"

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

        btn = await page.wait_for_selector('button:has-text("Add payment method")', timeout=10000)
        await btn.click()
        await asyncio.sleep(4)

        # Check crypto capabilities
        print("=== Crypto Check ===")
        crypto_check = await page.evaluate("""
            () => {
                const result = {};
                // Web Crypto API
                result.hasCrypto = typeof crypto !== 'undefined';
                result.hasSubtleCrypto = typeof crypto !== 'undefined' && typeof crypto.subtle !== 'undefined';
                
                // Check if SubtleCrypto methods exist
                if (result.hasSubtleCrypto) {
                    result.hasEncrypt = typeof crypto.subtle.encrypt === 'function';
                    result.hasGenerateKey = typeof crypto.subtle.generateKey === 'function';
                    result.hasImportKey = typeof crypto.subtle.importKey === 'function';
                    result.hasExportKey = typeof crypto.subtle.exportKey === 'function';
                }
                
                // Test actual encryption
                result.encryptionTest = 'pending';
                return result;
            }
        """)
        print(f"  Crypto: {json.dumps(crypto_check, indent=2)}")

        # Test actual RSA-OAEP or AES-GCM encryption
        enc_test = await page.evaluate("""
            async () => {
                try {
                    // Generate AES key
                    const key = await crypto.subtle.generateKey(
                        {name: 'AES-GCM', length: 256},
                        true,
                        ['encrypt', 'decrypt']
                    );
                    const iv = crypto.getRandomValues(new Uint8Array(12));
                    const data = new TextEncoder().encode('test123456789012');
                    const encrypted = await crypto.subtle.encrypt(
                        {name: 'AES-GCM', iv: iv},
                        key,
                        data
                    );
                    return {success: true, encryptedLength: encrypted.byteLength};
                } catch(e) {
                    return {success: false, error: e.message, stack: e.stack?.substring(0, 200)};
                }
            }
        """)
        print(f"  Encryption test: {json.dumps(enc_test, indent=2)}")

        # Check for Meta's e2ee library
        e2ee_check = await page.evaluate("""
            () => {
                const result = {};
                // Check for Meta's e2ee globals
                result.hasE2EE = typeof window.__e2ee !== 'undefined';
                result.hasE2EEKeys = typeof window.__e2ee_keys !== 'undefined';
                
                // Check for any crypto-related globals
                const cryptoGlobals = [];
                for (const key of Object.keys(window)) {
                    if (key.toLowerCase().includes('crypt') || key.toLowerCase().includes('e2ee') || 
                        key.toLowerCase().includes('encrypt') || key.toLowerCase().includes('sensitive')) {
                        cryptoGlobals.push(key);
                    }
                }
                result.cryptoGlobals = cryptoGlobals;
                
                // Check for trust token API
                result.hasTrustToken = typeof document.hasTrustToken === 'function';
                result.hasPrivateStateToken = typeof document.hasPrivateStateToken === 'function';
                
                return result;
            }
        """)
        print(f"  E2EE: {json.dumps(e2ee_check, indent=2)}")

        # Check if card input has special event listeners
        card_listeners = await page.evaluate("""
            () => {
                const inp = document.querySelector('input[name="cardNumber"]');
                if (!inp) return 'no card input';
                
                // Check for data attributes
                const attrs = {};
                for (const attr of inp.attributes) {
                    if (attr.name.startsWith('data-') || attr.name.startsWith('aria-')) {
                        attrs[attr.name] = attr.value;
                    }
                }
                
                // Check parent form
                const form = inp.closest('form');
                const formAction = form ? form.action : 'no form';
                
                return {attrs, formAction, type: inp.type, autocomplete: inp.autocomplete};
            }
        """)
        print(f"  Card input: {json.dumps(card_listeners, indent=2)}")

        # Fill card and watch what happens to the value
        print("\n=== Fill card and monitor ===")
        el = await page.query_selector('input[name="cardNumber"]')
        if el:
            await el.click()
            await el.fill("")
            for ch in "4463694299238720":
                await page.keyboard.type(ch, delay=30)
            
            await asyncio.sleep(2)
            
            # Check the value - is it still plaintext or encrypted?
            val = await page.evaluate("""
                () => {
                    const inp = document.querySelector('input[name="cardNumber"]');
                    return {
                        value: inp.value,
                        valueLength: inp.value.length,
                    };
                }
            """)
            print(f"  After fill: {json.dumps(val)}")

        await page.screenshot(path="data/screenshots/e2ee_check.png")
        print("\n[DONE]")

asyncio.run(main())
