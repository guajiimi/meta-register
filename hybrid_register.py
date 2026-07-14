#!/usr/bin/env python3
"""
Hybrid Meta AI registration: API on VPS, card addition on Windows local.

Usage:
  1. Run on VPS: python3 hybrid_register.py --step register
     → Creates account, saves session to session.json
  
  2. Copy session.json to Windows, run:
     python hybrid_register.py --step card --session session.json
     → Opens browser, fills card form, saves result
  
  3. Copy result back to VPS, run:
     python3 hybrid_register.py --step apikey --session session.json
     → Creates API key, outputs final account JSON
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


def step_card(session_file='session.json'):
    """Step 2: Add card via browser (runs on Windows local with real Chrome)."""
    import asyncio
    
    with open(session_file) as f:
        session = json.load(f)
    
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
            # Use real Chrome (headed) — Windows has TPM
            browser = await p.chromium.launch(
                headless=False,
                proxy={"server": "socks5://127.0.0.1:1081"},
                args=['--disable-blink-features=AutomationControlled'],
            )
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await ctx.add_cookies(cookies)
            
            # Navigate to billing
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
            
            # Dismiss modals
            import random
            for _ in range(3):
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
            await asyncio.sleep(1)
            
            # Click Add payment method
            try:
                btn = await page.wait_for_selector(
                    ':is(button, [role="button"]):has-text("Add payment method")',
                    timeout=15000
                )
                await btn.click()
                await asyncio.sleep(4)
            except Exception as e:
                print(json.dumps({"error": f"No add payment button: {e}"}))
                await browser.close()
                return
            
            # Wait for card form
            card_input = await page.query_selector('input[name="cardNumber"]')
            if not card_input:
                await asyncio.sleep(5)
                card_input = await page.query_selector('input[name="cardNumber"]')
            
            if not card_input:
                print(json.dumps({"error": "Card form not loaded"}))
                await browser.close()
                return
            
            # Fill card form
            CARD_NUMBER = "4889501032758307"
            CARD_EXPIRY = "0827"
            CARD_CVV = "424"
            CARD_NAME = "Brian Anderson"
            CARD_ZIP = "94025"
            
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
            
            # ZIP code
            await page.evaluate(f"""() => {{
                for (const inp of document.querySelectorAll('input')) {{
                    const t = (inp.closest('label')?.innerText || '') + (inp.parentElement?.innerText || '');
                    if (t.toLowerCase().includes('zip') || t.toLowerCase().includes('postal')) {{
                        inp.value = '{CARD_ZIP}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            }}""")
            await asyncio.sleep(1)
            
            # Submit
            for sel in ['button:has-text("Save")', 'button:has-text("Add card")', 'button:has-text("Continue")']:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        break
                except:
                    pass
            
            await asyncio.sleep(10)
            
            # Check result
            body = await page.evaluate("() => document.body?.innerText || ''")
            success = 'visa' in body.lower() or '8307' in body or 'added' in body.lower()
            
            # Save updated cookies
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
            
            result = {
                'success': success,
                'body_snippet': body[:300],
                'session_file': session_file,
            }
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
    args = parser.parse_args()
    
    if args.step == 'register':
        step_register()
    elif args.step == 'card':
        step_card(args.session)
    elif args.step == 'apikey':
        step_apikey(args.session)
