"""Login Google account in Chrome to enable Trust Token attestation."""
import asyncio, json, os, sys
os.environ["DISPLAY"] = ":99"

async def main():
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    # Use a fresh Chrome profile
    profile_dir = "/tmp/chrome-profile-trust"
    os.makedirs(profile_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                f"--user-data-dir={profile_dir}",
                "--enable-features=TrustTokens,PrivateStateTokens",
                "--enable-features=AttestationConsent",
            ]
        )
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await ctx.new_page()
        await Stealth().apply_stealth_async(page)
        page.set_default_timeout(60000)

        # Check Trust Token support BEFORE login
        print("[1] Before Google login:")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        trust_before = await page.evaluate("""
            async () => {
                const r = {};
                r.hasTrustToken = typeof document.hasTrustToken === 'function';
                r.hasPrivateStateToken = typeof document.hasPrivateStateToken === 'function';
                // Try to check enrollment
                if (r.hasTrustToken) {
                    try { r.hasToken = await document.hasTrustToken('https://google.com'); } catch(e) { r.error = e.message; }
                }
                return r;
            }
        """)
        print(f"  Trust: {json.dumps(trust_before)}")

        # Go to Google login
        print("\n[2] Google login...")
        await page.goto("https://accounts.google.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        body = await page.evaluate("document.body?.innerText || ''")
        print(f"  Page: {body[:200]}")
        
        # Check if we can sign in
        email_input = await page.query_selector('input[type="email"]')
        if email_input:
            print("  Email input found! Need Google credentials to proceed.")
            print("  Please provide Google account email/password.")
        else:
            print("  No email input found")
        
        await page.screenshot(path="data/screenshots/google_login.png")
        
        # Check Trust Token after visiting Google
        print("\n[3] After Google visit:")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        trust_after = await page.evaluate("""
            async () => {
                const r = {};
                r.hasTrustToken = typeof document.hasTrustToken === 'function';
                r.hasPrivateStateToken = typeof document.hasPrivateStateToken === 'function';
                return r;
            }
        """)
        print(f"  Trust: {json.dumps(trust_after)}")
        
        print("\n[INFO] Chrome needs Google account sign-in to enable Trust Tokens.")
        print("[INFO] This is a chicken-and-egg problem:")
        print("  - Trust Tokens require Google account + enrollment time")
        print("  - Meta billing requires Trust Tokens for platform_trust_token")
        print("  - VPS can't get real Trust Tokens without Google enrollment")
        
        print("\n[DONE]")
        await browser.close()

asyncio.run(main())
