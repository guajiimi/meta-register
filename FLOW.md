# Meta AI Registration Bot — Flow & Core Logic

## Overview

Bot untuk auto-register akun Meta AI (dev.meta.ai), add payment method, dan create API key.

**Kenapa Windows?** Meta billing butuh `platform_trust_token` dengan hardware attestation (TPM/Secure Enclave). VPS Linux gagal karena gak ada TPM hardware. Windows punya real TPM → trust token valid.

## Setup

```bash
pip install playwright playwright-stealth python-dotenv
playwright install chromium
```

Copy `.env.example` ke `.env` dan isi credentials.

## Jalankan

```bash
# Single account
python bot_windows.py register --count 1

# Batch 3 accounts
python bot_windows.py register --count 3

# Skip billing (register only)
python bot_windows.py register --no-billing

# Skip API key creation
python bot_windows.py register --no-apikey

# Headless mode (NOT recommended — trust tokens may fail)
python bot_windows.py register --headless
```

## Flow Diagram

```
START
  │
  ├─[1] Launch Playwright Chromium (headed, stealth args)
  │     └─ Apply anti-detection patches (navigator.webdriver, WebGL, plugins)
  │
  ├─[2] REGISTER (step_register)
  │     ├─ Navigate to auth.meta.com
  │     ├─ Click "Use mobile number or email"
  │     ├─ Enter email (Gmail dot-trick)
  │     ├─ Fill birthday (month/day/year comboboxes)
  │     ├─ Fill first name, last name
  │     ├─ Fill password
  │     ├─ Click "Confirm"
  │     │
  │     ├─[3] OTP VERIFICATION
  │     │    ├─ Poll IMAP for Meta verification email
  │     │    ├─ Search: FROM notification@email.meta.com
  │     │    ├─ Extract 5-8 digit code from subject
  │     │    ├─ Enter code in OTP field
  │     │    └─ Click "Next"
  │     │
  │     ├─[4] Handle post-login dialogs
  │     │    └─ "Save your login info?" → Click "Save" / "OK"
  │     │
  │     └─[5] Wait for OAuth redirect to dev.meta.ai
  │          └─ Extract cookies (datr, llm_sess, ps_l, ps_n, fs, locale)
  │
  ├─[6] BILLING (step_billing) — OPTIONAL
  │     ├─ Navigate to dev.meta.ai/billing
  │     ├─ Check geo-block (US-only)
  │     ├─ Extract team_id + project_id from URL
  │     ├─ Click "Add payment method"
  │     ├─ Fill card form:
  │     │    ├─ Name: "{first_name} {last_name}"
  │     │    ├─ Card: 4889501032758307
  │     │    ├─ Expiry: 08/27
  │     │    ├─ CVV: 424
  │     │    └─ ZIP: 90001
  │     ├─ Submit → capture billing/graphql response
  │     └─ Verify: xfb_billing_save_credit_card → client_result
  │
  ├─[7] API KEY (step_api_key) — OPTIONAL
  │     ├─ Navigate to dev.meta.ai/api-keys
  │     ├─ Click "Create API key"
  │     ├─ Set name: "default"
  │     ├─ Copy API key (AAI...)
  │     └─ Handle "Continue without safety" if shown
  │
  └─[8] OUTPUT JSON
        ├─ accounts_TIMESTAMP.json (summary, no cookies)
        └─ accounts_TIMESTAMP_full.json (full, with cookies)
```

## Key Functions

### `launch_browser(playwright, headless=False)`
Playwright Chromium launch dengan stealth args.

**Critical args:**
- `--disable-blink-features=AutomationControlled` — hide automation flag
- `ignore_default_args=['--enable-automation']` — remove "Chrome is being controlled" bar
- `headless=False` — WAJIB headed untuk trust tokens

**Context fingerprint:**
- User-Agent: Chrome 131 on Windows 10
- Viewport: 1920x1080
- Locale: en-US, Timezone: America/New_York
- Proxy: dari .env PROXY_URL (socks5://127.0.0.1:40000 = WARP)

### `apply_stealth(context)` (inline JS patches)
Inject JS ke setiap page untuk:
- `navigator.webdriver = false`
- `navigator.plugins` = 5 fake plugins
- `navigator.languages = ['en-US', 'en']`
- `chrome.runtime` mock
- `WebGL vendor = Google Inc.`, `renderer = Intel`

### `fetch_otp(email_addr, timeout=120)`
Poll IMAP setiap 5 detik:
- Login ke Gmail IMAP
- Search: `FROM "notification@email.meta.com" SINCE today`
- Extract 5-8 digit code dari subject
- Filter by timestamp (skip old emails)
- Mark as read

### `step_register(page, ...)` 
Registration flow di auth.meta.com.

**Selector strategy (penting!):**
- Button: `div[role="button"]:has-text("...")` — lebih reliable dari `button:has-text`
- Size check: `bounding_box.height >= 20` — skip inner spans
- Email input: `input[autocomplete="username"]` atau `input[inputmode="email"]`
- Combobox: `div[role="combobox"]` → select `div[role="option"]` by text

**Timing:**
- `human_delay(0.3, 1.0)` antar action
- Wait for `aria-disabled` ≠ "true" sebelum click button
- `asyncio.sleep(3-6)` setelah major transitions

### `step_billing(page, context, first_name, last_name)`
Card submission di dev.meta.ai/billing.

**CRITICAL — ini yang gagal di VPS:**
- Meta billing kirim `platform_trust_token` dengan `signatures`
- Di VPS: `signatures: []` (empty) → server reject `error_code: 2078180`
- Di Windows: TPM generate real signatures → should work

**Card form selectors:**
- `input[name="firstName"]` — cardholder name
- `input[name="cardNumber"]` — 16 digit card number
- `input[name="expiration"]` — MM/YY format
- `input[name="securityCode"]` — 3-4 digit CVV
- ZIP: injected via JS (no reliable selector)

**Response capture:**
- Listen `page.on("response")` untuk `billing/graphql`
- Parse: `data.xfb_billing_save_credit_card.client_result`
- `status` + `error_code` tell us if card was saved

### `step_api_key(page, context)`
API key creation di dev.meta.ai/api-keys.

**Flow:**
- Navigate → click "Create API key"
- Fill name "default" → click "Continue"
- Handle "Continue without safety" modal
- Copy API key text (starts with `AAI`)
- Key muncul 1x saja, langsung capture

**Selectors:**
- Create button: `:is(button, [role="button"]):has-text("Create API key")`
- Name input: `input[name="name"]` atau `input[placeholder*="name"]`
- API key display: element containing `AAI` prefix

## Known Issues & Debugging

### `error_code: 2078180` — Card save failed
**Penyebab:** `platform_trust_token` invalid (signatures empty)
**Fix:** Harus run di Windows dengan real TPM. Headless mode juga bisa gagal.

### `error_code: 2078180` di Windows
**Kemungkinan:**
1. Headless mode — coba `--headed` (default)
2. Proxy blocking — coba tanpa proxy, atau ganti VPN
3. Card declined bank — coba kartu lain
4. Rate limit — tunggu 15-30 menit, ganti IP

### OTP timeout
**Penyebab:** Email gak masuk dalam 120 detik
**Fix:**
- Cek IMAP credentials di .env
- Cek BASE_GMAIL valid
- Tambah timeout: `fetch_otp(email, timeout=180)`

### Billing geo-blocked
**Penyebab:** IP bukan US
**Fix:** Pakai VPN/socks5 proxy ke US. Set di .env:
```
PROXY_URL=socks5://127.0.0.1:40000  # WARP
```

### `navigator.webdriver` masih terdeteksi
**Fix:** Cek `apply_stealth()` jalan. Tambahkan:
```python
await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {get: () => false});
""")
```

## Output Format

```json
{
  "email": "d.e.w.i.x.z.pajak.01@gmail.com",
  "password": "Kx9!mQ2@pL5nR8sT",
  "first_name": "James",
  "last_name": "Smith",
  "birthday": "March 15, 1995",
  "status": "success",
  "has_session": true,
  "cookie_keys": ["datr", "llm_sess", "ps_l", "ps_n", "fs", "locale"],
  "cookies": {"datr": "...", "llm_sess": "..."},
  "team_id": "1738876200781240",
  "project_id": "1532003478624205",
  "api_key": "AAIxxxxxxxxxxxxxxx",
  "billing_status": "success",
  "timestamp": "2026-07-14T23:45:00.000000"
}
```

## Environment Variables (.env)

```env
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=dewixzpajak01@gmail.com
IMAP_PASS=your-app-password
BASE_GMAIL=dewixzpajak01@gmail.com
PROXY_URL=socks5://127.0.0.1:40000
```

## File Structure

```
meta-register/
├── bot.py              # Original bot (Linux/Camoufox)
├── bot_windows.py      # Windows Playwright version ← THIS
├── .env                # Credentials (gitignored)
├── FLOW.md             # This file
├── data/
│   ├── output/         # JSON results
│   └── screenshots/    # Step screenshots
```
