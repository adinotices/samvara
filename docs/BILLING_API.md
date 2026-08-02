# Samvara Billing API Documentation

## Overview

The billing API handles Stripe payment processing for charge penalties. Ordinary users charge their card directly through Samvara's Stripe account. The app owner can optionally charge through Beeminder instead (owner-only).

**All endpoints require authentication** (Bearer token).

---

## Endpoints

### GET `/v1/billing/status`

Returns the user's billing configuration and current payment method.

**Response:**
```json
{
  "provider": "samvara",
  "hasPaymentMethod": true,
  "cardDisplay": "Visa •••• 4242",
  "canUseBeeminder": false,
  "publishableKey": "pk_test_..."
}
```

**Fields:**
- `provider`: `"samvara"` (Stripe) or `"beeminder"` (owner-only)
- `hasPaymentMethod`: whether a card is on file
- `cardDisplay`: formatted card identification (e.g., "Visa •••• 4242"), or `null`
- `canUseBeeminder`: whether this user can switch to Beeminder (owner only)
- `publishableKey`: Stripe publishable key for client-side SDK initialization

---

### POST `/v1/billing/setup-intent`

Create a Stripe SetupIntent for collecting and saving a card without charging.

**Response:**
```json
{
  "clientSecret": "seti_1234_secret_...",
  "id": "seti_1234"
}
```

**Flow:**
1. Client calls this endpoint
2. Server creates a Stripe customer (if needed) and SetupIntent
3. Client passes `clientSecret` to Stripe SDK's PaymentSheet
4. User collects card details and confirms setup
5. Client calls `/v1/billing/payment-method` with the SetupIntent `id`

**Errors:**
- `400`: STRIPE_SECRET_KEY not configured
- `500`: Stripe API failure

---

### POST `/v1/billing/payment-method`

Confirm a SetupIntent and save the payment method to the user's Stripe customer.

**Request:**
```json
{
  "setupIntentId": "seti_1234"
}
```

**Response:**
```json
{
  "stripePaymentMethodId": "pm_1234",
  "cardBrand": "visa",
  "cardLast4": "4242"
}
```

**Important:**
- The server **does not trust** client-supplied payment method IDs
- The server looks up the payment method from the SetupIntent itself
- This prevents downgrade attacks where a client supplies a different card

**Errors:**
- `400`: STRIPE_SECRET_KEY not configured
- `409`: No Stripe customer on file (call `/v1/billing/setup-intent` first)
- `502`: Stripe API failure or SetupIntent has no attached payment method

---

### DELETE `/v1/billing/payment-method`

Remove the saved payment method from the user's account.

**Response:**
```json
{
  "stripePaymentMethodId": null,
  "cardBrand": null,
  "cardLast4": null
}
```

**Behavior:**
- Detaches payment method from Stripe customer
- Clears card details from user settings
- User cannot report slips/misses until a new card is added

**Errors:**
- `502`: Stripe API failure (non-fatal; still clears local state)

---

### DELETE `/v1/billing/charges/{charge_id}/refund`

Issue a refund against a charge.

**Query Parameters:**
- `amount` (optional): refund amount in USD (e.g., `10.50`). Omit for full refund.

**Response:**
```json
{
  "refundId": "ref_1234"
}
```

**Behavior:**
- Full refund if `amount` omitted
- Partial refund if `amount` specified (rounded to cents)
- Refund is issued immediately to Stripe
- Charge must exist and be from the user's account

**Errors:**
- `400`: STRIPE_SECRET_KEY not configured
- `400`: Missing or invalid charge_id
- `502`: Stripe API failure or charge not found

**Example:**
```bash
# Full refund
curl -X DELETE https://api.samvara.app/v1/billing/charges/pi_1234/refund \
  -H "Authorization: Bearer $TOKEN"

# Partial refund of $10.50
curl -X DELETE https://api.samvara.app/v1/billing/charges/pi_1234/refund?amount=10.50 \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST `/v1/billing/webhook/stripe`

Webhook endpoint for Stripe events. **Not authenticated** (signature verified instead).

**Stripe Configuration:**
- URL: `https://your-domain/v1/billing/webhook/stripe`
- Events: `payment_intent.succeeded`
- Secret: Set `STRIPE_WEBHOOK_SECRET` in environment

**Signature Verification:**
- Stripe sends `Stripe-Signature` header with format: `t=timestamp,v1=signature`
- Server verifies using HMAC-SHA256 with webhook secret
- Timestamp verified to be within 5 minutes (prevents replay)
- Old timestamps rejected automatically by Stripe SDK

**Webhook Processing:**
1. `payment_intent.succeeded` → charge is automatically committed
2. User notification sent if charge was pending (requires_action)
3. Ledger updated with actual charge amount
4. Idempotent on replay (same payment_intent_id → same result)

**Example Webhook Event:**
```json
{
  "type": "payment_intent.succeeded",
  "data": {
    "object": {
      "id": "pi_1234",
      "status": "succeeded",
      "amount": 550,
      "customer": "cus_5678"
    }
  }
}
```

**Error Handling:**
- Invalid signature → `401 Unauthorized`
- Unknown payment_intent_id → logged but `200 OK` (prevents retry spam)
- Duplicate event → idempotent (no double-charge)

---

## Charge Flow

### Happy Path (No Authentication Required)

```
user.slip/miss
    ↓
stripe_billing.charge()
    ↓
payment_intent.status == "succeeded"
    ↓
charge committed immediately
    ↓
user notified
```

### With 3D Secure (Requires Authentication)

```
user.slip/miss
    ↓
stripe_billing.charge()
    ↓
payment_intent.status == "requires_action"
    ↓
charge stored as PENDING (provider_charge_id = payment_intent_id)
    ↓
user notified: "authenticate your card at bank"
    ↓
stripe webhook fires (payment_intent.succeeded)
    ↓
charge committed
    ↓
user notified: "charge completed"
```

---

## Safety Rails

**Per-Charge Floor:**
- Configurable via `MIN_STAKE` (default $1.00)
- Any charge below this is rejected before API call to Stripe

**Per-Charge Cap:**
- Configurable via `MAX_CHARGE` (default $500.00)
- Any charge above this is rejected before API call to Stripe
- Hard circuit breaker against bugs or malicious requests

**Idempotency:**
- All charges include idempotency key (based on commitment ID and lapse type)
- Stripe deduplicates: same key → same PaymentIntent ID
- Server tracks by provider_charge_id to detect retries

**State Machine:**
- Charges transition: PENDING → SUCCEEDED or FAILED
- Failed charges do NOT reduce user's money in the ledger
- Outbox pattern: charge succeeds → then persist (not vice versa)

---

## Error Handling

### Client Errors (4xx)

| Code | Meaning | Recovery |
|------|---------|----------|
| 400 | Invalid input or configuration missing | Check request format; verify Stripe keys set |
| 401 | Unauthorized (invalid/expired token) | Re-authenticate |
| 403 | Forbidden (not owner, can't use Beeminder) | Use Samvara provider or contact owner |
| 404 | Resource not found | Verify charge_id exists |
| 409 | Conflict (e.g., no customer on file) | Call setup-intent first |

### Server Errors (5xx)

| Code | Meaning | Recovery |
|------|---------|----------|
| 502 | Bad Gateway (Stripe API failure) | Retry after delay; check Stripe status |
| 503 | Service Unavailable | Wait for service recovery |

**Retry Strategy:**
- 4xx errors: do not retry (fix the request)
- 5xx errors: retry with exponential backoff (2s, 4s, 8s, 16s)
- Webhook: Stripe retries on non-2xx response; idempotency key prevents double-charge

---

## Testing

### Test Mode

Set `STRIPE_SECRET_KEY=sk_test_...` to use Stripe test mode.

**Test Cards:**
- `4242 4242 4242 4242` — succeeds
- `4000 0025 0000 3155` — requires 3D Secure (requires_action)
- `4000 0000 0000 0002` — declines
- Use any future expiry, any CVC

**Test Customers:**
- Create via `/v1/billing/setup-intent`; Stripe automatically issues test payment methods

### Example Test Flow

```bash
# 1. Get status (confirm no card yet)
curl https://api.samvara.app/v1/billing/status \
  -H "Authorization: Bearer $TEST_TOKEN"

# 2. Create setup intent
SETUP=$(curl -X POST https://api.samvara.app/v1/billing/setup-intent \
  -H "Authorization: Bearer $TEST_TOKEN" | jq -r '.id')

# 3. Confirm setup intent (in real flow, Stripe SDK does this)
# (use Stripe Dashboard or mobile app to confirm the setup intent)

# 4. Save payment method
curl -X POST https://api.samvara.app/v1/billing/payment-method \
  -H "Authorization: Bearer $TEST_TOKEN" \
  -d '{"setupIntentId": "'$SETUP'"}' \
  -H "Content-Type: application/json"

# 5. Charge user (via slip/miss endpoint)
# (this uses the saved card automatically)
```

---

## Migration from Beeminder

If migrating from Beeminder to Stripe:

1. **Existing Beeminder charges:** Continue working (stored charge IDs don't change)
2. **New charges:** Automatically use Stripe unless `chargeProvider == "beeminder"`
3. **Owner:** Can switch back and forth via PATCH `/v1/settings` (non-owners cannot)
4. **Ledger:** Tracks both providers; balance is provider-agnostic

```bash
# Switch to Beeminder (owner only)
curl -X PATCH https://api.samvara.app/v1/settings \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -d '{"chargeProvider": "beeminder"}' \
  -H "Content-Type: application/json"

# Switch back to Stripe
curl -X PATCH https://api.samvara.app/v1/settings \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -d '{"chargeProvider": "samvara"}' \
  -H "Content-Type: application/json"
```

---

## Rate Limiting

No explicit rate limits yet. Monitor Stripe API usage in Stripe Dashboard.

Recommended future additions:
- 100 requests/minute per user (prevents abuse)
- 1000 requests/minute per server (Stripe's limits)
- Webhook delivery tracking (Stripe retries up to 3 days)

---

## Compliance & Security

- **PCI DSS:** Samvara never sees card numbers (Stripe handles them)
- **SCA/3D Secure:** Automatic for cards that require it
- **Webhook Verification:** HMAC-SHA256 signature (cannot be spoofed)
- **GDPR:** Customer data deleted on account erasure
- **Idempotency:** All charges deduplicated by key (no double-charging)

---

## Support & Debugging

**Check Stripe Dashboard:**
- Payments → PaymentIntents (see all charges)
- Customers (see customer IDs, payment methods)
- Logs → Webhook deliveries (see event retries)

**Common Issues:**

1. **"No payment method on file"** → Call `/v1/billing/setup-intent` first
2. **"SetupIntent has no attached payment method"** → SetupIntent confirmation failed on client
3. **"Stripe request failed"** → Network error or invalid credentials (check STRIPE_SECRET_KEY)
4. **Charge pending but never completes** → Customer didn't authenticate; check card type (requires SCA)
5. **Webhook not firing** → Check STRIPE_WEBHOOK_SECRET is set and matches Stripe Dashboard

**Logs:**
- All Stripe errors logged with request_id for correlation
- Webhook deliveries logged with event type and payment_intent_id
- Check server logs for `samvara.stripe` logger
