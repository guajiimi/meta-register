#!/usr/bin/env python3
"""Try creating API key without payment method (using free credits)."""
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

        api_calls = []
        async def on_resp(resp):
            if "graphql" in resp.url or "api" in resp.url:
                if "pixel" not in resp.url and "google" not in resp.url and "reddit" not in resp.url:
                    try:
                        body = await resp.text()
                        api_calls.append({"url": resp.url[:200], "status": resp.status, "body": body[:2000]})
                    except: pass
        page.on("response", on_resp)

        # Go to API keys page
        print("[1] API keys page...")
        await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except: pass
        await asyncio.sleep(3)

        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  Page: {body[:500]}")

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
        print(f"\n  After dismiss: {body[:500]}")

        # Check buttons
        btns = await page.evaluate("""
            Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => ({
                text: b.innerText.trim(),
                disabled: b.disabled,
            }))
        """)
        print(f"\n  Buttons: {btns}")

        # Try clicking Create API key
        create_btn = await page.query_selector('button:has-text("Create API key")')
        if create_btn:
            disabled = await create_btn.is_disabled()
            print(f"\n[2] Create API key button: disabled={disabled}")
            if not disabled:
                api_calls.clear()
                await create_btn.click(force=True)
                await asyncio.sleep(5)
                
                body = await page.evaluate("document.body?.innerText || ''")
                print(f"  After click: {body[:500]}")
                
                # Check for name input
                name_input = await page.query_selector('input[type="text"]')
                if name_input:
                    await name_input.fill("default")
                    create = await page.query_selector('button:has-text("Create")')
                    if create:
                        api_calls.clear()
                        await create.click(force=True)
                        await asyncio.sleep(5)
                        for c in api_calls:
                            print(f"  API [{c['status']}]: {c['url'][:100]}")
                            body = c['body']
                            if body.startswith("for (;;);"): body = body[len("for (;;);"):]
                            print(f"    {body[:500]}")
                        
                        body = await page.evaluate("document.body?.innerText || ''")
                        print(f"  Result: {body[:500]}")
            else:
                print("  Button disabled — needs payment first")
        else:
            print("  No 'Create API key' button found")

        await page.screenshot(path="data/screenshots/apikey_attempt.png")
        print(f"\n[DONE]")

asyncio.run(main())
