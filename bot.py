#!/usr/bin/env python3
"""
Meta (auth.meta.ai) account auto-registration bot.
Uses Camoufox browser automation + IMAP OTP reading.
"""

import asyncio
import argparse
import email
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

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASS = os.getenv("IMAP_PASS", "")
EMAIL_DOMAINS = [d.strip() for d in os.getenv("EMAIL_DOMAINS", "guajimi.social").split(",")]
BASE_GMAIL = os.getenv("BASE_GMAIL", "").strip()  # dot-trick base, e.g. dewixzpajak01@gmail.com
PROXY_URL = os.getenv("PROXY_URL", "socks5://127.0.0.1:40000")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/meta-register/data/output"))
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/root/meta-register/data/screenshots"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

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


def random_name():
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def random_email(first: str, last: str) -> str:
    """Generate a unique email.

    If BASE_GMAIL is set, use Gmail dot-trick: insert random dots into the
    local part of the base Gmail. All variants deliver to the SAME inbox, so
    one IMAP account catches every OTP. Meta treats each dotted form as new.
    Falls back to domain-based email if BASE_GMAIL is unset.
    """
    if BASE_GMAIL and "@gmail.com" in BASE_GMAIL.lower():
        local, domain = BASE_GMAIL.split("@", 1)
        # Insert dots between characters (skip existing dots to avoid '..')
        chars = [c for c in local if c != "."]
        gaps = len(chars) - 1
        # Randomly choose which gaps get a dot (at least 1 for uniqueness)
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
    # Fallback: domain-based
    domain = random.choice(EMAIL_DOMAINS)
    sep = random.choice([".", "_", ""])
    num = random.randint(1, 999)
    user = f"{first.lower()}{sep}{last.lower()}{num}"
    return f"{user}@{domain}"


def random_birthday() -> tuple[str, str, str]:
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


# ---------------------------------------------------------------------------
# IMAP OTP reader
# ---------------------------------------------------------------------------
def fetch_otp(email_addr: str, timeout: int = 120, poll_interval: int = 5,
              since_ts: float | None = None) -> str | None:
    """Poll IMAP for Meta verification code.

    Searches by FROM Meta (not TO email_addr) because Gmail dot-variants
    all land in one inbox but the TO header reflects the dotted form.
    Filters by SINCE timestamp to skip old OTP emails.
    """
    print(f"  [OTP] Waiting for verification email at {email_addr} (timeout {timeout}s)...")
    deadline = time.time() + timeout
    # Record start time for SINCE filter — only look for emails received
    # AFTER we started waiting (skip old Meta OTP emails in inbox)
    if since_ts is None:
        since_ts = time.time()

    while time.time() < deadline:
        try:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            imap.login(IMAP_USER, IMAP_PASS)
            imap.select("INBOX")

            # Search by FROM Meta — no UNSEEN filter (email might already be read)
            # Also search in "[Gmail]/Semua Email" fallback if INBOX returns nothing
            since_date = datetime.fromtimestamp(since_ts).strftime("%d-%b-%Y")
            _, msg_nums = imap.search(None, f'(OR FROM "notification@email.meta.com" FROM "notification@facebookmail.com") (SINCE {since_date})')
            if not msg_nums[0]:
                # Fallback: try All Mail folder (Indonesian Gmail locale)
                try:
                    imap.select('"[Gmail]/Semua Email"')
                    _, msg_nums = imap.search(None, f'(OR FROM "notification@email.meta.com" FROM "notification@facebookmail.com") (SINCE {since_date})')
                except Exception:
                    pass

            if msg_nums[0]:
                for num in reversed(msg_nums[0].split()):  # newest first
                    _, data = imap.fetch(num, "(BODY[HEADER.FIELDS (SUBJECT DATE)])")
                    header = data[0][1].decode(errors="ignore")

                    # Extract date to verify it's newer than our request
                    date_match = re.search(r"Date:\s*(.+)", header)
                    if date_match:
                        try:
                            email_date = email.utils.parsedate_to_datetime(date_match.group(1).strip())
                            if email_date.timestamp() < since_ts:
                                continue  # skip old emails
                        except Exception:
                            pass

                    subject = header
                    m = re.search(r"(\d{5,8})", subject)
                    if m:
                        code = m.group(1)
                        imap.store(num, "+FLAGS", "\\Seen")
                        imap.logout()
                        print(f"  [OTP] Got code: {code}")
                        return code

            imap.logout()
        except Exception as e:
            print(f"  [OTP] IMAP error: {e}")

        time.sleep(poll_interval)

    print("  [OTP] Timeout waiting for code")
    return None


# ---------------------------------------------------------------------------
# Registration flow
# ---------------------------------------------------------------------------
async def take_screenshot(page, label: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"{label}_{ts}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"  [SCREENSHOT] {path}")
    return str(path)


async def safe_click(page, selector: str, timeout: int = 10000):
    """Wait for element and click it."""
    el = await page.wait_for_selector(selector, timeout=timeout)
    await el.scroll_into_view_if_needed()
    await asyncio.sleep(random.uniform(0.2, 0.6))
    await el.click()


async def human_type(page, selector: str, text: str, clear: bool = True):
    """Type text into a field with human-like delays."""
    el = await page.wait_for_selector(selector, timeout=10000)
    if clear:
        await el.click(click_count=3)
        await asyncio.sleep(0.1)
    for ch in text:
        await el.type(ch, delay=random.randint(40, 120))
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 0.8))


async def select_combobox_option(page, combobox, option_text: str, timeout: int = 10000):
    """Click a React div-based combobox and select an option by visible text.

    `combobox` can be an ElementHandle (preferred) or a CSS selector string.
    """
    # Resolve to an element handle
    if isinstance(combobox, str):
        cb = await page.wait_for_selector(combobox, timeout=timeout)
    else:
        cb = combobox
    # Click the combobox to open the dropdown
    await cb.click()
    await asyncio.sleep(random.uniform(0.3, 0.8))

    # Wait for a VISIBLE listbox (Meta renders a hidden aria-hidden dupe)
    await asyncio.sleep(0.4)
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

    # Fallback: try keyboard search
    await cb.press_sequentially(option_text[:3], delay=80)
    await asyncio.sleep(0.5)
    options = await page.query_selector_all('[role="listbox"] [role="option"]')
    for opt in options:
        text = await opt.inner_text()
        if option_text.lower() in text.lower():
            await opt.click()
            return True

    print(f"  [WARN] Could not find option '{option_text}' in combobox")
    return False


async def register_one(browser_context, email_addr: str, password: str,
                       first_name: str, last_name: str,
                       month: str, day: str, year: str) -> dict:
    """Attempt to register one Meta account. Returns result dict."""
    result = {
        "email": email_addr,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "birthday": f"{month} {day}, {year}",
        "status": "failed",
        "timestamp": datetime.now().isoformat(),
    }

    page = await browser_context.new_page()
    try:
        # Step 1: Navigate to dev.meta.ai
        print("  [1] Navigating to dev.meta.ai...")
        await page.goto("https://dev.meta.ai", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(random.uniform(3, 6))

        current_url = page.url
        print(f"  [1] Current URL: {current_url}")

        # Take initial screenshot
        await take_screenshot(page, "01_landing")

        # Step 2: Click "Use mobile number or email"
        print("  [2] Looking for 'Use mobile number or email' button...")
        # PRIORITY: role=button selectors first — they hit the real 52px div,
        # not the inner 10px span that text= would match.
        selectors = [
            'div[role="button"]:has-text("Use mobile number or email")',
            'div[role="button"]:has-text("mobile number")',
            'div[role="button"]:has-text("email")',
            'text="Use mobile number or email"',
            '[data-testid="royal_email_button"]',
            'button:has-text("email")',
        ]

        clicked = False
        for sel in selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                if el and await el.is_visible():
                    box = await el.bounding_box()
                    # Skip tiny elements (<20px height) — those are inner spans, not real buttons
                    if box and box.get("height", 0) >= 20:
                        await el.evaluate("el => el.click()")
                        clicked = True
                        print(f"  [2] Clicked: {sel} (h={box['height']:.0f}px)")
                        break
            except Exception:
                continue

        if not clicked:
            # Fallback: click coordinates where we know the button appears (559-611 Y range)
            print("  [2] Selector click failed, trying coordinate click")
            try:
                # Click center of the known button position
                await page.mouse.click(864, 585)  # center of 585,559 + 558,52
                clicked = True
                print("  [2] Coordinate click at (864,585)")
            except Exception as e:
                print(f"  [2] Coordinate click failed: {e}")

        if not clicked:
            # Maybe already showing email field
            print("  [2] Button not found, checking if email field is visible...")
            email_field = await page.query_selector('input[name="email"]')
            if not email_field:
                await take_screenshot(page, "02_no_button")
                result["error"] = "Could not find 'use email' button or email field"
                return result

        # Wait for the email/mobile input to actually appear after the click
        # Meta shows a transition page: "What's your mobile number or email?"
        await asyncio.sleep(random.uniform(1, 2))
        try:
            await page.wait_for_selector('input[autocomplete="username"], input[inputmode="email"], input:not([type="password"]):not([type="hidden"])', timeout=8000, state="visible")
            print("  [2] Email input appeared after click")
        except Exception:
            print("  [2] WARN: Email input not visible yet after click, continuing anyway")

        # Record timestamp before email entry — used by fetch_otp to skip old emails
        reg_start_ts = time.time()

        # Step 3: Enter email address
        print(f"  [3] Entering email: {email_addr}")
        # Meta actual: type="text" inputmode="email" autocomplete="username" (no name/type=email)
        email_selectors = [
            'input[autocomplete="username"]',   # Meta's actual attribute
            'input[inputmode="email"]',          # Meta's actual attribute
            'input:not([type="password"]):not([type="hidden"]):not([type="submit"])',  # last resort
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

        # Click Continue — wait for button to become enabled after email entry
        print("  [3] Clicking Continue...")
        continue_selectors = [
            'div[role="button"]:has-text("Continue")',
            'div[role="button"]:has-text("Next")',
            'button:has-text("Continue")',
        ]
        # Wait for Continue button to be enabled (starts disabled on Meta)
        for _ in range(20):  # up to 10s
            for sel in continue_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=1000, state="visible")
                    if el and await el.is_visible():
                        dis = await el.get_attribute("aria-disabled")
                        if dis != "true":
                            await el.evaluate("el => el.click()")
                            print(f"  [3] Continue clicked (enabled)")
                            break
                except Exception:
                    continue
            else:
                await asyncio.sleep(0.5)
                continue
            break
        else:
            print("  [3] WARN: Continue button never enabled, trying force click anyway")
            try:
                el = await page.query_selector('div[role="button"]:has-text("Continue")')
                if el:
                    await el.evaluate("el => el.click()")
                    print("  [3] Continue force-clicked (was disabled)")
            except Exception:
                pass

        await asyncio.sleep(random.uniform(2, 5))
        await take_screenshot(page, "04_after_email")

        # Step 4: Check if we see "Create a new account" form
        print("  [4] Checking for account creation form...")
        page_text = await page.inner_text("body")

        if "create" in page_text.lower() and "account" in page_text.lower():
            print("  [4] Account creation form detected!")

            # Fill birthday using comboboxes
            print(f"  [4] Setting birthday: {month} {day}, {year}")

            # Month combobox - usually first one
            month_cbs = await page.query_selector_all('div[role="combobox"]')
            if len(month_cbs) >= 3:
                # Pass element handles directly — avoids fragile :nth-of-type
                # (which counts siblings per-parent, not document order)
                await select_combobox_option(page, month_cbs[0], month)
                await asyncio.sleep(random.uniform(0.3, 0.7))

                # Day combobox
                await select_combobox_option(page, month_cbs[1], day)
                await asyncio.sleep(random.uniform(0.3, 0.7))

                # Year combobox
                await select_combobox_option(page, month_cbs[2], year)
                await asyncio.sleep(random.uniform(0.3, 0.7))
            else:
                # Fallback: try aria-label or name-based selectors
                print(f"  [4] Found {len(month_cbs)} comboboxes, trying alternative selectors...")
                # Try by aria-label
                for label_text, value in [("month", month), ("day", day), ("year", year)]:
                    sel = f'div[role="combobox"][aria-label*="{label_text}" i], div[role="combobox"][aria-label*="{label_text.capitalize()}" i]'
                    try:
                        await select_combobox_option(page, sel, value)
                    except Exception:
                        # Try nth combobox approach with broader selector
                        try:
                            all_cbs = await page.query_selector_all('[role="combobox"]')
                            idx = {"month": 0, "day": 1, "year": 2}[label_text]
                            if idx < len(all_cbs):
                                await all_cbs[idx].click()
                                await asyncio.sleep(0.5)
                                opt_sel = f'[role="listbox"] [role="option"]:has-text("{value}")'
                                opt = await page.wait_for_selector(opt_sel, timeout=3000)
                                await opt.click()
                        except Exception as e:
                            print(f"  [4] Combobox fallback error for {label_text}: {e}")
                    await asyncio.sleep(random.uniform(0.3, 0.7))

            # Fill name fields
            print(f"  [4] Entering name: {first_name} {last_name}")
            name_selectors = [
                ('input[name="firstname"]', first_name),
                ('input[name="lastName"]', last_name),
                ('input[aria-label*="first" i]', first_name),
                ('input[aria-label*="last" i]', last_name),
            ]
            # Also try by order if name-specific selectors fail
            all_text_inputs = await page.query_selector_all('input[type="text"]')

            for sel, val in name_selectors:
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

            # If name fields weren't found by specific selectors, try positional
            if all_text_inputs and len(all_text_inputs) >= 2:
                for inp in all_text_inputs:
                    val = await inp.get_attribute("value") or ""
                    name_val = await inp.get_attribute("name") or ""
                    if not val and "first" not in name_val.lower():
                        # Might be name fields
                        pass

            # Fill password
            print("  [4] Entering password...")
            pwd_selectors = [
                'input[name="reg_passwd__"]',
                'input[name="password"]',
                'input[type="password"]',
                'input[name="new_password"]',
            ]
            for sel in pwd_selectors:
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

            await asyncio.sleep(random.uniform(0.5, 1.5))
            await take_screenshot(page, "05_filled_form")

            # Click Confirm/Sign Up — use role=button with size check (same as "Use email" fix)
            print("  [4] Clicking Confirm...")
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
                            print(f"  [4] Clicked: {sel} (h={box['height']:.0f}px)")
                            break
                except Exception:
                    continue

            # Wait for page to react — check for URL change or new content
            for _ in range(10):  # up to 5s
                await asyncio.sleep(0.5)
                if page.url != url_before:
                    print(f"  [4] URL changed after Confirm → navigated")
                    break
                # Check if OTP input or error appeared
                otp_hint = await page.query_selector('input[aria-label*="code" i], input[aria-label*="otp" i], input[aria-label*="verification" i]')
                if otp_hint:
                    print(f"  [4] OTP input appeared after Confirm")
                    break
            else:
                # Final check — take screenshot and dump visible text for debugging
                page_snippet = (await page.inner_text("body"))[:400]
                print(f"  [4] WARN: page didn't change after Confirm. Visible: {page_snippet[:200]}")


            await asyncio.sleep(random.uniform(3, 6))
            await take_screenshot(page, "06_after_confirm")

        elif "check your email" in page_text.lower() or "enter the code" in page_text.lower() or "verification code" in page_text.lower():
            # Meta sent OTP directly after email entry (existing account / passwordless login)
            print("  [4] OTP screen detected after email entry (Check your email)")
            await take_screenshot(page, "04_otp_screen")

            otp_code = fetch_otp(email_addr, timeout=120, since_ts=reg_start_ts)
            if not otp_code:
                result["error"] = "OTP timeout after email entry"
                await take_screenshot(page, "07_otp_timeout")
                return result

            print(f"  [4] Entering OTP: {otp_code}")
            otp_selectors = [
                'input[aria-label*="code" i]',
                'input[aria-label*="otp" i]',
                'input[aria-label*="verification" i]',
                'input[inputmode="numeric"]',
                'input[type="tel"]',
                'input[type="number"]',
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
                        print(f"  [4] OTP filled via {sel}")
                        break
                except Exception:
                    continue

            if not otp_filled:
                # Fallback: fill any visible empty text input
                inputs = await page.query_selector_all("input")
                for inp in inputs:
                    try:
                        val = await inp.get_attribute("value") or ""
                        itype = await inp.get_attribute("type") or ""
                        vis = (await inp.bounding_box()) is not None
                        if vis and not val and itype in ("text", "tel", "number", ""):
                            await inp.fill(otp_code)
                            otp_filled = True
                            print(f"  [4] OTP filled via fallback input[type={itype}]")
                            break
                    except Exception:
                        continue

            if not otp_filled:
                result["error"] = "Could not find OTP input field"
                await take_screenshot(page, "07_no_otp_field")
                return result

            await asyncio.sleep(random.uniform(1, 3))

            # Click Next/Continue/Submit after OTP
            # Meta OTP screen uses "Next" button (enabled after code entry)
            for sel in ['div[role="button"]:has-text("Next")', 'div[role="button"]:has-text("Continue")', 'button:has-text("Next")', 'button:has-text("Continue")']:
                try:
                    el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                    if el:
                        # Wait for button to become enabled (starts disabled on Meta OTP screen)
                        for _ in range(20):  # up to 10s
                            dis = await el.get_attribute("aria-disabled")
                            if dis != "true":
                                break
                            await asyncio.sleep(0.5)
                        box = await el.bounding_box()
                        if box and box.get("height", 0) >= 20:
                            # Use Playwright native click (not JS evaluate) — better for React apps
                            await el.scroll_into_view_if_needed()
                            await asyncio.sleep(0.3)
                            await el.click(force=True)
                            print(f"  [4] Post-OTP '{sel}' clicked (box: {box['height']:.0f}px)")
                            break
                except Exception:
                    continue

            await asyncio.sleep(random.uniform(3, 6))
            await take_screenshot(page, "08_after_otp_entry")

            # Check if login succeeded
            page_text_after = (await page.inner_text("body"))[:500].lower()
            current_url = page.url
            if "error" in page_text_after or "wrong" in page_text_after or "incorrect" in page_text_after:
                result["error"] = "OTP entry failed — wrong code or error"
                return result
            # Success indicators: redirected away from auth.meta.com, or dev.meta.ai content
            if "auth.meta.com" not in current_url or "dev.meta.ai" in current_url:
                print(f"  [4] ✅ LOGIN SUCCESS — redirected to {current_url[:80]}")
                result["status"] = "success"
                await take_screenshot(page, "09_success")
                # Extract cookies/session
                cookies = await page.context.cookies()
                result["cookies"] = cookies
            else:
                print(f"  [4] OTP entry complete — checking if we're logged in...")
                await take_screenshot(page, "08_after_otp_wait")

        elif "password" in page_text.lower() or "login" in page_text.lower():
            # Account already exists - might be a login prompt
            result["error"] = "Account may already exist (login prompt shown)"
            await take_screenshot(page, "04_login_prompt")
            return result
        else:
            print("  [4] Unknown state after email entry")
            await take_screenshot(page, "04_unknown_state")
            result["error"] = "Unknown state after email entry"
            return result

        # Step 5: OTP entry
        print("  [5] Waiting for OTP verification...")
        await take_screenshot(page, "07_before_otp")

        # Check if OTP input is visible on page
        otp_code = fetch_otp(email_addr, timeout=120, since_ts=reg_start_ts)
        if not otp_code:
            result["error"] = "OTP timeout - no code received"
            await take_screenshot(page, "07_otp_timeout")
            return result

        print(f"  [5] Entering OTP: {otp_code}")
        otp_selectors = [
            'input[name="code"]',
            'input[type="tel"]',
            'input[type="number"]',
            'input[aria-label*="code" i]',
            'input[aria-label*="verification" i]',
            'input[inputmode="numeric"]',
        ]
        otp_filled = False
        for sel in otp_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=5000)
                if el:
                    await el.click()
                    await el.fill(otp_code)
                    otp_filled = True
                    break
            except Exception:
                continue

        if not otp_filled:
            # Try finding any input that appeared
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                try:
                    val = await inp.get_attribute("value") or ""
                    itype = await inp.get_attribute("type") or ""
                    if not val and itype in ("text", "tel", "number", ""):
                        await inp.fill(otp_code)
                        otp_filled = True
                        break
                except Exception:
                    continue

        await asyncio.sleep(random.uniform(1, 3))

        # Submit OTP (Meta uses "Next" button, not "Continue")
        submit_selectors = [
            'div[role="button"]:has-text("Next")',
            'div[role="button"]:has-text("Continue")',
            'div[role="button"]:has-text("Confirm")',
            'div[role="button"]:has-text("Submit")',
            'div[role="button"]:has-text("Verify")',
            'button:has-text("Next")',
            'button:has-text("Continue")',
        ]
        for sel in submit_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=3000)
                if el:
                    await el.click()
                    break
            except Exception:
                continue

        # Wait for OTP submit to process
        await asyncio.sleep(random.uniform(3, 5))
        await take_screenshot(page, "08_after_otp")

        # Step 5.5: Handle "Save your login info?" dialog
        print("  [5.5] Checking for post-login dialogs...")
        dialog_buttons = [
            'div[role="button"]:has-text("Save")',
            'div[role="button"]:has-text("OK")',
            'div[role="button"]:has-text("Continue")',
            'div[role="button"]:has-text("Yes")',
            'div[role="button"]:has-text("Allow")',
            'div[role="button"]:has-text("Confirm")',
            'div[role="button"]:has-text("Next")',
            'div[role="button"]:has-text("Done")',
        ]
        for _round in range(5):  # Check 5 times over 10s
            for sel in dialog_buttons:
                try:
                    el = await page.wait_for_selector(sel, timeout=2000)
                    if el:
                        box = await el.bounding_box()
                        if box and box["height"] > 20:
                            await el.click(force=True)
                            btn_text = sel.split('"')[3] if '"' in sel else sel
                            print(f"  [5.5] Clicked dialog button: {btn_text}")
                            await asyncio.sleep(2)
                except Exception:
                    continue
            await asyncio.sleep(2)

        # Step 6: Wait for OAuth redirect to complete (c_user cookie set after redirect)
        print("  [6] Waiting for OAuth redirect to complete...")
        redirect_done = False
        for _wait in range(30):  # max 30s
            current_url = page.url
            if "dev.meta.ai" in current_url or "developers.facebook" in current_url:
                redirect_done = True
                print(f"  [6] Redirect complete: {current_url[:80]}")
                break
            # Check if c_user cookie already exists
            all_cookies_now = await browser_context.cookies()
            if any(c["name"] == "c_user" for c in all_cookies_now):
                redirect_done = True
                print("  [6] c_user cookie found during wait")
                break
            await asyncio.sleep(1)

        if not redirect_done:
            # Force navigate to dev.meta.ai to trigger cookie finalization
            print(f"  [6] Redirect timeout. Current URL: {page.url[:80]}")
            print("  [6] Navigating to dev.meta.ai to trigger cookie set...")
            try:
                await page.goto("https://dev.meta.ai/", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(5)
            except Exception as nav_err:
                print(f"  [6] Navigation error (may be OK): {nav_err}")

        # Extract ALL cookies from ALL domains (not just meta/facebook)
        cookies = await browser_context.cookies()
        meta_cookies = {c["name"]: c["value"] for c in cookies}

        # Debug: print all cookie domains
        all_domains = sorted(set(c.get("domain", "") for c in cookies))
        print(f"  [6] Cookie domains: {all_domains}")
        print(f"  [6] Cookie names: {sorted(meta_cookies.keys())}")

        # If no c_user yet, check iframes and try visiting facebook.com
        if "c_user" not in meta_cookies:
            print("  [6.1] No c_user yet — checking all frames for cookies...")
            for i, frame in enumerate(page.frames):
                try:
                    frame_url = frame.url
                    frame_cookies = await browser_context.cookies([frame_url])
                    for c in frame_cookies:
                        if c["name"] == "c_user":
                            meta_cookies["c_user"] = c["value"]
                            print(f"  [6.1] Found c_user in frame[{i}] URL={frame_url[:60]}")
                            break
                except Exception as fe:
                    pass

            # Also dump all frame URLs for debug
            frame_urls = [f.url for f in page.frames]
            print(f"  [6.1] All frames ({len(frame_urls)}): {frame_urls[:5]}")

            # Try visiting facebook.com to trigger c_user cookie
            if "c_user" not in meta_cookies:
                print("  [6.2] Trying facebook.com visit to trigger c_user...")
                try:
                    await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(3)
                    fb_cookies = await browser_context.cookies()
                    for c in fb_cookies:
                        if c["name"] == "c_user":
                            meta_cookies["c_user"] = c["value"]
                            meta_cookies[c["name"]] = c["value"]
                            print(f"  [6.2] Got c_user from facebook.com: {c['value']}")
                            break
                    # Update all cookies
                    cookies = await browser_context.cookies()
                    meta_cookies = {c["name"]: c["value"] for c in cookies}
                except Exception as fb_err:
                    print(f"  [6.2] facebook.com visit error: {fb_err}")

                # Also try auth.meta.com
                if "c_user" not in meta_cookies:
                    print("  [6.3] Trying auth.meta.com visit to trigger c_user...")
                    try:
                        await page.goto("https://auth.meta.com/", wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(3)
                        cookies = await browser_context.cookies()
                        meta_cookies = {c["name"]: c["value"] for c in cookies}
                    except Exception as auth_err:
                        print(f"  [6.3] auth.meta.com visit error: {auth_err}")

        # Check for session cookies (llm_sess = Meta AI session, c_user = Facebook session)
        if "c_user" in meta_cookies:
            result["status"] = "success"
            result["cookies"] = meta_cookies
            result["c_user"] = meta_cookies.get("c_user", "")
            print(f"  [6] SUCCESS! c_user={result['c_user']}")
        elif "llm_sess" in meta_cookies:
            result["status"] = "success"
            result["cookies"] = meta_cookies
            print(f"  [6] SUCCESS! llm_sess={meta_cookies['llm_sess'][:20]}...")
        else:
            final_url = page.url
            result["final_url"] = final_url
            print(f"  [6] No session cookies. Final URL: {final_url}")
            if "dev.meta" in final_url or "developers" in final_url or "datr" in meta_cookies:
                result["status"] = "success"
                result["cookies"] = meta_cookies

        # Navigate to dev.meta.ai dashboard for final screenshot
        try:
            current = page.url
            if "dev.meta.ai" not in current:
                await page.goto("https://dev.meta.ai/", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
            result["final_url"] = page.url
            print(f"  [7] Final URL: {page.url}")
        except Exception:
            pass

        await take_screenshot(page, "09_final")

    except Exception as e:
        result["error"] = str(e)
        print(f"  [ERROR] {e}")
        try:
            await take_screenshot(page, "error")
        except Exception:
            pass
    finally:
        await page.close()

    return result


async def run_registrations(count: int):
    """Main registration loop."""
    from camoufox.async_api import AsyncCamoufox

    results = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"accounts_{ts}.json"

    print(f"\n{'='*60}")
    print(f"Meta Account Registration Bot")
    print(f"Target: {count} account(s)")
    print(f"Output: {output_file}")
    print(f"{'='*60}\n")

    for i in range(count):
        first, last = random_name()
        email_addr = random_email(first, last)
        password = random_password()
        month, day, year = random_birthday()

        print(f"\n[{i+1}/{count}] Registering: {first} {last} <{email_addr}>")
        print(f"  Birthday: {month} {day}, {year}")

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                launch_kwargs = dict(
                    headless="virtual",
                    humanize=True,
                    os="windows",
                    block_webrtc=True,
                )
                if PROXY_URL:
                    launch_kwargs["proxy"] = {"server": PROXY_URL}
                    launch_kwargs["geoip"] = True  # geolocate via proxy IP
                # else: direct connection, no proxy, no geoip lookup
                async with AsyncCamoufox(**launch_kwargs) as browser:
                    # Create context with ignore_https_errors for free proxy SSL issues
                    if hasattr(browser, 'new_context'):
                        ctx = await browser.new_context(ignore_https_errors=True)
                        result = await register_one(ctx, email_addr, password, first, last, month, day, year)
                        await ctx.close()
                    else:
                        ctx = browser
                        result = await register_one(ctx, email_addr, password, first, last, month, day, year)

                if result["status"] == "success" or attempt == max_retries:
                    results.append(result)
                    break
                else:
                    print(f"  Retry {attempt + 1}/{max_retries}...")
                    # New email for retry
                    email_addr = random_email(first, last)
                    await asyncio.sleep(random.uniform(3, 8))

            except Exception as e:
                print(f"  [FATAL] Browser launch error: {e}")
                if attempt == max_retries:
                    results.append({
                        "email": email_addr,
                        "status": "failed",
                        "error": str(e),
                        "timestamp": datetime.now().isoformat(),
                    })
                await asyncio.sleep(random.uniform(5, 10))

        # Random delay between registrations
        if i < count - 1:
            delay = random.uniform(10, 30)
            print(f"\n  Waiting {delay:.1f}s before next registration...")
            await asyncio.sleep(delay)

    # Save results
    # Strip cookies from verbose output, keep summary
    output_data = []
    for r in results:
        entry = {k: v for k, v in r.items() if k != "cookies"}
        entry["has_session"] = r.get("status") == "success"
        entry["cookie_keys"] = list(r.get("cookies", {}).keys())
        output_data.append(entry)

    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)

    # Also save full data with cookies
    full_file = OUTPUT_DIR / f"accounts_{ts}_full.json"
    with open(full_file, "w") as f:
        json.dump(results, f, indent=2)

    success = sum(1 for r in results if r["status"] == "success")
    print(f"\n{'='*60}")
    print(f"Done! {success}/{count} registrations succeeded")
    print(f"Summary: {output_file}")
    print(f"Full data: {full_file}")
    print(f"{'='*60}\n")

    return results


def main():
    parser = argparse.ArgumentParser(description="Meta account registration bot")
    sub = parser.add_subparsers(dest="command")

    reg = sub.add_parser("register", help="Register accounts")
    reg.add_argument("--count", "-c", type=int, default=1, help="Number of accounts to register")

    args = parser.parse_args()

    if args.command == "register":
        asyncio.run(run_registrations(args.count))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
