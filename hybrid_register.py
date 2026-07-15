#!/usr/bin/env python3
"""
Hybrid Meta AI registration: API + browser card addition.

Meta's own JS handles ECDH card encryption natively in the browser —
no need to reverse-engineer trust tokens or ConcatKDF.

Usage:
  1. python3 hybrid_register.py --step register
     → Register via API (tempmail + OTP), save session.json

  2. python3 hybrid_register.py --step card [--headless]
     → Open Chromium, inject cookies, fill card form
     → Meta JS encrypts card data via ECDH-ES automatically
     → Requires SOCKS5 proxy at 127.0.0.1:1081 (US IP)
     → Linux: headless (needs Xvfb :99), Windows: headed + real Chrome

  3. python3 hybrid_register.py --step apikey
     → Create API key via GraphQL, output final account JSON
"""
import json, os, sys, time, argparse, asyncio, platform, random


# ---------------------------------------------------------------------------
# Card constants (must match bot_windows.py exactly)
# ---------------------------------------------------------------------------
CARD_NUMBER = "4889501032758307"
CARD_EXPIRY = "08/27"
CARD_CVV = "424"
CARD_ZIP = "90001"
CARD_NAME = "Brian Anderson"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def dismiss_modals(page, max_rounds=3):
    """Dismiss 'Continue'/'OK'/'Done' modals — NOT 'Get started' (that's onboarding)."""
    async def _dismiss():
        for _ in range(max_rounds):
            try:
                els = await page.evaluate("""
                    Array.from(document.querySelectorAll('button, div[role="button"]')).filter(el => {
                        const t = el.innerText?.trim();
                        return (t === 'Continue' || t === 'OK' || t === 'Done' || t === 'Save') &&
                               el.offsetParent !== null &&
                               el.getBoundingClientRect().height > 20;
                    }).map(el => ({ r: el.getBoundingClientRect(), text: el.innerText.trim() }))
                """)
                if els:
                    e = els[0]['r']
                    await page.mouse.click(e['x'] + e['width'] / 2, e['y'] + e['height'] / 2)
                    await asyncio.sleep(2)
                else:
                    break
            except Exception:
                break
    return _dismiss()


# ---------------------------------------------------------------------------
# Step 1: Register via API
# ---------------------------------------------------------------------------
def step_register():
    """Step 1: Register account via pure API (runs on VPS)."""
    from api_client import MetaAPI, tempmail_generate, tempmail_otp
    
    c = MetaAPI()
    email, _ = tempmail_generate()
    c.check_email(email)
    reg = c.register(email, "TestPass123!")
    otp = tempmail_otp(email, 90)
    if not otp:
        print(json.dumps({"error": "OTP timeout"}))
        return
    
    c.verify_otp(otp, reg.get('account_id'))
    oauth = c.oauth_login()
    c.onboard('Brian', 'Anderson')
    c.terms()
    billing_info = c.load_billing()
    
    session = {
        'email': email,
        'password': 'TestPass123!',
        'actor_id': c.actor_id,
        'team_id': c.team_id,
        'payment_account_id': c.payment_account_id,
        'project_id': c.project_id,
        'cookies': c.cookies_dict(),
        'fb_dtsg': c.fb_dtsg,
        'lsd': c.lsd,
        'has_session': oauth.get('has_session', False),
    }
    
    with open('session.json', 'w') as f:
        json.dump(session, f, indent=2)
    
    print(json.dumps({
        'status': 'registered',
        'email': email,
        'team_id': c.team_id,
        'project_id': c.project_id,
        'session_file': 'session.json',
    }, indent=2))


# ---------------------------------------------------------------------------
# Step 2: Add card via browser (mirrors bot_windows.py step_billing exactly)
# ---------------------------------------------------------------------------
def step_card(session_file='session.json', headless=None):
    """Step 2: Add card via browser (Meta JS handles ECDH encryption natively).

    This mirrors the exact billing flow from bot_windows.py:
    - Navigate to billing URL with project_id & team_id
    - Dismiss modals
    - Click "Add payment method"
    - Fill card form with human-like typing
    - Capture GraphQL response via resp.text() (handles "for (;;);" prefix)
    - Parse xfb_billing_save_credit_card result
    """
    with open(session_file) as f:
        session = json.load(f)

    # Resolve headless mode: explicit flag > auto-detect
    if headless is None:
        headless = platform.system() == 'Linux'

    is_windows = platform.system() == 'Windows'

    async def run():
        from playwright.async_api import async_playwright

        # Build cookie list for injection
        cookies = []
        for domain, cs in session['cookies'].items():
            for name, value in cs.items():
                cookies.append({
                    'name': name, 'value': value,
                    'domain': domain, 'path': '/',
                    'secure': True, 'httpOnly': True,
                })

        async with async_playwright() as p:
            # Platform-aware browser launch
            launch_kwargs = {
                'headless': headless,
                'proxy': {"server": "socks5://127.0.0.1:1081"},
                'args': ['--disable-blink-features=AutomationControlled'],
            }
            # Use real Chrome on Windows (channel='chrome'), default Chromium on Linux
            if is_windows:
                launch_kwargs['channel'] = 'chrome'
            browser = await p.chromium.launch(**launch_kwargs)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await ctx.add_cookies(cookies)

            result = {"status": "failed"}

            # ── Build billing URL with project_id & team_id ──
            billing_base = "https://dev.meta.ai/billing"
            project_id = session.get('project_id')
            team_id = session.get('team_id')
            if project_id and team_id:
                billing_url_target = f"{billing_base}?project_id={project_id}&team_id={team_id}"
            else:
                billing_url_target = f"{billing_base}?team_id={team_id}"

            print(f"  [card] Navigating to billing: {billing_url_target}", file=sys.stderr)
            await page.goto(billing_url_target, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(5)

            # Check for geo-block
            body = await page.evaluate("() => document.body?.innerText || ''")
            if 'not available' in body.lower():
                print(json.dumps({"error": "Geo-blocked"}))
                await browser.close()
                return

            # ── Dismiss modals ──
            await dismiss_modals(page)

            # Force-remove any lingering dialog
            if await page.locator('[role="dialog"]').count() > 0:
                await page.evaluate('document.querySelectorAll(\'[role="dialog"]\').forEach(d => d.remove())')
                await asyncio.sleep(1)

            # ── Click "Add payment method" ──
            add_btn_found = False
            for attempt in range(2):
                try:
                    btn = await page.wait_for_selector(
                        ':is(button, [role="button"]):has-text("Add payment method")',
                        timeout=15000
                    )
                    await btn.click()
                    add_btn_found = True
                    await asyncio.sleep(4)
                    break
                except Exception:
                    if attempt == 0:
                        await page.keyboard.press('Escape')
                        await asyncio.sleep(2)
                        try:
                            close = page.locator('[aria-label="Close"]')
                            if await close.count() > 0:
                                await close.first.click(force=True)
                                await asyncio.sleep(2)
                        except Exception:
                            pass
            if not add_btn_found:
                print(json.dumps({"error": "No add payment button found"}))
                await browser.close()
                return

            # ── Wait for card form ──
            card_input = await page.query_selector('input[name="cardNumber"]')
            if not card_input:
                await asyncio.sleep(5)
                card_input = await page.query_selector('input[name="cardNumber"]')
            if not card_input:
                print(json.dumps({"error": "Card form not loaded"}))
                await browser.close()
                return

            # ── Fill card form (mirrors bot_windows.py exactly) ──
            print("  [card] Filling card form...", file=sys.stderr)

            el = await page.query_selector('input[name="firstName"]')
            if el:
                await el.click()
                await el.fill("")
                await el.type(CARD_NAME, delay=30)
            await asyncio.sleep(random.uniform(0.3, 0.7))

            el = await page.query_selector('input[name="cardNumber"]')
            if el:
                await el.click()
                await el.fill("")
                for ch in CARD_NUMBER:
                    await page.keyboard.type(ch, delay=random.randint(30, 60))
            await asyncio.sleep(random.uniform(0.3, 0.7))

            el = await page.query_selector('input[name="expiration"]')
            if el:
                await el.click()
                await asyncio.sleep(0.2)
                for ch in CARD_EXPIRY:
                    await page.keyboard.type(ch, delay=random.randint(40, 80))
            await asyncio.sleep(random.uniform(0.3, 0.7))

            el = await page.query_selector('input[name="securityCode"]')
            if el:
                await el.click()
                await asyncio.sleep(0.2)
                for ch in CARD_CVV:
                    await page.keyboard.type(ch, delay=random.randint(40, 80))
            await asyncio.sleep(random.uniform(0.3, 0.7))

            # ZIP code via JS injection (same as bot_windows.py)
            await page.evaluate(f"""() => {{
                for (const inp of document.querySelectorAll('input')) {{
                    const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                    if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {{
                        if (!inp.value) {{
                            inp.value = '{CARD_ZIP}';
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                    }}
                }}
            }}""")
            await asyncio.sleep(1)

            # ── Capture billing GraphQL response (resp.text + "for (;;);" handling) ──
            billing_response = {}

            async def on_billing_resp(resp):
                if "billing/graphql" in resp.url:
                    try:
                        body_text = await resp.text()
                        if "save_credit_card" in body_text:
                            billing_response["body"] = body_text
                    except Exception:
                        pass

            page.on("response", on_billing_resp)

            # ── Submit card ──
            print("  [card] Submitting card...", file=sys.stderr)
            next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
            if next_btn:
                await next_btn.click(force=True)
            else:
                # Fallback: try other submit buttons
                for sel in ['button:has-text("Save")', 'button:has-text("Add card")',
                            'button:has-text("Continue")', 'button[type="submit"]']:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            break
                    except Exception:
                        pass

            # Wait for GraphQL response (up to 15s)
            for _ in range(30):
                await asyncio.sleep(0.5)
                if billing_response:
                    break

            # ── Parse result (mirrors bot_windows.py exactly) ──
            if billing_response.get("body"):
                raw = billing_response["body"]
                if raw.startswith("for (;;);"):
                    raw = raw[len("for (;;);"):]
                try:
                    d = json.loads(raw)
                    r = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
                    cc = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("credit_card")
                    print(f"  [card] Billing status: {r.get('status')} | error: {r.get('error_code')}", file=sys.stderr)
                    if cc:
                        print("  [card] ✅ CARD SAVED!", file=sys.stderr)
                        result["status"] = "success"
                    else:
                        print(f"  [card] ❌ {r.get('message')}", file=sys.stderr)
                        result["error"] = r.get("message", "Card save failed")
                except Exception as e:
                    print(f"  [card] Parse error: {e}", file=sys.stderr)
                    result["error"] = f"Parse error: {e}"
            else:
                body = await page.evaluate("document.body?.innerText || ''")
                if "couldn't save" in body.lower():
                    print("  [card] ❌ Card save failed", file=sys.stderr)
                    result["error"] = "Card save failed (trust token issue?)"
                elif "temporarily blocked" in body.lower():
                    print("  [card] ❌ Rate limited", file=sys.stderr)
                    result["error"] = "Rate limited"
                else:
                    print(f"  [card] Result unclear: {body[:200]}", file=sys.stderr)
                    result["error"] = f"Unclear result: {body[:200]}"

            # ── Save updated cookies ──
            new_cookies = await ctx.cookies()
            for ck in new_cookies:
                try:
                    domain = ck['domain']
                    name = ck['name']
                    value = ck['value']
                    if domain not in session['cookies']:
                        session['cookies'][domain] = {}
                    session['cookies'][domain][name] = value
                except Exception:
                    pass

            with open(session_file, 'w') as f:
                json.dump(session, f, indent=2)

            await browser.close()

            # ── Output result ──
            result['session_file'] = session_file
            print(json.dumps(result, indent=2))

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Step 3: Create API key
# ---------------------------------------------------------------------------
def step_apikey(session_file='session.json'):
    """Step 3: Create API key via pure API (runs on VPS)."""
    from api_client import MetaAPI, DOC, DEV_URL
    
    with open(session_file) as f:
        session = json.load(f)
    
    c = MetaAPI()
    for domain, cs in session['cookies'].items():
        for name, value in cs.items():
            try:
                c.s.cookies.set(name, value, domain=domain)
            except Exception:
                pass
    
    c.actor_id = session['actor_id']
    c.team_id = session['team_id']
    c.payment_account_id = session.get('payment_account_id')
    c.fb_dtsg = session.get('fb_dtsg')
    c.lsd = session.get('lsd')
    
    ak = c.create_api_key()
    
    result = {
        'email': session['email'],
        'password': session['password'],
        'actor_id': c.actor_id,
        'team_id': c.team_id,
        'api_key': ak.get('access_token', ''),
        'cookies': c.cookies_dict(),
    }
    
    os.makedirs('data/output', exist_ok=True)
    outfile = f'data/output/account_{int(time.time())}.json'
    with open(outfile, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hybrid Meta AI registration')
    parser.add_argument('--step', choices=['register', 'card', 'apikey'], required=True)
    parser.add_argument('--session', default='session.json')
    parser.add_argument('--headless', action='store_true', default=None,
                        help='Force headless browser (default: auto-detect, Linux=headless)')
    parser.add_argument('--no-headless', dest='headless', action='store_false',
                        help='Force headed browser')
    args = parser.parse_args()

    if args.step == 'register':
        step_register()
    elif args.step == 'card':
        step_card(args.session, headless=args.headless)
    elif args.step == 'apikey':
        step_apikey(args.session)
