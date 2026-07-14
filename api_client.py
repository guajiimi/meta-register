#!/usr/bin/env python3
"""
Meta AI Pure API Client v2 — Full reverse engineered from network capture.
No Playwright. curl_cffi only.
"""
import json, os, re, time, uuid, base64, struct, urllib.parse
from typing import Optional, Dict, Any, Tuple

from curl_cffi import requests as cffi_requests

try:
    import nacl.public, nacl.utils
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.kdf.concatkdf import ConcatKDFHash
    from cryptography import x509
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ─── CONFIG ───────────────────────────────────────────────────────
APP_ID = "2403310080153219"
AUTH_URL = "https://auth.meta.com"
DEV_URL = "https://dev.meta.ai"
TEMPMAIL_API = os.getenv("TEMPMAIL_API_URL", "http://localhost:8096")
PROXY = os.getenv("PROXY_URL", "socks5://127.0.0.1:1081")

# ─── GRAPHQL DOC IDS ─────────────────────────────────────────────
DOC = {
    "otp_confirm":    "9851798224911796",
    "onboard_name":   "37615747154690842",
    "accept_terms":   "9665990526769906",
    "encrypt_key":    "23994203586844376",
    "bin_lookup":     "26853726450994905",
    "save_card":      "26656707574002201",
    "create_api_key": "26450098374584540",
}

REQ_COUNTER = 0

def next_req():
    global REQ_COUNTER
    REQ_COUNTER += 1
    return hex(REQ_COUNTER)[2:]

def uid():
    return str(uuid.uuid4())

def uid_hex(n=20):
    return uuid.uuid4().hex[:n]


# ─── TEMPMAIL (tempmail.lol direct API) ──────────────────────────
TEMPMAIL_LOL_API = "https://api.tempmail.lol/v2"
_tempmail_tokens = {}  # email -> token (for inbox polling)

def tempmail_generate():
    """Generate temp email via tempmail.lol v2 API.
    
    POST /v2/inbox/create → {address, token}
    Token stored in _tempmail_tokens for OTP polling.
    """
    r = cffi_requests.post(f"{TEMPMAIL_LOL_API}/inbox/create",
                           json={}, headers={"Content-Type": "application/json"},
                           timeout=15)
    d = r.json()
    email = d.get("address", "")
    token = d.get("token", "")
    if email and token:
        _tempmail_tokens[email] = token
    return email, token

def tempmail_otp(email, timeout=120):
    """Poll tempmail.lol v2 for 6-digit OTP.
    
    GET /v2/inbox?token={token} → {emails: [{body, html, sender, subject}], expired}
    """
    token = _tempmail_tokens.get(email)
    if not token:
        return None
    
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = cffi_requests.get(f"{TEMPMAIL_LOL_API}/inbox?token={token}", timeout=12)
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code != 200:
                continue
            
            data = r.json()
            if data.get("expired"):
                return None
            
            emails = data.get("emails", [])
            for msg in emails:
                raw = msg.get("body", "") + " " + msg.get("html", "")
                # Clean HTML
                text = re.sub(r'<[^>]+>', ' ', raw)
                m = re.search(r"\b(\d{6})\b", text)
                if m:
                    return m.group(1)
        except Exception:
            pass
        time.sleep(1.5)
    return None


# ─── ENCRYPTION ──────────────────────────────────────────────────
def encrypt_password(password: str, key_id: int, public_key_hex: str) -> str:
    """Meta's EnvelopeEncryption: AES-256-GCM + NaCl sealed box."""
    if not HAS_CRYPTO:
        return f"#PWD_BROWSER:5:{int(time.time())}:{password}"

    ts = str(int(time.time()))
    pk = nacl.public.PublicKey(bytes.fromhex(public_key_hex))
    box = nacl.public.SealedBox(pk)

    pwd_b = password.encode()
    ts_b = ts.encode()

    aes_key = nacl.utils.random(32)
    aesgcm = AESGCM(aes_key)
    enc = aesgcm.encrypt(bytes(12), pwd_b, ts_b)
    tag, ct = enc[-16:], enc[:-16]

    sealed = box.encrypt(aes_key)

    # Build envelope: [version=1][key_id][sealed_len_le16][sealed][tag][ciphertext]
    v = bytearray(1 + 1 + 2 + len(sealed) + 16 + len(ct))
    v[0] = 1
    v[1] = key_id
    sl = len(sealed)
    v[2] = sl & 0xFF
    v[3] = (sl >> 8) & 0xFF
    off = 4
    v[off:off+len(sealed)] = sealed; off += len(sealed)
    v[off:off+16] = tag; off += 16
    v[off:] = ct

    return f"#PWD_BROWSER:5:{ts}:{base64.b64encode(bytes(v)).decode()}"


# ─── CLIENT ──────────────────────────────────────────────────────
class MetaAPI:
    def __init__(self, proxy=None):
        self.s = cffi_requests.Session(impersonate="chrome120")
        self.px = {"https": proxy or PROXY, "http": proxy or PROXY}
        self.lsd = None
        self.jazoest = None
        self.fb_dtsg = None
        self.hsi = None
        self.rev = None
        self.spin_r = None
        self.spin_t = None
        self.session_s = None  # __s from login page
        self.waterfall = uid()
        self.actor_id = "0"
        self.account_id = None
        self.team_id = None
        self.payment_account_id = None

    # ── HTTP helpers ──
    def get(self, url, timeout=30, **kw):
        return self.s.get(url, proxies=self.px, allow_redirects=True, timeout=timeout, **kw)

    def post(self, url, data=None, **kw):
        return self.s.post(url, data=data, proxies=self.px, allow_redirects=True, timeout=30, **kw)

    def post_json(self, url, body, **kw):
        return self.s.post(url, json=body, proxies=self.px, allow_redirects=True, timeout=30, **kw)

    def parse(self, text):
        """Strip for(;;); prefix and parse JSON."""
        if text and text.startswith("for (;;);"):
            text = text[len("for (;;);"):]
        try:
            return json.loads(text)
        except Exception:
            return {}

    def cookies_dict(self):
        """Export cookies grouped by domain."""
        c = {}
        for ck in self.s.cookies.jar:
            d = ck.domain
            if d not in c:
                c[d] = {}
            c[d][ck.name] = ck.value
        return c

    # ── Token extraction ──
    def _extract(self, html):
        """Extract session tokens from Meta HTML."""
        # LSD
        m = re.search(r'"LSD".*?"token"\s*:\s*"([^"]+)"', html)
        if m:
            self.lsd = m.group(1)
        # jazoest = sum(char_codes_of_lsd) * sprinkle_version
        m = re.search(r'"SprinkleConfig".*?"param_name":"jazoest".*?"version":(\d+)', html)
        ver = int(m.group(1)) if m else 2
        if self.lsd:
            self.jazoest = str(sum(ord(c) for c in self.lsd) * ver)
        # fb_dtsg
        m = re.search(r'"DTSGInitialData".*?"token"\s*:\s*"([^"]+)"', html)
        if m:
            self.fb_dtsg = m.group(1)
        # hsi
        m = re.search(r'"hsi":"(\d+)"', html)
        if m:
            self.hsi = m.group(1)
        # rev
        m = re.search(r'"client_revision":(\d+)', html)
        if m:
            self.rev = m.group(1)
        # spin_r / spin_t
        m = re.search(r'"__spin_r":(\d+)', html)
        if m:
            self.spin_r = m.group(1)
        m = re.search(r'"__spin_t":(\d+)', html)
        if m:
            self.spin_t = m.group(1)
        # __s (session identifier from login page)
        m = re.search(r'"__s":"([^"]+)"', html)
        if m:
            self.session_s = m.group(1)

    def _load_auth_page(self):
        """Load auth.meta.com login page and extract all tokens."""
        r = self.get(f"{AUTH_URL}/login/?app_id={APP_ID}")
        self._extract(r.text)
        return r.text

    def _load_dev_page(self):
        """Load dev.meta.ai and extract tokens."""
        r = self.get(f"{DEV_URL}/")
        self._extract(r.text)
        return r.text

    # ── Meta GraphQL form builder ──
    def _gql(self, url, doc_id, variables, friendly="", **extra):
        """Build and POST a Meta GraphQL form-encoded request."""
        form = {
            "av": self.actor_id,
            "__user": "0",
            "__a": "1",
            "__req": next_req(),
            "__hs": "20648.HYP:comet_plat_default_pkg.2.1...0",
            "dpr": "1",
            "__ccg": "MODERATE",
            "__rev": self.rev or "1043137552",
            "__s": uid_hex(12) + ":" + uid_hex(6) + ":" + uid_hex(6),
            "__hsi": self.hsi or str(int(time.time() * 1000)),
            "__dyn": "7xeUmwlEnwn8K2Wmh0no6u5U4e0yoW3q32360CEbo1nEhw2nVE4W099w8G1Dz81s8hwnU2lwv89k2C1Fwc60D85m1mzXwae4UaEW0Loco5G0zK1swa-260p2azo11E2ZwrUdUco9E3Lwr8kwl85ucwo82PxW1owtogwbu0Ko1WU3OwRwgU",
            "__csr": "",
            "__hsdp": "",
            "__hblp": "",
            "__sjsp": "",
            "__comet_req": "1",
            "fb_dtsg": self.fb_dtsg or "",
            "jazoest": self.jazoest or "22293",
            "lsd": self.lsd or "",
            "__spin_r": self.spin_r or "1043137552",
            "__spin_b": "trunk",
            "__spin_t": self.spin_t or str(int(time.time())),
            "__jssesw": "1",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly,
            "server_timestamps": "true",
            "variables": json.dumps(variables),
            "doc_id": doc_id,
        }
        form.update(extra)
        return self.parse(self.post(url, data=form).text)

    # ── Meta auth form (different format) ──
    def _auth_form(self, endpoint, fields):
        """POST to auth.meta.com form endpoint with standard Meta fields."""
        base = {
            "__user": "0",
            "__a": "1",
            "__req": next_req(),
            "__hs": "20648.HYP:frl_comet_auth_pkg.2.1...0",
            "dpr": "1",
            "__ccg": "EXCELLENT",
            "__rev": self.rev or "1043132952",
            "__s": uid_hex(12) + ":" + uid_hex(6) + ":" + uid_hex(6),
            "__hsi": self.hsi or str(int(time.time() * 1000)),
            "lsd": self.lsd or "",
            "jazoest": self.jazoest or "22293",
            "__spin_r": self.spin_r or "1043132952",
            "__spin_b": "trunk",
            "__spin_t": self.spin_t or str(int(time.time())),
            "__jssesw": "1",
        }
        base.update(fields)
        return self.parse(self.post(f"{AUTH_URL}/{endpoint}", data=base).text)

    # ================================================================
    # STEP 1: CHECK EMAIL
    # ================================================================
    def check_email(self, email):
        """Check if email is available for registration."""
        if not self.lsd:
            self._load_auth_page()

        fields = {
            "account_reg_info[birthday]": "1998-08-21",
            "account_reg_info[email]": email,
            "account_reg_info[has_youth_consent]": "false",
            "account_reg_info[is_bootstrap_flow]": "false",
            "allow_unconfirmed_email": "false",
            "check_for_pre_registration_restrictions": "true",
            "check_mma_account": "false",
            "contact_point": email,
            "contact_point_type": "EMAIL_ADDRESS",
            "check_ntm_qe": "true",
            "skip_xapp_checks": "false",
            "csi": uid_hex(20),
            "event_client_time": str(time.time()),
            "waterfall_id": self.waterfall,
            "source_app_id": APP_ID,
            "qpl_join_id": uid_hex(16),
        }
        r = self.post(f"{AUTH_URL}/api/check-contact-point-availability/", data={
            **{k: v for k, v in self._base_auth_fields().items()},
            **fields,
        })
        body = self.parse(r.text)
        return "error" not in body or (body.get("payload") or {}).get("contactpoint_available", True)

    def _base_auth_fields(self):
        return {
            "__user": "0", "__a": "1", "__req": next_req(),
            "__hs": "20648.HYP:frl_comet_auth_pkg.2.1...0",
            "dpr": "1", "__ccg": "EXCELLENT",
            "__rev": self.rev or "1043132952",
            "__s": uid_hex(12) + ":" + uid_hex(6) + ":" + uid_hex(6),
            "__hsi": self.hsi or str(int(time.time() * 1000)),
            "lsd": self.lsd or "",
            "jazoest": self.jazoest or "22293",
            "__spin_r": self.spin_r or "1043132952",
            "__spin_b": "trunk",
            "__spin_t": self.spin_t or str(int(time.time())),
            "__jssesw": "1",
        }

    # ================================================================
    # STEP 2: REGISTER
    # ================================================================
    def register(self, email, password, first_name="Brian", last_name="Anderson"):
        """Register account. Returns {account_id, redirect_uri} or {error}."""
        if not self.lsd:
            self._load_auth_page()

        # Get encryption key
        r = self.get(f"{AUTH_URL}/login/?app_id={APP_ID}")
        self._extract(r.text)
        m1 = re.search(r'"keyId":(\d+)', r.text)
        m2 = re.search(r'"publicKey":"([a-f0-9]{64})"', r.text)
        key_id = int(m1.group(1)) if m1 else 140
        pub_key = m2.group(1) if m2 else None

        pwd = encrypt_password(password, key_id, pub_key) if pub_key else password

        # Build redirect_uri (client-side constructed, sent to server)
        nonce = uid_hex(20)
        state = uid()
        redir = (f"https://auth.meta.com/oidc/?app_id={APP_ID}"
                 f"&nonce={nonce}"
                 f"&redirect_uri=https%3A%2F%2Fdev.meta.ai%2Foidc%2Fcallback%2F"
                 f"&response_type=code&scope=openid&state={state}")

        ts = int(time.time())
        fields = {
            "client_consent_timestamp": str(ts),
            "tos_cms_id": "957798449862312",
            "username": "Unused",
            "contact_point": email,
            "contact_point_type": "EMAIL_ADDRESS",
            "csi": uid_hex(20),
            "date_of_birth": "1998-08-21",
            "has_youth_consent": "false",
            "opt_into_marketing": "false",
            "password": pwd,
            "redirect_uri": redir,
            "reg_integrity": base64.b64encode(os.urandom(64)).decode().replace("+", "-").replace("/", "_")[:100],
            "should_save_credentials": "true",
            "source_app_id": APP_ID,
            "waterfall_id": self.waterfall,
            "caa_event_flow": "ntf",
            "entry_point": "login_home",
            "event_client_time": str(time.time()),
            "is_kadabra_zero": "false",
            "regulation_jurisdiction": '["US","US_NY"]',
            "qpl_join_id": uid_hex(16),
        }

        r = self.post(f"{AUTH_URL}/login/device-based/kadabra-register-save-credentials/",
                       data={**self._base_auth_fields(), **fields})
        body = self.parse(r.text)
        payload = body.get("payload", {})

        if payload and payload.get("account_id"):
            self.account_id = str(payload["account_id"])
            self.actor_id = self.account_id
            # Follow redirect_uri if present (sets session cookies)
            redir_url = (body.get("redirect_uri") or
                         payload.get("redirect_uri") or
                         payload.get("redirectURI"))
            if redir_url:
                self.get(redir_url)
            return {"account_id": self.account_id, "uid": payload.get("uid", ""),
                    "redirect": redir_url}

        if body.get("redirect_uri"):
            self.get(body["redirect_uri"])
            return {"redirect_uri": body["redirect_uri"], "account_id": body.get("account_id", "")}

        err = body.get("errorDescription") or body.get("errorSummary") or body.get("error")
        return {"error": err or str(body)[:300]}

    # ================================================================
    # STEP 3: VERIFY OTP
    # ================================================================
    def verify_otp(self, otp_code, account_id=None):
        """Submit OTP to auth.meta.com/api/graphql/.
        
        Note: av=0 (not account_id), __hs uses frl_comet_auth_pkg (auth page).
        Reloads auth page to refresh session before sending confirm.
        """
        aid = account_id or self.account_id or "0"
        # Reload auth page to get fresh session tokens
        self._load_auth_page()
        variables = {
            "input": {
                "confirmation_code": {"sensitive_string_value": otp_code},
                "confirmation_code_type": "OTP_CODE",
                "event_flow": "ntf",
                "rl_client_session_id": uid_hex(20),
                "waterfall_id": self.waterfall,
                "source_app_id": int(APP_ID),
                "qpl_join_id": uid_hex(16),
                "actor_id": "0",  # Must be "0" for OTP confirm
                "client_mutation_id": "1",
            }
        }
        # Use auth-specific form fields (av=0, __hs=frl_comet_auth_pkg)
        form = {
            "av": "0",
            "__user": "0",
            "__a": "1",
            "__req": next_req(),
            "__hs": "20648.HYP:frl_comet_auth_pkg.2.1...0",
            "dpr": "1",
            "__ccg": "EXCELLENT",
            "__rev": self.rev or "1043132952",
            "__s": self.session_s or (uid_hex(12) + ":" + uid_hex(6) + ":" + uid_hex(6)),
            "__hsi": self.hsi or str(int(time.time() * 1000)),
            "__dyn": "7xeUmwlEnwn8K2Wmh0no6u5U4e0yoW3q32360CEbo1nEhw2nVE4W099w8G1Dz81s8hwnU2lwv89k2C1Fwc60D82IzXwae4UaEW0Loco5G0zK1swa-0raazo7u0zE2ZwrU6C2q0XU6O1FwlU5G3y0zo7u0xE2Tw3C8doW",
            "__csr": "",
            "__hsdp": "",
            "__hblp": "",
            "__sjsp": "",
            "__comet_req": "1",
            "fb_dtsg": self.fb_dtsg or "",
            "jazoest": self.jazoest or "22293",
            "lsd": self.lsd or "",
            "__spin_r": self.spin_r or "1043132952",
            "__spin_b": "trunk",
            "__spin_t": self.spin_t or str(int(time.time())),
            "__jssesw": "1",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "FRLConfirmEmailMutation",
            "server_timestamps": "true",
            "variables": json.dumps(variables),
            "doc_id": DOC["otp_confirm"],
        }
        body = self.parse(self.post(f"{AUTH_URL}/api/graphql/", data=form).text)
        data = (body.get("data") or {}).get("confirm_email") or {}
        if data.get("isConfirmed"):
            return {"confirmed": True, "account_id": data.get("accountId", aid)}
        return {"confirmed": False, "raw": body}

    # ================================================================
    # STEP 4: OAUTH REDIRECT
    # ================================================================
    def oauth_login(self):
        """Follow OAuth redirect to establish dev.meta.ai session.
        
        After OTP confirm, load auth.meta.com with app_id to trigger OIDC redirect.
        The server redirects to dev.meta.ai/oidc/callback/ with auth code,
        which sets llm_sess cookie.
        """
        # Step 1: Hit auth.meta.com OIDC endpoint — triggers redirect chain
        oidc_url = (f"{AUTH_URL}/oidc/?app_id={APP_ID}"
                    f"&locale=en_US"
                    f"&nonce={uid_hex(20)}"
                    f"&redirect_uri=https%3A%2F%2Fdev.meta.ai%2Foidc%2Fcallback%2F"
                    f"&response_type=code&scope=openid&state={uid()}")
        r = self.get(oidc_url)
        
        # Step 2: Also directly hit dev.meta.ai to ensure cookies are set
        r2 = self.get(f"{DEV_URL}/")

        # Check session cookies across all domains
        has_sess = False
        for ck in self.s.cookies.jar:
            if ck.name == "llm_sess":
                has_sess = True
            if ck.name == "c_user":
                self.actor_id = ck.value

        # Extract tokens from dev page
        if has_sess:
            self._extract(r2.text)

        return {"has_session": has_sess, "actor_id": self.actor_id,
                "final_url": r2.url if hasattr(r2, 'url') else ""}

    # ================================================================
    # STEP 5: ONBOARDING
    # ================================================================
    def onboard(self, first_name="Brian", last_name="Anderson"):
        """Fill onboarding form."""
        variables = {
            "input": {
                "actor_id": self.actor_id,
                "client_mutation_id": "1",
                "allow_marketing_emails": False,
                "first_name": first_name,
                "last_name": last_name,
            }
        }
        body = self._gql(f"{DEV_URL}/api/graphql/", DOC["onboard_name"], variables,
                          friendly="LLMDCAccountOnboardingPageMutation")
        ok = ((body.get("data") or {}).get("xllm_complete_model_api_account") or {}).get("success", False)
        return ok

    # ================================================================
    # STEP 6: ACCEPT TERMS
    # ================================================================
    def terms(self):
        """Accept Meta AI terms."""
        variables = {
            "input": {
                "actor_id": self.actor_id,
                "client_mutation_id": "1",
                "terms_surface": "LLM_DC_TERMS_MODAL_FLOW",
                "user_id": self.actor_id,
            }
        }
        body = self._gql(f"{DEV_URL}/api/graphql/", DOC["accept_terms"], variables,
                          friendly="LLMDCAcceptUpdatedTermsDialogMutation")
        return ((((body.get("data") or {}).get("xllm_sign_terms_user") or {}).get("viewer") or {}).get("user") or {}).get("has_accepted_terms", False)

    # ================================================================
    # STEP 7: BILLING
    # ================================================================
    def load_billing(self):
        """Load billing info via GraphQL and/or HTML."""
        # First try GraphQL billing query
        try:
            body = self._gql(f"{DEV_URL}/api/billing/graphql/", "24332672802771817", {
                "billableAccountID": None,
                "paymentAccountID": None,
            }, friendly="LLMDBillingHubPageQuery")
            ba = (body.get("data") or {}).get("billable_account_by_asset_id") or {}
            pa = ba.get("billing_payment_account", {})
            if pa.get("id"):
                self.payment_account_id = pa["id"]
            team = ba.get("billing_team", {})
            if team.get("id"):
                self.team_id = team["id"]
        except Exception:
            pass

        # Fallback: load billing page HTML (slower, timeout=60)
        if not self.team_id or not self.payment_account_id:
            try:
                r = self.get(f"{DEV_URL}/billing/", timeout=60)
                self._extract(r.text)
                html = r.text
                m = re.search(r'[?&]team_id=(\d+)', r.url if hasattr(r, 'url') else '')
                if m:
                    self.team_id = m.group(1)
                if not self.team_id:
                    m2 = re.search(r'"team":\s*\{[^}]*"id":"(\d+)"', html)
                    if m2:
                        self.team_id = m2.group(1)
                m3 = re.search(r'"payment_account_id":"(\d+)"', html)
                if m3:
                    self.payment_account_id = m3.group(1)
            except Exception:
                pass

        # Try another GraphQL query to get team_id
        if not self.team_id:
            try:
                body2 = self._gql(f"{DEV_URL}/api/graphql/", "24875768768825331", {},
                                   friendly="LLMDCTeamSettingsPageQuery")
                self.team_id = body2.get("data", {}).get("team", {}).get("id", "")
            except Exception:
                pass

        return {"team_id": self.team_id, "payment_account_id": self.payment_account_id}

    def get_payment_account(self):
        """Query billing to get payment_account_id."""
        billing_url = f"{DEV_URL}/api/billing/graphql/"
        # Query: billable account (need team_id for query)
        body = self._gql(billing_url, "24332672802771817", {
            "billableAccountID": None,
            "paymentAccountID": None,
        }, friendly="LLMDBillingHubPageQuery")

        ba = (body.get("data") or {}).get("billable_account_by_asset_id") or {}
        pa = ba.get("billing_payment_account", {})
        self.payment_account_id = pa.get("id", "")

        if not self.team_id:
            # Try getting team from dev meta graphql
            body2 = self._gql(f"{DEV_URL}/api/graphql/", "24875768768825331", {},
                               friendly="LLMDCTeamSettingsPageQuery")
            self.team_id = body2.get("data", {}).get("team", {}).get("id", "")

        return {"payment_account_id": self.payment_account_id, "team_id": self.team_id}

    def get_encryption_key(self):
        """Get server encryption key for card E2EE."""
        variables = {
            "input": {
                "device_id": "device_id",
                "payment_type": "BILLING_WIZARD",
                "target_account_id": self.payment_account_id,
                "actor_id": self.actor_id,
                "client_mutation_id": "3",
            }
        }
        body = self._gql(f"{DEV_URL}/api/billing/graphql/", DOC["encrypt_key"], variables,
                          friendly="PaymentsCometGetServerEncryptionKeyMutation")
        ek = (body.get("data") or {}).get("get_server_encryption_key") or {}
        return {"trust_chain": ek.get("trust_chain", []), "id": ek.get("id", "")}

    def _generate_trust_token(self, card_number, cvv, exp_month, exp_year):
        """Generate platform_trust_token via ECDH-ES + AES-256-GCM. No TPM needed."""
        if not HAS_CRYPTO:
            return ""

        # 1. Fetch server encryption key
        ek = self.get_encryption_key()
        trust_chain = ek.get("trust_chain", [])
        if not trust_chain:
            return ""

        # 2. Extract EC P-256 public key from cert
        cert_pem = f"-----BEGIN CERTIFICATE-----\n{trust_chain[0]}\n-----END CERTIFICATE-----"
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        server_pubkey = cert.public_key()

        # 3. Compute apv = "fp:" + base64url(SHA256(SPKI_DER))
        spki = server_pubkey.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo
        )
        spki_hash = hashes.Hash(hashes.SHA256())
        spki_hash.update(spki)
        apv = "fp:" + base64.urlsafe_b64encode(spki_hash.finalize()).rstrip(b"=").decode()

        # 4. Generate ephemeral ECDH key pair
        eph_private = ec.generate_private_key(ec.SECP256R1())
        eph_public = eph_private.public_key()

        # 5. ECDH key agreement
        shared_key = eph_private.exchange(ec.ECDH(), server_pubkey)

        # 6. ConcatKDF — flat format matching Meta's JS bundle
        algorithm_id = b"\x00\x00\x00\x07A256GCM"
        party_v_info = apv.encode()
        other_info = algorithm_id + b"" + party_v_info + b"\x00\x00\x00\x00" + b""
        ckdf = ConcatKDFHash(algorithm=hashes.SHA256(), length=32, otherinfo=other_info)
        aes_key = ckdf.derive(shared_key)

        # 7. Encrypt card data
        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)
        plaintext = json.dumps({
            "data": {
                "credit_card": card_number,
                "csc": cvv,
                "expiry_month": str(exp_month),
                "expiry_year": str(exp_year),
            },
            "nonce": str(uuid.uuid4()),
            "op": "ADD_CARD",
            "ver": 1,
        }).encode()
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        # 8. Build JWE compact serialization
        eph_nums = eph_public.public_numbers()
        jwe_header = {
            "alg": "ECDH-ES", "enc": "A256GCM", "apu": "",
            "apv": apv,
            "epk": {
                "kty": "EC", "crv": "P-256",
                "x": base64.urlsafe_b64encode(eph_nums.x.to_bytes(32, 'big')).rstrip(b"=").decode(),
                "y": base64.urlsafe_b64encode(eph_nums.y.to_bytes(32, 'big')).rstrip(b"=").decode(),
            },
        }
        header_b64 = base64.urlsafe_b64encode(json.dumps(jwe_header).encode()).rstrip(b"=").decode()
        iv_b64 = base64.urlsafe_b64encode(nonce).rstrip(b"=").decode()
        ct_b64 = base64.urlsafe_b64encode(ciphertext[:-16]).rstrip(b"=").decode()
        tag_b64 = base64.urlsafe_b64encode(ciphertext[-16:]).rstrip(b"=").decode()
        jwe_compact = f"{header_b64}..{iv_b64}.{ct_b64}.{tag_b64}"

        # 9. Wrap as trust token (signatures: [] is accepted!)
        trust_token = json.dumps({"payload": jwe_compact, "signatures": []})
        return base64.urlsafe_b64encode(trust_token.encode()).rstrip(b"=").decode()

    def save_card(self, card_number, exp_month, exp_year, cvv, name):
        """Save credit card. Returns {success, credential_id} or {error}."""
        # Generate trust token (ECDH-ES encrypted card data)
        trust_token = self._generate_trust_token(card_number, cvv, exp_month, exp_year)

        variables = {
            "input": {
                "actor_id": self.actor_id,
                "client_mutation_id": "2",
                "card_data": {
                    "bin": card_number[:8],
                    "cardholder_name": name,
                    "credit_card_number": {"sensitive_string_value": "$e2ee"},
                    "csc": {"sensitive_string_value": "$e2ee"},
                    "expiry_month": str(exp_month),
                    "expiry_year": f"20{exp_year}" if len(str(exp_year)) == 2 else str(exp_year),
                    "last_4": card_number[-4:],
                },
                "client_info": {
                    "color_depth": "24",
                    "java_enabled": False,
                    "screen_height": "1080",
                    "screen_width": "1920",
                },
                "country": "US",
                "network_tokenization_consent_given": False,
                "payment_account_id": self.payment_account_id,
                "platform_trust_token": trust_token,
                "recurring_payment_consent_given": False,
                "set_default": False,
                "logging_session_data": {
                    "flow_session_id": f"upl_believe_{int(time.time()*1000)}_{uid()}",
                    "upl_session_id": f"upl_{int(time.time()*1000)}_{uid()}",
                },
            },
            "completedTasks": ["add_credit_card"],
            "userIntent": None,
        }
        body = self._gql(f"{DEV_URL}/api/billing/graphql/", DOC["save_card"], variables,
                          friendly="useBillingSaveCreditCardMutation")
        sc = (body.get("data") or {}).get("xfb_billing_save_credit_card") or {}
        if sc.get("credit_card"):
            return {"success": True, "credential_id": sc["credit_card"].get("credential_id", "")}
        errors = body.get("errors", [])
        return {"success": False, "error": errors[0]["message"] if errors else str(body)[:300]}

    # ================================================================
    # STEP 8: CREATE API KEY
    # ================================================================
    def create_api_key(self, name="default"):
        """Create API key. Returns {success, access_token} or {error}."""
        variables = {
            "input": {
                "actor_id": self.actor_id,
                "client_mutation_id": "1",
                "display_name": name,
                "is_created_by_default": False,
                "team": self.team_id,
            },
            "connections": [f"client:{self.team_id}:***"],
        }
        body = self._gql(f"{DEV_URL}/api/graphql/", DOC["create_api_key"], variables,
                          friendly="LLMDCAPIKeyCreateDialogMutation")
        app = ((body.get("data") or {}).get("xllm_create_application") or {}).get("application") or {}
        if app.get("access_token"):
            return {"success": True, "access_token": app["access_token"], "app_id": app.get("id", "")}
        errors = body.get("errors", [])
        return {"success": False, "error": errors[0]["message"] if errors else str(body)[:300]}

    # ================================================================
    # FULL FLOW
    # ================================================================
    def run(self, email=None, password=None, first="Brian", last="Anderson",
            card="4889501032758307", exp_m="08", exp_y="27", cvv="424"):
        """Full registration flow."""
        print("[*] Meta AI API Client v2")

        if not email:
            print("[*] Generating temp email...")
            email, _ = tempmail_generate()
        if not password:
            password = f"Mx{uid_hex(12)}!"

        print(f"[*] {email} / {password}")

        # 1. Check email
        print("[1] Check email...")
        self.check_email(email)
        print("    ✓")

        # 2. Register
        print("[2] Register...")
        reg = self.register(email, password, first, last)
        if "error" in reg:
            return {"status": "error", "step": "register", **reg}
        print(f"    ✓ account_id={reg.get('account_id')}")

        # 3. OTP
        print("[3] Waiting OTP...")
        otp = tempmail_otp(email, 90)
        if not otp:
            return {"status": "error", "step": "otp", "error": "timeout"}
        print(f"    ✓ {otp}")

        # 4. Verify OTP
        print("[4] Verify OTP...")
        v = self.verify_otp(otp, reg.get("account_id"))
        if not v.get("confirmed"):
            # Try with account_id from register
            v = self.verify_otp(otp, reg.get("account_id"))
        if not v.get("confirmed"):
            return {"status": "error", "step": "verify_otp", "result": v}
        print(f"    ✓ confirmed")

        # 5. OAuth login
        print("[5] OAuth login...")
        oauth = self.oauth_login()
        print(f"    ✓ session={oauth['has_session']}, actor={oauth['actor_id']}")

        # 6. Onboarding
        print("[6] Onboarding...")
        ok = self.onboard(first, last)
        print(f"    ✓ {ok}")

        # 7. Terms
        print("[7] Terms...")
        t = self.terms()
        print(f"    ✓ {t}")

        # 8. Billing (skip if no session)
        if not oauth.get("has_session"):
            print("[!] No session established — billing/key steps will fail")
        
        print("[8] Billing...")
        self.load_billing()
        print(f"    ✓ team={self.team_id}, payment={self.payment_account_id}")

        # 9. Encryption key
        print("[9] Encryption key...")
        ek = self.get_encryption_key()
        print(f"    ✓ key_id={ek['id']}")

        # 10. Save card
        print("[10] Save card...")
        sc = self.save_card(card, exp_m, exp_y, cvv, f"{first} {last}")
        if sc.get("success"):
            print(f"    ✓ {sc['credential_id']}")
        else:
            print(f"    ✗ {sc.get('error', 'failed')}")

        # 11. API Key
        print("[11] API key...")
        ak = self.create_api_key()
        if ak.get("success"):
            print(f"    ✓ {ak['access_token']}")
        else:
            print(f"    ✗ {ak.get('error', 'failed')}")

        # Output
        result = {
            "status": "complete" if ak.get("success") else "partial",
            "email": email,
            "password": password,
            "actor_id": self.actor_id,
            "team_id": self.team_id,
            "payment_account_id": self.payment_account_id,
            "api_key": ak.get("access_token", ""),
            "card_saved": sc.get("success", False),
            "cookies": self.cookies_dict(),
        }

        os.makedirs("data/output", exist_ok=True)
        out = f"data/output/account_{int(time.time())}.json"
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n[*] Saved: {out}")
        return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--email")
    p.add_argument("--password")
    p.add_argument("--first", default="Brian")
    p.add_argument("--last", default="Anderson")
    p.add_argument("--card", default="4889501032758307")
    p.add_argument("--exp-month", default="08")
    p.add_argument("--exp-year", default="27")
    p.add_argument("--cvv", default="424")
    args = p.parse_args()

    client = MetaAPI()
    result = client.run(
        email=args.email, password=args.password,
        first=args.first, last=args.last,
        card=args.card, exp_m=args.exp_month,
        exp_y=args.exp_year, cvv=args.cvv,
    )
    print("\n" + "=" * 60)
    print(json.dumps(result, indent=2))
