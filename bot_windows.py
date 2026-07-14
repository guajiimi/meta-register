#!/usr/bin/env python3
"""
Meta AI (dev.meta.ai) account auto-registration bot — Windows/Playwright edition.

Uses Playwright Chromium with stealth patches (no Camoufox, no playwright-extra).
Designed for Windows with real TPM for platform trust tokens.

Flow: Register → OTP → Onboarding → Billing → API Key → JSON output

Usage:
    python bot_windows.py register --count 1
    python bot_windows.py register --count 3 --headless
    python bot_windows.py register --no-billing --no-apikey
"""

import asyncio
import argparse
import email.utils as email_utils
import imaplib
import json
import os
import random
import re
import string
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASS = os.getenv("IMAP_PASS", "")
BASE_GMAIL = os.getenv("BASE_GMAIL", "").strip()
PROXY_URL = os.getenv("PROXY_URL", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(SCRIPT_DIR / "data" / "output")))
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", str(SCRIPT_DIR / "data" / "screenshots")))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Card details
CARD_NUMBER = "4889501032758307"
CARD_EXPIRY = "08/27"
CARD_CVV = "424"
CARD_ZIP = "90001"
CARD_NAME_TEMPLATE = "{first} {last}"

# Realistic name pools
FIRST_NAMES = [
    "James", "Michael", "Robert", "David", "William", "Joseph", "Thomas", "Christopher",
    "Daniel", "Matthew", "Anthony", "Mark", "Steven", "Paul", "Andrew", "Joshua",
    "Kenneth", "Kevin", "Brian", "George", "Timothy", "Ronald", "Edward", "Jason",
    "Sarah", "Jessica", "Jennifer", "Amanda", "Ashley", "Stephanie", "Nicole", "Elizabeth",
    "Heather", "Megan", "Rachel", "Lauren", "Amber", "Brittany", "Danielle", "Melissa",
    "Emily", "Samantha", "Kayla", "Courtney", "Rebecca", "Laura", "Kimberly", "Amy",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def random_name():
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def random_email(first: str, last: str) -> str:
    """Generate a unique email using Gmail dot-trick or fallback domain."""
    if BASE_GMAIL and "@gmail.com" in BASE_GMAIL.lower():
        local, domain = BASE_GMAIL.split("@", 1)
        chars = [c for c in local if c != "."]
        gaps = len(chars) - 1
        while True:
            mask = [random.random() < 0.5 for _ in range(gaps)]
            if any(mask):
                break
        out = chars[0]
        for i, c in enumerate(chars[1:]):
            if mask[i]:
                out += "."
            out += c
        return f"{out}@{domain}"
    # Fallback
    sep = random.choice([".", "_", ""])
    num = random.randint(1, 999)
    user = f"{first.lower()}{sep}{last.lower()}{num}"
    return f"{user}@gmail.com"


def random_birthday() -> tuple:
    """Return (month_name, day_str, year_str) for age 25-35."""
    today = datetime.now()
    age = random.randint(25, 35)
    bd = today - timedelta(days=age * 365 + random.randint(0, 364))
    return bd.strftime("%B"), str(bd.day), str(bd.year)


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


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# IMAP OTP reader
# ---------------------------------------------------------------------------
def fetch_otp(email_addr: str, timeout: int = 120, poll_interval: int = 5,
              since_ts: float | None = None) -> str | None:
    """Poll IMAP for Meta verification code."""
    log(f"  [OTP] Waiting for verification email at {email_addr} (timeout {timeout}s)...")
    deadline = time.time() + timeout
    if since_ts is None:
        since_ts = time.time()
    # Buffer: subtract 30s to avoid edge cases with clock drift
    since_ts_buffered = since_ts - 30

    while time.time() < deadline:
        try:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            imap.login(IMAP_USER, IMAP_PASS)
            imap.select("INBOX")

            since_date = datetime.fromtimestamp(since_ts_buffered).strftime("%d-%b-%Y")
            _, msg_nums = imap.search(
                None,
                f'(UNSEEN) (OR FROM "notification@email.meta.com" '
                f'FROM "notification@facebookmail.com") (SINCE {since_date})'
            )
            if not msg_nums[0]:
                # Fallback: All Mail
                try:
                    imap.select('"[Gmail]/All Mail"')
                    _, msg_nums = imap.search(
                        None,
                        f'(UNSEEN) (OR FROM "notification@email.meta.com" '
                        f'FROM "notification@facebookmail.com") (SINCE {since_date})'
                    )
                except Exception:
                    pass

            if msg_nums[0]:
                for num in reversed(msg_nums[0].split()):
                    _, data = imap.fetch(num, "(BODY[HEADER.FIELDS (SUBJECT DATE)])")
                    header = data[0][1].decode(errors="ignore")

                    date_match = re.search(r"Date:\s*(.+)", header)
                    if date_match:
                        raw_date = date_match.group(1).strip()
                        email_ts = None
                        try:
                            email_date = email_utils.parsedate_to_datetime(raw_date)
                            email_ts = email_date.timestamp()
                        except Exception:
                            # Fallback: manual parse for common formats
                            try:
                                # "Tue, 14 Jul 2026 08:06:15 -0700"
                                cleaned = re.sub(r'\s*\(.*?\)\s*$', '', raw_date)
                                parsed = email_utils.parsedate_tz(cleaned)
                                if parsed:
                                    email_ts = email_utils.mktime_tz(parsed)
                            except Exception:
                                pass

                        if email_ts is not None:
                            if email_ts < since_ts_buffered:
                                log(f"  [OTP] Skipping old email from {raw_date[:40]}")
                                continue
                        else:
                            # Date parsing failed completely — SKIP to be safe
                            log(f"  [OTP] SKIP: unparseable Date: {raw_date[:40]}")
                            continue

                    m = re.search(r"(\d{5,8})", header)
                    if m:
                        code = m.group(1)
                        imap.store(num, "+FLAGS", "\\Seen")
                        imap.logout()
                        log(f"  [OTP] Got code: {code}")
                        return code

            imap.logout()
        except Exception as e:
            log(f"  [OTP] IMAP error: {e}")

        time.sleep(poll_interval)

    log("  [OTP] Timeout waiting for code")
    return None


# ---------------------------------------------------------------------------
# Stealth helpers
# ---------------------------------------------------------------------------
try:
    from playwright_stealth import Stealth
    _stealth = Stealth(
        navigator_platform_override="Win32",
        navigator_vendor_override="Google Inc.",
        webgl_vendor_override="Intel Inc.",
        webgl_renderer_override="Intel Iris OpenGL Engine",
        script_logging=False,
    )

    async def apply_stealth(context):
        """Apply stealth patches using playwright_stealth library."""
        await _stealth.apply_stealth_async(context)

    log("  [STEALTH] Using playwright_stealth library")
except ImportError:
    # Fallback: inline stealth patches
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
        """Apply inline stealth patches."""
        await context.add_init_script(STEALTH_JS)

    log("  [STEALTH] Using inline stealth patches (playwright_stealth not installed)")


# ---------------------------------------------------------------------------
# Human-like interaction helpers
# ---------------------------------------------------------------------------
async def human_delay(min_s=0.3, max_s=1.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_type_text(page, selector: str, text: str, delay_range=(30, 80)):
    """Type text into an element with human-like delays."""
    el = await page.wait_for_selector(selector, timeout=10000)
    await el.click()
    await human_delay(0.1, 0.3)
    await el.fill("")
    for ch in text:
        await el.type(ch, delay=random.randint(*delay_range))
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.2, 0.6))
    return el


async def safe_click(page, selector: str, timeout: int = 10000):
    """Wait for element and click it."""
    el = await page.wait_for_selector(selector, timeout=timeout)
    await el.scroll_into_view_if_needed()
    await human_delay(0.2, 0.6)
    await el.click()
    return el


async def select_combobox_option(page, combobox, option_text: str, timeout: int = 10000):
    """Click a React div-based combobox and select an option by visible text."""
    if isinstance(combobox, str):
        cb = await page.wait_for_selector(combobox, timeout=timeout)
    else:
        cb = combobox
    await cb.click()
    await asyncio.sleep(random.uniform(0.3, 0.8))
    await asyncio.sleep(0.4)

    # Find visible listbox
    options = []
    listboxes = await page.query_selector_all('[role="listbox"]')
    for lb in listboxes:
        if await lb.get_attribute("aria-hidden") == "true":
            continue
        if not await lb.is_visible():
            continue
        options = await lb.query_selector_all('[role="option"]')
        if options:
            break

    for opt in options:
        text = (await opt.inner_text()).strip()
        if text == option_text or option_text.lower() == text.lower():
            await opt.scroll_into_view_if_needed()
            await opt.click()
            await asyncio.sleep(random.uniform(0.2, 0.5))
            return True

    # Fallback: keyboard search
    await cb.press_sequentially(option_text[:3], delay=80)
    await asyncio.sleep(0.5)
    options = await page.query_selector_all('[role="listbox"] [role="option"]')
    for opt in options:
        text = await opt.inner_text()
        if option_text.lower() in text.lower():
            await opt.click()
            return True

    log(f"  [WARN] Could not find option '{option_text}' in combobox")
    return False


async def dismiss_modals(page, max_rounds=5):
    """Dismiss any 'Continue'/'OK' modals that Meta shows."""
    for _ in range(max_rounds):
        els = await page.evaluate("""
            Array.from(document.querySelectorAll('*')).filter(el => {
                const t = el.innerText?.trim();
                return (t === 'Continue' || t === 'OK' || t === 'Get started' || t === 'Done') &&
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


async def take_screenshot(page, label: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"{label}_{ts}.png"
    await page.screenshot(path=str(path), full_page=True)
    log(f"  [SCREENSHOT] {path}")
    return str(path)


# ---------------------------------------------------------------------------
# Browser launcher
# ---------------------------------------------------------------------------
async def launch_browser(playwright, headless=False):
    """Launch Playwright Chromium with stealth args."""
    launch_args = [
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-infobars',
        '--disable-dev-shm-usage',
        '--window-size=1920,1080',
        '--disable-gpu',
        '--disable-software-rasterizer',
        '--disable-extensions',
        '--ignore-certificate-errors',
    ]

    launch_kwargs = dict(
        headless=headless,
        args=launch_args,
        ignore_default_args=['--enable-automation'],
    )

    if PROXY_URL:
        launch_kwargs['proxy'] = {"server": PROXY_URL}

    browser = await playwright.chromium.launch(**launch_kwargs)

    # Create context with realistic fingerprint
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

    # Apply stealth patches
    await apply_stealth(context)

    return browser, context


# ---------------------------------------------------------------------------
# Registration flow
# ---------------------------------------------------------------------------
async def step_register(page, email_addr, password, first_name, last_name,
                        month, day, year) -> dict:
    """Navigate to dev.meta.ai and register a new account via OAuth."""
    result = {"status": "failed"}

    # Step 1: Navigate to dev.meta.ai (NOT auth.meta.com)
    # The OAuth flow starts from dev.meta.ai → "Use mobile number or email"
    # → redirects to auth.meta.com for registration
    # → redirects back to dev.meta.ai/?project_id=X&team_id=Y after success
    log("  [1] Navigating to dev.meta.ai...")
    await page.goto("https://dev.meta.ai/", wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(random.uniform(3, 6))
    log(f"  [1] Current URL: {page.url}")
    await take_screenshot(page, "01_landing")

    # Step 2: Click "Use mobile number or email"
    log("  [2] Looking for 'Use mobile number or email' button...")
    selectors = [
        'div[role="button"]:has-text("Use mobile number or email")',
        'div[role="button"]:has-text("mobile number")',
        'div[role="button"]:has-text("email")',
        'text="Use mobile number or email"',
        'button:has-text("email")',
    ]
    clicked = False
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=5000, state="visible")
            if el and await el.is_visible():
                box = await el.bounding_box()
                if box and box.get("height", 0) >= 20:
                    await el.evaluate("el => el.click()")
                    clicked = True
                    log(f"  [2] Clicked: {sel}")
                    break
        except Exception:
            continue

    if not clicked:
        email_field = await page.query_selector('input[name="email"]')
        if not email_field:
            await take_screenshot(page, "02_no_button")
            result["error"] = "Could not find 'use email' button or email field"
            return result

    await asyncio.sleep(random.uniform(1, 2))
    try:
        await page.wait_for_selector(
            'input[autocomplete="username"], input[inputmode="email"], '
            'input:not([type="password"]):not([type="hidden"])',
            timeout=8000, state="visible"
        )
    except Exception:
        pass

    reg_start_ts = time.time()

    # Step 3: Enter email
    log(f"  [3] Entering email: {email_addr}")
    email_selectors = [
        'input[autocomplete="username"]',
        'input[inputmode="email"]',
        'input:not([type="password"]):not([type="hidden"]):not([type="submit"])',
    ]
    email_filled = False
    for sel in email_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=3000)
            if el:
                await el.click()
                await asyncio.sleep(0.3)
                await el.fill("")
                for ch in email_addr:
                    await el.type(ch, delay=random.randint(30, 80))
                email_filled = True
                break
        except Exception:
            continue

    if not email_filled:
        await take_screenshot(page, "03_no_email_field")
        result["error"] = "Could not find email input field"
        return result

    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Click Continue
    log("  [3] Clicking Continue...")
    continue_selectors = [
        'div[role="button"]:has-text("Continue")',
        'div[role="button"]:has-text("Next")',
        'button:has-text("Continue")',
    ]
    for _ in range(20):
        for sel in continue_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=1000, state="visible")
                if el and await el.is_visible():
                    dis = await el.get_attribute("aria-disabled")
                    if dis != "true":
                        await el.evaluate("el => el.click()")
                        log("  [3] Continue clicked (enabled)")
                        break
            except Exception:
                continue
        else:
            await asyncio.sleep(0.5)
            continue
        break
    else:
        log("  [3] WARN: Continue button never enabled, force click")
        try:
            el = await page.query_selector('div[role="button"]:has-text("Continue")')
            if el:
                await el.evaluate("el => el.click()")
        except Exception:
            pass

    await asyncio.sleep(random.uniform(2, 5))
    await take_screenshot(page, "04_after_email")

    # Step 4: Handle account creation form
    page_text = await page.inner_text("body")

    if "create" in page_text.lower() and "account" in page_text.lower():
        log("  [4] Account creation form detected!")

        # Birthday
        log(f"  [4] Setting birthday: {month} {day}, {year}")
        month_cbs = await page.query_selector_all('div[role="combobox"]')
        if len(month_cbs) >= 3:
            await select_combobox_option(page, month_cbs[0], month)
            await human_delay(0.3, 0.7)
            await select_combobox_option(page, month_cbs[1], day)
            await human_delay(0.3, 0.7)
            await select_combobox_option(page, month_cbs[2], year)
            await human_delay(0.3, 0.7)
        else:
            # Fallback: aria-label based
            for label_text, value in [("month", month), ("day", day), ("year", year)]:
                sel = f'div[role="combobox"][aria-label*="{label_text}" i]'
                try:
                    await select_combobox_option(page, sel, value)
                except Exception:
                    pass
                await human_delay(0.3, 0.7)

        # Name fields
        log(f"  [4] Entering name: {first_name} {last_name}")
        for sel, val in [
            ('input[name="firstname"]', first_name),
            ('input[name="lastName"]', last_name),
            ('input[aria-label*="first" i]', first_name),
            ('input[aria-label*="last" i]', last_name),
        ]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await el.fill("")
                    for ch in val:
                        await el.type(ch, delay=random.randint(30, 80))
                    await asyncio.sleep(0.2)
            except Exception:
                pass

        # Password
        log("  [4] Entering password...")
        for sel in [
            'input[name="reg_passwd__"]',
            'input[name="password"]',
            'input[type="password"]',
            'input[name="new_password"]',
        ]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await el.fill("")
                    for ch in password:
                        await el.type(ch, delay=random.randint(30, 80))
                    break
            except Exception:
                continue

        await human_delay(0.5, 1.5)
        await take_screenshot(page, "05_filled_form")

        # Click Confirm
        log("  [4] Clicking Confirm...")
        confirm_selectors = [
            'div[role="button"]:has-text("Confirm")',
            'div[role="button"]:has-text("Sign Up")',
            'div[role="button"]:has-text("Register")',
            'div[role="button"]:has-text("Create")',
            'button:has-text("Confirm")',
        ]
        url_before = page.url
        for sel in confirm_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=3000, state="visible")
                if el and await el.is_visible():
                    box = await el.bounding_box()
                    if box and box.get("height", 0) >= 20:
                        await el.evaluate("el => el.click()")
                        log(f"  [4] Clicked: {sel}")
                        break
            except Exception:
                continue

        # Wait for page reaction
        for _ in range(10):
            await asyncio.sleep(0.5)
            if page.url != url_before:
                break
            otp_hint = await page.query_selector(
                'input[aria-label*="code" i], input[aria-label*="otp" i]'
            )
            if otp_hint:
                break

        await asyncio.sleep(random.uniform(3, 6))
        await take_screenshot(page, "06_after_confirm")

        # --- Wait for OTP ---
        log("  [5] Waiting for OTP verification...")
        otp_code = fetch_otp(email_addr, timeout=120, since_ts=reg_start_ts)
        if not otp_code:
            result["error"] = "OTP timeout - no code received"
            await take_screenshot(page, "07_otp_timeout")
            return result

        log(f"  [5] Entering OTP: {otp_code}")
        otp_selectors = [
            'input[aria-label*="code" i]',
            'input[aria-label*="otp" i]',
            'input[aria-label*="verification" i]',
            'input[inputmode="numeric"]',
            'input[type="tel"]',
            'input[type="number"]',
            'input[name="code"]',
        ]
        otp_filled = False
        for sel in otp_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                if el:
                    await el.click()
                    await asyncio.sleep(0.3)
                    await el.fill(otp_code)
                    otp_filled = True
                    log(f"  [5] OTP filled via {sel}")
                    break
            except Exception:
                continue

        if not otp_filled:
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                try:
                    val = await inp.get_attribute("value") or ""
                    itype = await inp.get_attribute("type") or ""
                    vis = (await inp.bounding_box()) is not None
                    if vis and not val and itype in ("text", "tel", "number", ""):
                        await inp.fill(otp_code)
                        otp_filled = True
                        break
                except Exception:
                    continue

        if not otp_filled:
            result["error"] = "Could not find OTP input field"
            await take_screenshot(page, "07_no_otp_field")
            return result

        await asyncio.sleep(random.uniform(1, 3))

        # Click Next/Continue after OTP
        for sel in [
            'div[role="button"]:has-text("Next")',
            'div[role="button"]:has-text("Continue")',
            'div[role="button"]:has-text("Confirm")',
            'button:has-text("Next")',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                if el:
                    for _ in range(20):
                        dis = await el.get_attribute("aria-disabled")
                        if dis != "true":
                            break
                        await asyncio.sleep(0.5)
                    box = await el.bounding_box()
                    if box and box.get("height", 0) >= 20:
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await el.click(force=True)
                        log(f"  [5] Post-OTP button clicked")
                        break
            except Exception:
                continue

        await asyncio.sleep(random.uniform(3, 6))
        await take_screenshot(page, "08_after_otp")

    elif ("check your email" in page_text.lower()
          or "enter the code" in page_text.lower()
          or "verification code" in page_text.lower()):
        # Direct OTP after email entry
        log("  [4] OTP screen detected after email entry")
        otp_code = fetch_otp(email_addr, timeout=120, since_ts=reg_start_ts)
        if not otp_code:
            result["error"] = "OTP timeout after email entry"
            return result

        log(f"  [4] Entering OTP: {otp_code}")
        otp_selectors = [
            'input[aria-label*="code" i]',
            'input[inputmode="numeric"]',
            'input[type="tel"]',
            'input[type="number"]',
        ]
        for sel in otp_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                if el:
                    await el.click()
                    await el.fill(otp_code)
                    break
            except Exception:
                continue

        await asyncio.sleep(random.uniform(1, 3))
        for sel in [
            'div[role="button"]:has-text("Next")',
            'div[role="button"]:has-text("Continue")',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                if el:
                    await el.click(force=True)
                    break
            except Exception:
                continue

        await asyncio.sleep(random.uniform(3, 6))
        await take_screenshot(page, "08_after_otp_entry")

    elif "password" in page_text.lower() and "login" in page_text.lower():
        result["error"] = "Account may already exist (login prompt)"
        await take_screenshot(page, "04_login_prompt")
        return result
    else:
        log("  [4] Unknown state after email entry")
        await take_screenshot(page, "04_unknown_state")
        result["error"] = "Unknown state after email entry"
        return result

    # Step 5.5: Handle post-login dialogs
    log("  [5.5] Checking for post-login dialogs...")
    dialog_progress = False
    for _round in range(2):
        pre_url = page.url
        round_clicked = False
        for text in ["Save", "OK", "Continue", "Yes", "Allow", "Confirm", "Next", "Done"]:
            sel = f'div[role="button"]:has-text("{text}")'
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    box = await el.bounding_box()
                    if box and box["height"] > 20:
                        await el.click(force=True)
                        log(f"  [5.5] Clicked: {text}")
                        round_clicked = True
                        await asyncio.sleep(2)
            except Exception:
                continue
        await asyncio.sleep(2)
        if round_clicked:
            dialog_progress = True
        # If URL didn't change after clicking dialogs, likely stuck on auth page
        if "auth.meta.com" in page.url and page.url == pre_url and round_clicked:
            log("  [5.5] Still on auth.meta.com after clicking dialog — OTP may have failed")
            break
        if not round_clicked:
            break  # No buttons found, no point continuing

    # Check if we actually succeeded: llm_sess cookie or landed on dev.meta.ai
    current_url = page.url
    try:
        page_cookies = {c["name"]: c["value"] for c in await page.context.cookies()}
    except Exception:
        page_cookies = {}
    if "llm_sess" in page_cookies or "dev.meta.ai" in current_url:
        result["status"] = "success"
    elif "auth.meta.com" in current_url:
        result["status"] = "failed"
        result["error"] = "Still on auth.meta.com after OTP — likely wrong code"
    else:
        result["status"] = "success"
    return result


# ---------------------------------------------------------------------------
# Post-registration: wait for redirect, extract cookies
# ---------------------------------------------------------------------------
async def wait_for_redirect(page, context, timeout=60):
    """Wait for redirect back to dev.meta.ai with project_id & team_id.
    
    After successful registration, Meta OAuth redirects to:
    https://dev.meta.ai/?project_id=XXX&team_id=YYY
    """
    log("  [6] Waiting for OAuth redirect back to dev.meta.ai...")
    cookies = {}
    project_id = None
    team_id = None

    for _ in range(timeout):
        url = page.url
        # Success: redirected back to dev.meta.ai with project params
        if "dev.meta.ai" in url and "project_id" in url:
            log(f"  [6] ✅ Redirected to dev.meta.ai with project params!")
            pm = re.search(r"project_id=(\d+)", url)
            tm = re.search(r"team_id=(\d+)", url)
            if pm:
                project_id = pm.group(1)
            if tm:
                team_id = tm.group(1)
            log(f"  [6] project_id={project_id}, team_id={team_id}")
            break
        # Also accept dev.meta.ai without params (onboarding flow)
        if "dev.meta.ai" in url and "auth.meta.com" not in url:
            log(f"  [6] Redirected to dev.meta.ai (no project params): {url[:80]}")
            break
        await asyncio.sleep(1)
    else:
        log("  [6] Redirect timeout, checking current state...")
        log(f"  [6] Current URL: {page.url[:100]}")

    # Handle any remaining modals ("Save login info?", onboarding, etc.)
    await dismiss_modals(page)

    # Extract ALL cookies from ALL domains
    all_cookies = await context.cookies()
    cookies = {c["name"]: c["value"] for c in all_cookies}

    # Navigate to dev.meta.ai if not already there
    if "dev.meta.ai" not in page.url:
        try:
            await page.goto("https://dev.meta.ai/", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(5)
            all_cookies = await context.cookies()
            cookies = {c["name"]: c["value"] for c in all_cookies}
        except Exception as e:
            log(f"  [6] Navigation error: {e}")

    await dismiss_modals(page)

    # Extract project_id/team_id from current URL if not captured yet
    current_url = page.url
    if not project_id:
        pm = re.search(r"project_id=(\d+)", current_url)
        if pm:
            project_id = pm.group(1)
    if not team_id:
        tm = re.search(r"team_id=(\d+)", current_url)
        if tm:
            team_id = tm.group(1)

    if "llm_sess" in cookies:
        log(f"  [6] Session cookies extracted (llm_sess found): {sorted(cookies.keys())}")
    elif "dev.meta.ai" in page.url:
        log(f"  [6] On dev.meta.ai — registration appears successful. Cookies: {sorted(cookies.keys())}")
    else:
        log(f"  [6] WARN: No session cookies found")

    return cookies, project_id, team_id


# ---------------------------------------------------------------------------
# Billing flow
# ---------------------------------------------------------------------------
async def step_billing(page, context, first_name, last_name) -> dict:
    """Navigate to billing page and add payment card."""
    result = {"status": "failed"}

    log("  [7] Navigating to billing page...")
    await page.goto("https://dev.meta.ai/billing", wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    billing_url = page.url
    log(f"  [7] Billing URL: {billing_url}")
    result["billing_url"] = billing_url

    body = await page.evaluate("document.body?.innerText || ''")
    if "not available" in body.lower():
        log("  [7] ❌ Billing geo-blocked!")
        result["error"] = "Billing geo-blocked"
        await take_screenshot(page, "10_billing_blocked")
        return result

    await dismiss_modals(page)

    # Extract team_id and project_id from URL
    team_match = re.search(r"team_id=(\d+)", billing_url)
    project_match = re.search(r"project_id=(\d+)", billing_url)
    if team_match:
        result["team_id"] = team_match.group(1)
    if project_match:
        result["project_id"] = project_match.group(1)

    # Click "Add payment method"
    try:
        btn = await page.wait_for_selector(
            ':is(button, [role="button"]):has-text("Add payment method")',
            timeout=15000
        )
        await btn.click()
        await asyncio.sleep(4)
    except Exception as e:
        log(f"  [7] No 'Add payment method' button: {e}")
        await take_screenshot(page, "10_no_add_payment")
        result["error"] = "No add payment button"
        return result

    await take_screenshot(page, "11_card_form")

    # Fill card form
    log("  [7] Filling card form...")
    card_name = CARD_NAME_TEMPLATE.format(first=first_name, last=last_name)

    el = await page.query_selector('input[name="firstName"]')
    if el:
        await el.click()
        await el.fill("")
        await el.type(card_name, delay=30)
    await human_delay(0.3, 0.7)

    el = await page.query_selector('input[name="cardNumber"]')
    if el:
        await el.click()
        await el.fill("")
        for ch in CARD_NUMBER:
            await page.keyboard.type(ch, delay=random.randint(30, 60))
    await human_delay(0.3, 0.7)

    el = await page.query_selector('input[name="expiration"]')
    if el:
        await el.click()
        await asyncio.sleep(0.2)
        for ch in CARD_EXPIRY:
            await page.keyboard.type(ch, delay=random.randint(40, 80))
    await human_delay(0.3, 0.7)

    el = await page.query_selector('input[name="securityCode"]')
    if el:
        await el.click()
        await asyncio.sleep(0.2)
        for ch in CARD_CVV:
            await page.keyboard.type(ch, delay=random.randint(40, 80))
    await human_delay(0.3, 0.7)

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

    await take_screenshot(page, "12_card_filled")

    # Capture billing response
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

    # Submit
    log("  [7] Submitting card...")
    next_btn = await page.query_selector(':is(button, [role="button"]):has-text("Next")')
    if next_btn:
        await next_btn.click(force=True)

    await asyncio.sleep(10)

    # Check result
    if billing_response.get("body"):
        raw = billing_response["body"]
        if raw.startswith("for (;;);"):
            raw = raw[len("for (;;);"):]
        try:
            d = json.loads(raw)
            r = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("client_result", {})
            cc = d.get("data", {}).get("xfb_billing_save_credit_card", {}).get("credit_card")
            log(f"  [7] Billing status: {r.get('status')} | error: {r.get('error_code')}")
            if cc:
                log("  [7] ✅ CARD SAVED!")
                result["status"] = "success"
            else:
                log(f"  [7] ❌ {r.get('message')}")
                result["error"] = r.get("message", "Card save failed")
        except Exception as e:
            log(f"  [7] Parse error: {e}")
    else:
        body = await page.evaluate("document.body?.innerText || ''")
        if "couldn't save" in body.lower():
            log(f"  [7] ❌ Card save failed")
            result["error"] = "Card save failed (trust token issue?)"
        elif "temporarily blocked" in body.lower():
            log("  [7] ❌ Rate limited")
            result["error"] = "Rate limited"
        else:
            log(f"  [7] Card submission result unclear: {body[:200]}")

    await take_screenshot(page, "13_billing_result")
    return result


# ---------------------------------------------------------------------------
# API Key flow
# ---------------------------------------------------------------------------
async def step_api_key(page, context) -> dict:
    """Navigate to API keys page and create a key."""
    result = {"status": "failed"}

    log("  [8] Navigating to API keys page...")
    await page.goto("https://dev.meta.ai/api-keys", wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    await dismiss_modals(page)

    body = await page.evaluate("document.body?.innerText || ''")
    log(f"  [8] Page: {body[:200]}")

    # Try to extract team_id and project_id from URL
    api_url = page.url
    team_match = re.search(r"team_id=(\d+)", api_url)
    project_match = re.search(r"project_id=(\d+)", api_url)
    if team_match:
        result["team_id"] = team_match.group(1)
    if project_match:
        result["project_id"] = project_match.group(1)

    # Click "Create API key"
    create_btn = await page.query_selector(
        ':is(button, [role="button"]):has-text("Create API key")'
    )
    if not create_btn:
        log("  [8] No 'Create API key' button found")
        await take_screenshot(page, "14_no_create_key")
        result["error"] = "No Create API key button"
        return result

    disabled = await create_btn.is_disabled()
    if disabled:
        log("  [8] Create API key button disabled (needs payment first?)")
        result["error"] = "API key button disabled"
        return result

    # Click create
    await create_btn.click(force=True)
    await asyncio.sleep(3)

    # Fill key name
    name_input = await page.query_selector('input[type="text"]')
    if name_input:
        await name_input.fill("default")
        await human_delay(0.3, 0.7)

        # Click Create button in dialog
        submit = await page.query_selector(
            ':is(button, [role="button"]):has-text("Create")'
        )
        if submit:
            await submit.click(force=True)
            await asyncio.sleep(5)

    await take_screenshot(page, "15_apikey_result")

    # Extract API key from page
    body = await page.evaluate("document.body?.innerText || ''")
    log(f"  [8] Result: {body[:300]}")

    # Try multiple extraction methods
    api_key = None

    # Method 1: Look for AAI... pattern (Meta API keys start with AAI)
    aai_match = re.search(r'(AAI[A-Za-z0-9_-]{20,})', body)
    if aai_match:
        api_key = aai_match.group(1)

    # Method 2: Look for Bearer tokens
    if not api_key:
        bearer_match = re.search(r'(eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})', body)
        if bearer_match:
            api_key = bearer_match.group(1)

    # Method 3: Look for long alphanumeric strings in code/pre/span elements
    if not api_key:
        key_els = await page.evaluate("""
            Array.from(document.querySelectorAll('[class*="key"], [data-testid*="key"], code, pre, span')).filter(el => {
                const t = el.innerText || '';
                return t.startsWith('AAI') || t.startsWith('Bearer ') || t.startsWith('eyJ') ||
                       (t.length > 30 && /^[A-Za-z0-9_-]+$/.test(t));
            }).map(el => el.innerText.trim())
        """)
        if key_els:
            api_key = key_els[0].replace("Bearer ", "")

    # Method 4: Check input fields (sometimes key is in a copyable input)
    if not api_key:
        inputs = await page.query_selector_all('input[readonly], input[value]')
        for inp in inputs:
            val = await inp.get_attribute("value") or ""
            if val.startswith("AAI") or (len(val) > 30 and val.startswith("eyJ")):
                api_key = val
                break

    if api_key:
        log(f"  [8] ✅ API Key found: {api_key[:20]}...")
        result["status"] = "success"
        result["api_key"] = api_key
    else:
        log("  [8] ⚠️ Could not extract API key from page")
        result["error"] = "Could not extract API key"

    return result


# ---------------------------------------------------------------------------
# Single registration + full flow
# ---------------------------------------------------------------------------
async def register_one(context, email_addr, password, first_name, last_name,
                       month, day, year, do_billing=True, do_apikey=True) -> dict:
    """Attempt full flow: register → OTP → billing → API key."""
    result = {
        "email": email_addr,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "birthday": f"{month} {day}, {year}",
        "status": "failed",
        "timestamp": datetime.now().isoformat(),
    }

    page = await context.new_page()
    try:
        # Registration
        reg_result = await step_register(
            page, email_addr, password, first_name, last_name, month, day, year
        )

        if reg_result.get("error"):
            result["error"] = reg_result["error"]
            return result

        # Extract cookies + project_id/team_id from redirect URL
        cookies, project_id, team_id = await wait_for_redirect(page, context)
        result["cookies"] = cookies
        if project_id:
            result["project_id"] = project_id
        if team_id:
            result["team_id"] = team_id

        if "c_user" in cookies:
            result["status"] = "registered"
            result["c_user"] = cookies.get("c_user", "")
            log(f"  ✅ REGISTERED! c_user={result['c_user']}")
        elif "llm_sess" in cookies:
            result["status"] = "registered"
            log(f"  ✅ REGISTERED! llm_sess found")
        elif "dev.meta.ai" in page.url:
            result["status"] = "registered"
            log(f"  ✅ REGISTERED! on dev.meta.ai (no llm_sess/c_user but landed correctly)")
        else:
            result["status"] = "failed"
            result["error"] = "Registration unconfirmed — no llm_sess cookie and not on dev.meta.ai"
            log(f"  ❌ Registration unconfirmed: cookies={sorted(cookies.keys())}, url={page.url[:80]}")

        await take_screenshot(page, "09_registered")

        # Billing
        if do_billing:
            billing_result = await step_billing(page, context, first_name, last_name)
            if billing_result.get("team_id"):
                result["team_id"] = billing_result["team_id"]
            if billing_result.get("project_id"):
                result["project_id"] = billing_result["project_id"]
            if billing_result.get("billing_url"):
                result["billing_url"] = billing_result["billing_url"]

            if billing_result.get("status") == "success":
                result["status"] = "billing_added"
                log("  ✅ BILLING ADDED!")
            else:
                result["billing_error"] = billing_result.get("error", "Unknown")
                log(f"  ⚠️ Billing: {result['billing_error']}")
        else:
            log("  [SKIP] Billing step skipped")

        # API Key
        if do_apikey:
            api_result = await step_api_key(page, context)
            if api_result.get("api_key"):
                result["api_key"] = api_result["api_key"]
            if api_result.get("team_id") and "team_id" not in result:
                result["team_id"] = api_result["team_id"]
            if api_result.get("project_id") and "project_id" not in result:
                result["project_id"] = api_result["project_id"]

            if api_result.get("status") == "success":
                result["status"] = "complete"
                log("  ✅ API KEY CREATED!")
            else:
                result["api_key_error"] = api_result.get("error", "Unknown")
                log(f"  ⚠️ API Key: {result['api_key_error']}")
        else:
            log("  [SKIP] API key step skipped")

        # Final refresh of cookies
        final_cookies = await context.cookies()
        result["cookies"] = {c["name"]: c["value"] for c in final_cookies}

    except Exception as e:
        result["error"] = str(e)
        log(f"  [ERROR] {e}")
        try:
            await take_screenshot(page, "error")
        except Exception:
            pass
    finally:
        await page.close()

    return result


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
async def run_registrations(count: int, headless: bool = False,
                            do_billing: bool = True, do_apikey: bool = True):
    """Main registration loop."""
    from playwright.async_api import async_playwright

    results = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"accounts_{ts}.json"
    full_file = OUTPUT_DIR / f"accounts_{ts}_full.json"

    log(f"\n{'=' * 60}")
    log(f"Meta Account Registration Bot (Playwright/Windows)")
    log(f"Target: {count} account(s)")
    log(f"Headless: {headless}")
    log(f"Billing: {do_billing}")
    log(f"API Key: {do_apikey}")
    log(f"Output: {output_file}")
    log(f"{'=' * 60}\n")

    async with async_playwright() as playwright:
        for i in range(count):
            first, last = random_name()
            email_addr = random_email(first, last)
            password = random_password()
            month, day, year = random_birthday()

            log(f"\n[{i + 1}/{count}] Registering: {first} {last} <{email_addr}>")
            log(f"  Birthday: {month} {day}, {year}")

            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    browser, context = await launch_browser(playwright, headless=headless)
                    try:
                        result = await register_one(
                            context, email_addr, password, first, last,
                            month, day, year,
                            do_billing=do_billing,
                            do_apikey=do_apikey,
                        )
                    finally:
                        await context.close()
                        await browser.close()

                    if result["status"] in ("complete", "billing_added", "registered") or attempt == max_retries:
                        results.append(result)
                        break
                    else:
                        log(f"  Retry {attempt + 1}/{max_retries}...")
                        email_addr = random_email(first, last)
                        await asyncio.sleep(random.uniform(3, 8))

                except Exception as e:
                    log(f"  [FATAL] Browser error: {e}")
                    if attempt == max_retries:
                        results.append({
                            "email": email_addr,
                            "status": "failed",
                            "error": str(e),
                            "timestamp": datetime.now().isoformat(),
                        })
                    await asyncio.sleep(random.uniform(5, 10))

            # Delay between registrations
            if i < count - 1:
                delay = random.uniform(10, 30)
                log(f"\n  Waiting {delay:.1f}s before next registration...")
                await asyncio.sleep(delay)

    # Save results
    # Summary (no verbose cookies)
    summary_data = []
    for r in results:
        entry = {k: v for k, v in r.items() if k != "cookies"}
        entry["has_session"] = r.get("status") in ("success", "registered", "billing_added", "complete")
        entry["cookie_keys"] = list(r.get("cookies", {}).keys())
        summary_data.append(entry)

    with open(output_file, "w") as f:
        json.dump(summary_data, f, indent=2)

    # Full data with cookies
    with open(full_file, "w") as f:
        json.dump(results, f, indent=2)

    success = sum(1 for r in results if r["status"] in ("registered", "billing_added", "complete"))
    log(f"\n{'=' * 60}")
    log(f"Done! {success}/{count} registrations succeeded")
    log(f"Summary: {output_file}")
    log(f"Full data: {full_file}")
    log(f"{'=' * 60}\n")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Meta AI account registration bot (Playwright/Windows)"
    )
    sub = parser.add_subparsers(dest="command")

    reg = sub.add_parser("register", help="Register accounts")
    reg.add_argument("--count", "-c", type=int, default=1, help="Number of accounts")
    reg.add_argument("--headless", action="store_true", default=False,
                     help="Run headless (default: headed for trust tokens)")
    reg.add_argument("--headed", action="store_true", default=True,
                     help="Run headed (default)")
    reg.add_argument("--no-billing", action="store_true", default=False,
                     help="Skip billing/payment step")
    reg.add_argument("--no-apikey", action="store_true", default=False,
                     help="Skip API key creation step")

    args = parser.parse_args()

    if args.command == "register":
        headless = args.headless
        do_billing = not args.no_billing
        do_apikey = not args.no_apikey
        asyncio.run(run_registrations(args.count, headless=headless,
                                      do_billing=do_billing, do_apikey=do_apikey))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
