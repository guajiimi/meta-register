#!/usr/bin/env python3
"""
Meta AI Unified Registration Bot — VPS / Xvfb edition.

All-in-one: API register → browser card → API key.

Uses Xvfb virtual display (:99) for headed Chromium with
Meta's ECDH card encryption (crypto.subtle requires secure context).

Flow:
  1. API register (~30s): tempmail → register → OTP → verify → oauth → onboard → terms → billing
  2. Browser card: inject cookies → billing page → fill card → capture GraphQL response
  3. API key: GraphQL mutation → access_token

Requires:
  - SOCKS5 proxy at 127.0.0.1:1081 (US IP)
  - Xvfb running on :99 (DISPLAY=:99)

Usage:
  python3 bot.py                    # full flow (register + card + api key)
  python3 bot.py --no-card          # skip billing/card step
  python3 bot.py --no-apikey        # skip API key creation
"""

import argparse
import asyncio
import json
import os
import random
import string
import sys
import time
import uuid
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROXY_URL = "socks5://127.0.0.1:1081"
DISPLAY = ":99"

CARD_NUMBER = "4889501032758307"
CARD_EXPIRY = "08/27"
CARD_CVV = "424"
CARD_ZIP = "90001"

FIRST_NAMES = [
    "James", "Michael", "Robert", "David", "William", "Joseph", "Thomas",
    "Daniel", "Matthew", "Anthony", "Mark", "Steven", "Paul", "Andrew",
    "Brian", "George", "Timothy", "Ronald", "Edward", "Jason",
    "Sarah", "Jessica", "Jennifer", "Amanda", "Ashley", "Stephanie",
    "Nicole", "Elizabeth", "Heather", "Megan", "Rachel", "Lauren",
    "Emily", "Samantha", "Kayla", "Courtney", "Rebecca", "Laura",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def uid_hex(n=20):
    return uuid.uuid4().hex[:n]


def random_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    pwd = (
        random.choice(string.ascii_uppercase)
        + random.choice(string.ascii_lowercase)
        + random.choice(string.digits)
        + random.choice("!@#$%")
    )
    pwd += "".join(random.choices(chars, k=length - 4))
    return "".join(random.sample(pwd, len(pwd)))


# ---------------------------------------------------------------------------
# Step 1: API Registration
# ---------------------------------------------------------------------------
def step_register() -> dict:
    """Register account via pure API. Returns session dict or None on error."""
    from api_client import MetaAPI, tempmail_generate, tempmail_otp

    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    password = random_password(16)

    log("STEP 1 — API Registration")
    log(f"  Name: {first} {last}")

    # ── Generate temp email ──
    log("  [1/8] Generating temp email...")
    email, _ = tempmail_generate()
    if not email:
        log("  ✗ Failed to generate temp email")
        return None
    log(f"  ✓ {email}")

    c = MetaAPI(proxy=PROXY_URL)

    # ── Check email availability ──
    log("  [2/8] Checking email availability...")
    try:
        c.check_email(email)
        log("  ✓ Available")
    except Exception as e:
        log(f"  ✗ Check email failed: {e}")
        return None

    # ── Register ──
    log("  [3/8] Registering...")
    reg = c.register(email, password, first, last)
    if "error" in reg:
        log(f"  ✗ Register failed: {reg['error']}")
        return None
    log(f"  ✓ account_id={reg.get('account_id')}")

    # ── Wait for OTP ──
    log("  [4/8] Waiting for OTP (up to 120s)...")
    otp = tempmail_otp(email, 120)
    if not otp:
        log("  ✗ OTP timeout — no code received")
        return None
    log(f"  ✓ OTP: {otp}")

    # ── Verify OTP ──
    log("  [5/8] Verifying OTP...")
    v = c.verify_otp(otp, reg.get("account_id"))
    if not v.get("confirmed"):
        # Retry once
        time.sleep(2)
        v = c.verify_otp(otp, reg.get("account_id"))
    if not v.get("confirmed"):
        log(f"  ✗ OTP verify failed: {v}")
        return None
    log("  ✓ Confirmed")

    # ── OAuth login ──
    log("  [6/8] OAuth login...")
    oauth = c.oauth_login()
    log(f"  ✓ session={oauth.get('has_session')}, actor={oauth.get('actor_id')}")

    # ── Onboarding ──
    log("  [7/8] Onboarding...")
    ok = c.onboard(first, last)
    log(f"  ✓ onboard={ok}")

    # ── Terms ──
    log("  [7/8] Accepting terms...")
    t = c.terms()
    log(f"  ✓ terms={t}")

    # ── Load billing info ──
    log("  [8/8] Loading billing info...")
    billing = c.load_billing()
    log(f"  ✓ team_id={c.team_id}, project_id={c.project_id}, payment={c.payment_account_id}")

    session = {
        "email": email,
        "password": password,
        "first_name": first,
        "last_name": last,
        "actor_id": c.actor_id,
        "account_id": c.account_id,
        "team_id": c.team_id,
        "project_id": c.project_id,
        "payment_account_id": c.payment_account_id,
        "cookies": c.cookies_dict(),
        "fb_dtsg": c.fb_dtsg,
        "lsd": c.lsd,
        "has_session": oauth.get("has_session", False),
    }

    log("  ✅ API registration complete")
    return session


# ---------------------------------------------------------------------------
# Step 2: Browser Card Addition (Playwright + Xvfb)
# ---------------------------------------------------------------------------
# Stealth helpers
try:
    from playwright_stealth import Stealth
    _stealth = Stealth(
        navigator_platform_override="Win32",
        navigator_vendor_override="Google Inc.",
        webgl_vendor_override="Intel Inc.",
        webgl_renderer_override="Intel Iris OpenGL Engine",
        script_logging=False,
    )
    _has_stealth_lib = True
except ImportError:
    _has_stealth_lib = False

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: { isInstalled: false } };
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
    p.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : origQuery(p);
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
const getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return getParam.apply(this, arguments);
};
for (let k in document) { if (k.match(/^cdc_/)) delete document[k]; }
"""


async def apply_stealth(context):
    """Apply stealth patches to Playwright context."""
    if _has_stealth_lib:
        await _stealth.apply_stealth_async(context)
    else:
        await context.add_init_script(STEALTH_JS)


async def dismiss_modals(page, max_rounds=3):
    """Dismiss 'Continue'/'OK'/'Done'/'Save' modals."""
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
                log(f"  [MODAL] Clicked: {els[0]['text']}")
                await asyncio.sleep(2)
            else:
                break
        except Exception as e:
            log(f"  [MODAL] Error: {e}")
            break


async def step_card(session: dict) -> dict:
    """Add payment card via Playwright browser on Xvfb.

    Meta's JS handles ECDH card encryption natively — we just fill the form.
    """
    from playwright.async_api import async_playwright

    result = {"status": "failed"}

    # Ensure DISPLAY for Xvfb
    os.environ["DISPLAY"] = DISPLAY

    # Build cookie list for injection
    cookies = []
    for domain, cs in session.get("cookies", {}).items():
        for name, value in cs.items():
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })

    async with async_playwright() as pw:
        # Launch headed Chromium on Xvfb
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--window-size=1920,1080",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-extensions",
            "--ignore-certificate-errors",
        ]

        log("STEP 2 — Browser Card Addition")
        log("  Launching Chromium (headless=False, Xvfb :99)...")

        browser = await pw.chromium.launch(
            headless=False,
            args=launch_args,
            ignore_default_args=["--enable-automation"],
            proxy={"server": PROXY_URL},
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            java_script_enabled=True,
            ignore_https_errors=True,
        )

        await apply_stealth(context)

        # Inject cookies
        if cookies:
            log(f"  Injecting {len(cookies)} cookies...")
            await context.add_cookies(cookies)

        page = await context.new_page()

        # ── Navigate to billing page ──
        project_id = session.get("project_id")
        team_id = session.get("team_id")
        billing_base = "https://dev.meta.ai/billing"
        if project_id and team_id:
            billing_url = f"{billing_base}?project_id={project_id}&team_id={team_id}"
        else:
            billing_url = billing_base

        log(f"  Navigating to billing: {billing_url}")
        await page.goto(billing_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(5)

        log(f"  Current URL: {page.url}")

        # Check for onboarding redirect
        if "/onboarding" in page.url:
            log("  Onboarding page detected — completing...")
            await _complete_onboarding(page, session.get("first_name", "Brian"), session.get("last_name", "Anderson"))
            await asyncio.sleep(2)
            # Re-navigate to billing
            log(f"  Re-navigating to billing...")
            await page.goto(billing_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(5)

        # Check for geo-block
        body_text = await page.evaluate("document.body?.innerText || ''")
        if "not available" in body_text.lower():
            log("  ✗ Billing geo-blocked!")
            result["error"] = "Billing geo-blocked"
            await browser.close()
            return result

        # Extract team_id / project_id from URL if we didn't have them
        current_url = page.url
        if not team_id:
            import re
            m = re.search(r"team_id=(\d+)", current_url)
            if m:
                team_id = m.group(1)
                session["team_id"] = team_id
                log(f"  Extracted team_id from URL: {team_id}")
        if not project_id:
            import re
            m = re.search(r"project_id=(\d+)", current_url)
            if m:
                project_id = m.group(1)
                session["project_id"] = project_id
                log(f"  Extracted project_id from URL: {project_id}")

        # ── Dismiss modals ──
        await dismiss_modals(page)

        # ── Click "Add payment method" ──
        log("  Looking for 'Add payment method' button...")
        add_btn_found = False
        for attempt in range(3):
            try:
                btn = await page.wait_for_selector(
                    ':is(button, [role="button"]):has-text("Add payment method")',
                    timeout=15000,
                )
                await btn.click()
                add_btn_found = True
                log("  ✓ 'Add payment method' clicked")
                await asyncio.sleep(4)
                break
            except Exception:
                if attempt == 0:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(2)
                log(f"  Retry {attempt+1}/3 finding 'Add payment method'...")

        if not add_btn_found:
            log("  ✗ No 'Add payment method' button found")
            result["error"] = "No add payment button"
            await browser.close()
            return result

        # ── Wait for card form ──
        card_input = await page.query_selector('input[name="cardNumber"]')
        if not card_input:
            await asyncio.sleep(5)
            card_input = await page.query_selector('input[name="cardNumber"]')
        if not card_input:
            log("  ✗ Card form did not load")
            result["error"] = "Card form not loaded"
            await browser.close()
            return result

        # ── Fill card form ──
        card_name = f"{session.get('first_name', 'Brian')} {session.get('last_name', 'Anderson')}"
        log(f"  Filling card form (name: {card_name})...")

        el = await page.query_selector('input[name="firstName"]')
        if el:
            await el.click()
            await el.fill("")
            await el.type(card_name, delay=30)
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

        # ZIP code via JS injection
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

        # ── Capture billing GraphQL response ──
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
        log("  Submitting card...")
        next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
        if next_btn:
            await next_btn.click(force=True)
        else:
            # Fallback
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
        for i in range(30):
            await asyncio.sleep(0.5)
            if billing_response:
                break

        # ── Parse result ──
        if billing_response.get("body"):
            raw = billing_response["body"]
            if raw.startswith("for (;;);"):
                raw = raw[len("for (;;);"):]
            try:
                d = json.loads(raw)
                save_data = d.get("data", {}).get("xfb_billing_save_credit_card", {})
                cc_result = save_data.get("client_result", {})
                cc = save_data.get("credit_card")
                log(f"  Billing status: {cc_result.get('status')} | error: {cc_result.get('error_code')}")
                if cc:
                    log("  ✅ CARD SAVED!")
                    result["status"] = "success"
                else:
                    log(f"  ✗ {cc_result.get('message')}")
                    result["error"] = cc_result.get("message", "Card save failed")
            except Exception as e:
                log(f"  ✗ Parse error: {e}")
                result["error"] = f"Parse error: {e}"
        else:
            body_check = await page.evaluate("document.body?.innerText || ''")
            if "couldn't save" in body_check.lower():
                log("  ✗ Card save failed (trust token issue?)")
                result["error"] = "Card save failed"
            elif "temporarily blocked" in body_check.lower():
                log("  ✗ Rate limited")
                result["error"] = "Rate limited"
            else:
                log(f"  ⚠ Result unclear: {body_check[:200]}")
                result["error"] = f"Unclear: {body_check[:200]}"

        # ── Update cookies from browser ──
        new_cookies = await context.cookies()
        for ck in new_cookies:
            try:
                domain = ck["domain"]
                name = ck["name"]
                value = ck["value"]
                if domain not in session["cookies"]:
                    session["cookies"][domain] = {}
                session["cookies"][domain][name] = value
            except Exception:
                pass

        await browser.close()

    return result


async def _complete_onboarding(page, first_name: str, last_name: str):
    """Complete onboarding pages if redirected there."""
    for step in range(6):
        try:
            # Fill name fields if present
            input_ids = await page.evaluate("""
                () => {
                    const ids = {first: null, last: null};
                    document.querySelectorAll('label').forEach(l => {
                        const t = (l.innerText || '').trim().toLowerCase();
                        if (l.htmlFor) {
                            if (t.includes('first')) ids.first = l.htmlFor;
                            if (t.includes('last')) ids.last = l.htmlFor;
                        }
                    });
                    return ids;
                }
            """)
            if input_ids.get("first"):
                inp = page.locator(f"#{input_ids['first']}")
                await inp.click()
                await inp.press_sequentially(first_name, delay=50)
            if input_ids.get("last"):
                inp = page.locator(f"#{input_ids['last']}")
                await inp.click()
                await inp.press_sequentially(last_name, delay=50)

            # Click submit button
            clicked = await page.evaluate("""
                () => {
                    const targets = ['Get started', 'Continue', 'Next', 'Accept', 'Agree', 'Done', 'Finish', 'Submit'];
                    const allEls = document.querySelectorAll('button, div[role="button"], a[role="button"]');
                    for (const el of allEls) {
                        const t = (el.innerText || '').trim();
                        if (targets.includes(t) && el.offsetParent !== null && el.getBoundingClientRect().height > 20) {
                            el.click();
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log(f"  [ONBOARDING] Step {step+1}: Clicked '{clicked}'")
                await asyncio.sleep(4)
            else:
                await asyncio.sleep(2)
                if "/onboarding" not in page.url:
                    return
                break
        except Exception as e:
            log(f"  [ONBOARDING] Error at step {step+1}: {e}")
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Step 3: API Key Creation (via API)
# ---------------------------------------------------------------------------
def step_api_key(session: dict) -> str:
    """Create API key via GraphQL. Returns access_token or empty string."""
    from api_client import MetaAPI

    log("STEP 3 — API Key Creation")

    c = MetaAPI(proxy=PROXY_URL)

    # Restore session cookies
    for domain, cs in session.get("cookies", {}).items():
        for name, value in cs.items():
            try:
                c.s.cookies.set(name, value, domain=domain)
            except Exception:
                pass

    # Restore session state
    c.actor_id = session.get("actor_id", "0")
    c.account_id = session.get("account_id")
    c.team_id = session.get("team_id")
    c.payment_account_id = session.get("payment_account_id")
    c.fb_dtsg = session.get("fb_dtsg")
    c.lsd = session.get("lsd")

    # Load dev page to refresh tokens if needed
    if not c.fb_dtsg or not c.lsd:
        log("  Refreshing tokens from dev.meta.ai...")
        try:
            c._load_dev_page()
        except Exception:
            pass

    log(f"  actor_id={c.actor_id}, team_id={c.team_id}")
    ak = c.create_api_key()

    if ak.get("success"):
        token = ak.get("access_token", "")
        log(f"  ✅ API key created: {token[:30]}...")
        return token
    else:
        log(f"  ✗ API key failed: {ak.get('error')}")
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Meta AI Unified Registration Bot (VPS/Xvfb)")
    parser.add_argument("--no-card", action="store_true", help="Skip billing/card step")
    parser.add_argument("--no-apikey", action="store_true", help="Skip API key creation")
    args = parser.parse_args()

    log("=" * 60)
    log("Meta AI Unified Registration Bot")
    log(f"  Proxy: {PROXY_URL}")
    log(f"  Display: {DISPLAY}")
    log(f"  Card: {'SKIP' if args.no_card else 'YES'}")
    log(f"  API Key: {'SKIP' if args.no_apikey else 'YES'}")
    log("=" * 60)

    # ── Step 1: API Registration ──
    session = step_register()
    if not session:
        log("✗ Registration failed — aborting")
        print(json.dumps({"status": "error", "step": "register", "error": "Registration failed"}, indent=2))
        sys.exit(1)

    # ── Step 2: Browser Card Addition ──
    card_ok = False
    if not args.no_card:
        try:
            card_result = asyncio.run(step_card(session))
            card_ok = card_result.get("status") == "success"
            if not card_ok:
                log(f"  ⚠ Card step: {card_result.get('error', 'unknown')}")
        except Exception as e:
            log(f"  ✗ Card step exception: {e}")
    else:
        log("STEP 2 — Skipped (--no-card)")

    # ── Step 3: API Key ──
    api_key = ""
    if not args.no_apikey:
        try:
            api_key = step_api_key(session)
        except Exception as e:
            log(f"  ✗ API key step exception: {e}")
    else:
        log("STEP 3 — Skipped (--no-apikey)")

    # ── Final Output ──
    result = {
        "email": session["email"],
        "password": session["password"],
        "cookies": session["cookies"],
        "api_key": api_key,
        "team_id": session.get("team_id", ""),
        "project_id": session.get("project_id", ""),
    }

    # Save to file
    outfile = os.path.join(OUTPUT_DIR, f"account_{int(time.time())}.json")
    with open(outfile, "w") as f:
        json.dump(result, f, indent=2)
    log(f"\nSaved: {outfile}")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
