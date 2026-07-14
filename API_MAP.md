# Meta AI API Map (Reverse Engineered)

## Auth Flow
1. GET `auth.meta.com/login/?app_id=2403310080153219` → extract `lsd`, `jazoest`, `fb_dtsg`, `__hsi`, `__rev`, `__spin_r`, `__spin_t`
2. POST `auth.meta.com/api/check-contact-point-availability/` → verify email available
3. POST `auth.meta.com/login/device-based/kadabra-register-save-credentials/` → register account
4. POST `auth.meta.com/api/graphql/` doc_id=9851798224911796 → verify OTP
5. GET `auth.meta.com/oidc/?app_id=2403310080153219&redirect_uri=...` → OAuth redirect
6. GET `dev.meta.ai/oidc/callback/` → session established

## Onboarding
7. POST `dev.meta.ai/api/graphql/` doc_id=37615747154690842 → fill name (xllm_complete_model_api_account)
8. POST `dev.meta.ai/api/graphql/` doc_id=9665990526769906 → accept terms (xllm_sign_terms_user)

## Billing
9. POST `dev.meta.ai/api/billing/graphql/` doc_id=23994203586844376 → get encryption key
10. POST `dev.meta.ai/api/billing/graphql/` doc_id=26853726450994905 → BIN lookup
11. POST `dev.meta.ai/api/billing/graphql/` doc_id=26656707574002201 → save card (xfb_billing_save_credit_card)

## API Key
12. POST `dev.meta.ai/api/graphql/` doc_id=26450098374584540 → create key (xllm_create_application)

## Key Variables
- app_id: 2403310080153219
- source_app_id: 2403310080153219
- fb_dtsg: extracted from login page
- lsd: extracted from login page
- jazoest: extracted from login page

## Save Card Variables
- credit_card_number: $e2ee (ECDH encrypted)
- csc: $e2ee (ECDH encrypted)
- platform_trust_token: 1060 chars (needs real TPM on Windows)
- payment_account_id: extracted from billing page load
- actor_id: user_id from cookie

## Card Details
- 4889501032758307
- Expiry: 08/27
- CVV: 424
- Name: Brian Anderson
