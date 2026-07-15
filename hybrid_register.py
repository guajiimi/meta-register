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
import json, os, sys, time, argparse

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
    c.load_billing()
    
    session = {
        'email': email,
        'password': 'TestPass123!',
        'actor_id': c.actor_id,
        'team_id': c.team_id,
        'payment_account_id': c.payment_account_id,
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
        'session_file': 'session.json',
    }, indent=2))


def step_card(session_file='session.json', headless=None):
    """Step 2: Add card via browser (Meta JS handles ECDH encryption natively)."""
    import asyncio
    import platform
    import random

    with open(session_file) as f:
        session = json.load(f)

    # Resolve headless mode: explicit flag > auto-detect
    if headless is None:
        headless = platform.system() == 'Linux'

    is_windows = platform.system() == 'Windows'

    # Card details
    CARD_NUMBER = "4889501032758307"
    CARD_EXPIRY = "0827"
    CARD_CVV = "424"
    CARD_NAME = "Brian Anderson"
    CARD_ZIP = "94025"

    async def run():
        from playwright.async_api import async_playwright

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

            # ── Navigate to billing ──
            billing_url = f"https://dev.meta.ai/billing/?team_id={session['team_id']}"
            await page.goto(billing_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except:
                pass
            await asyncio.sleep(5)

            body = await page.evaluate("() => document.body?.innerText || ''")
            if 'not available' in body.lower():
                print(json.dumps({"error": "Geo-blocked"}))
                await browser.close()
                return

            # ── Handle Welcome dialog (first billing visit) ──
            # Shows "Welcome to Meta Model API" with $20 free credits info
            try:
                # Try close button by aria-label
                close_btn = page.locator('[aria-label="Close"]')
                if await close_btn.count() > 0:
                    await close_btn.first.click(force=True)
                    await asyncio.sleep(1)
                else:
                    # Try "Get started" or similar CTA buttons in the dialog
                    for text in ["Get started", "Got it", "Continue", "OK", "Start"]:
                        btn = page.locator(f'button:has-text("{text}")')
                        if await btn.count() > 0:
                            await btn.first.click(force=True)
                            await asyncio.sleep(1)
                            break
            except:
                pass

            # Dismiss any remaining modals
            for _ in range(2):
                try:
                    close = page.locator('[aria-label="Close"]')
                    if await close.count() > 0:
                        await close.first.click(force=True)
                        await asyncio.sleep(1)
                    else:
                        break
                except:
                    break
            await page.keyboard.press('Escape')
            await asyncio.sleep(2)

            # ── Click "Add payment method" with retry ──
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
                except:
                    if attempt == 0:
                        # Retry: dismiss modal again and re-check
                        await page.keyboard.press('Escape')
                        await asyncio.sleep(2)
                        try:
                            close = page.locator('[aria-label="Close"]')
                            if await close.count() > 0:
                                await close.first.click(force=True)
                                await asyncio.sleep(2)
                        except:
                            pass
            if not add_btn_found:
                print(json.dumps({"error": "No add payment button found after retries"}))
                await browser.close()
                return

            # ── Wait for card form with retry ──
            card_input = await page.query_selector('input[name="cardNumber"]')
            if not card_input:
                # Retry once: maybe modal dismissal was slow
                await asyncio.sleep(5)
                card_input = await page.query_selector('input[name="cardNumber"]')
            if not card_input:
                print(json.dumps({"error": "Card form not loaded after modal dismiss"}))
                await browser.close()
                return

            # ── Set up network capture for GraphQL card-save verification ──
            card_save_response = {}

            async def capture_graphql_response(response):
                url = response.url
                if 'graphql' in url.lower() or 'payment' in url.lower():
                    try:
                        data = await response.json()
                        data_str = json.dumps(data).lower()
                        # Look for PaymentType_Add mutation or payment_type in response
                        if ('payment' in data_str and (
                                'add' in data_str or 'type' in data_str or
                                'last4' in data_str or 'card' in data_str)):
                            card_save_response['data'] = data
                            card_save_response['success'] = (
                                'last4' in data_str or
                                '8307' in data_str or
                                'paymentmethod' in data_str.replace(' ', '')
                            )
                    except:
                        pass

            page.on('response', capture_graphql_response)

            # ── Fill card form ──
            el = await page.query_selector('input[name="firstName"]')
            if el:
                await el.click()
                await el.type(CARD_NAME, delay=30)
            await asyncio.sleep(0.5)

            el = await page.query_selector('input[name="cardNumber"]')
            if el:
                await el.click()
                for ch in CARD_NUMBER:
                    await page.keyboard.type(ch, delay=random.randint(30, 60))
            await asyncio.sleep(0.5)

            el = await page.query_selector('input[name="expiration"]')
            if el:
                await el.click()
                for ch in CARD_EXPIRY:
                    await page.keyboard.type(ch, delay=random.randint(40, 80))
            await asyncio.sleep(0.5)

            el = await page.query_selector('input[name="securityCode"]')
            if el:
                await el.click()
                for ch in CARD_CVV:
                    await page.keyboard.type(ch, delay=random.randint(40, 80))
            await asyncio.sleep(0.5)

            # ZIP code — use type() so React sees each keystroke
            zip_input = await page.query_selector(
                'input[name="zip"], input[name="postalCode"], input[placeholder*="ZIP"], input[placeholder*="zip"]'
            )
            if not zip_input:
                # Fallback: find by label text
                zip_input = await page.evaluate_handle("""() => {
                    for (const inp of document.querySelectorAll('input')) {
                        const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                        if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {
                            return inp;
                        }
                    }
                    return null;
                }""")
                if zip_input and await zip_input.evaluate("el => el !== null"):
                    zip_input = zip_input.as_element()
                else:
                    zip_input = None
            if zip_input:
                await zip_input.click()
                await zip_input.type(CARD_ZIP, delay=40)
            await asyncio.sleep(1)

            # ── Submit card form ──
            submitted = False
            for sel in ['button:has-text("Save")', 'button:has-text("Add card")',
                        'button:has-text("Continue")', 'button[type="submit"]']:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        submitted = True
                        break
                except:
                    pass
            if not submitted:
                print(json.dumps({"error": "Could not find submit button"}))
                await browser.close()
                return

            # Wait for GraphQL response (up to 30s)
            for _ in range(60):
                await asyncio.sleep(0.5)
                if card_save_response:
                    break

            # ── Determine success from network capture (primary) or page body (fallback) ──
            success = False
            graphql_error = None
            body_text = ''

            if card_save_response.get('data'):
                data = card_save_response['data']
                success = card_save_response.get('success', False)
                if not success and 'errors' in data:
                    graphql_error = data['errors']
            else:
                # Fallback: check page body text
                body_text = await page.evaluate("() => document.body?.innerText || ''")
                success = 'visa' in body_text.lower() or '8307' in body_text or 'added' in body_text.lower()

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
                except:
                    pass

            with open(session_file, 'w') as f:
                json.dump(session, f, indent=2)

            await browser.close()

            # ── Build result ──
            result = {
                'success': success,
                'session_file': session_file,
            }
            if graphql_error:
                result['graphql_errors'] = graphql_error
                print(f"[!] GraphQL error: {json.dumps(graphql_error, indent=2)}", file=sys.stderr)
            if card_save_response.get('data'):
                result['graphql_snippet'] = json.dumps(card_save_response['data'])[:500]
            if not success and not graphql_error:
                result['body_snippet'] = body_text[:300] if body_text else '(checked via network capture)'

            print(json.dumps(result, indent=2))

    asyncio.run(run())


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
            except:
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
