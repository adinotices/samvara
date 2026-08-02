# Samvara Billing: Deployment & Setup Guide

This guide walks through setting up Stripe billing for Samvara in development, staging, and production environments.

---

## Prerequisites

- Stripe account (create at https://stripe.com)
- React Native client with Stripe SDK installed (@stripe/stripe-react-native)
- Backend running FastAPI with stripe_billing.py module
- HTTPS endpoint (required by Stripe webhooks)

---

## 1. Stripe Account Setup

### 1.1 Create Stripe Account

1. Go to https://stripe.com/start
2. Sign up or log in
3. Verify email
4. Stripe Dashboard loads → https://dashboard.stripe.com

### 1.2 Get API Keys

**Test Mode (Development):**

1. Dashboard → Developers → API Keys (top right)
2. Copy test keys:
   - **Publishable Key** (starts with `pk_test_`)
   - **Secret Key** (starts with `sk_test_`)

**Live Mode (Production):**

1. Same path, toggle "Live keys" (right side of API Keys)
2. Copy live keys:
   - **Publishable Key** (starts with `pk_live_`)
   - **Secret Key** (starts with `sk_live_`)

⚠️ **Never commit secret keys to git. Use environment variables only.**

---

## 2. Environment Configuration

### 2.1 Development (.env.local or .env)

```bash
# Backend Stripe keys (test mode)
STRIPE_SECRET_KEY=sk_test_YOUR_SECRET_KEY_HERE
STRIPE_PUBLISHABLE_KEY=pk_test_YOUR_PUBLISHABLE_KEY_HERE

# Webhook signing secret (get from step 3.2)
STRIPE_WEBHOOK_SECRET=whsec_test_YOUR_WEBHOOK_SECRET

# Money safety rails
MIN_STAKE=1.00
MAX_CHARGE=500.00

# Auth
AUTH_MODE=token
API_TOKEN=local-dev-token

# Database
SAMVARA_DB=samvara-dev.db
```

### 2.2 Staging (.env.staging)

```bash
# Same as development, but with staging URLs
STRIPE_SECRET_KEY=sk_test_YOUR_STAGING_SECRET_KEY
STRIPE_PUBLISHABLE_KEY=pk_test_YOUR_STAGING_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET=whsec_test_YOUR_STAGING_WEBHOOK_SECRET

# Point to staging database/services
SAMVARA_DB=/data/samvara-staging.db
DATABASE_URL=postgresql://user:pass@staging-db.internal/samvara

# More permissive for testing
MAX_CHARGE=5000.00
```

### 2.3 Production (.env.production)

```bash
# Live Stripe keys (charged to real customer cards)
STRIPE_SECRET_KEY=sk_live_YOUR_PRODUCTION_SECRET_KEY
STRIPE_PUBLISHABLE_KEY=pk_live_YOUR_PRODUCTION_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET=whsec_live_YOUR_PRODUCTION_WEBHOOK_SECRET

# Production database
DATABASE_URL=postgresql://user:pass@prod-db.cloud/samvara

# Tighter safety rails for production
MIN_STAKE=1.00
MAX_CHARGE=500.00

# Authentication
AUTH_MODE=oauth
OAUTH_CLIENT_ID=...

# Monitoring
SENTRY_DSN=https://...
LOG_LEVEL=WARNING
```

---

## 3. Webhook Setup

### 3.1 Create Webhook Endpoint

1. Dashboard → Developers → Webhooks (left sidebar)
2. Click "Add endpoint"
3. Endpoint URL: `https://your-domain.com/v1/billing/webhook/stripe`
4. Events to send:
   - Select `payment_intent.succeeded`
   - Optionally: `payment_intent.payment_failed` (for future handling)
5. Click "Add endpoint"

### 3.2 Get Webhook Secret

1. Click the endpoint you just created
2. Scroll to "Signing secret"
3. Click "Reveal" (if needed)
4. Copy the secret (starts with `whsec_`)
5. Add to `.env`: `STRIPE_WEBHOOK_SECRET=whsec_...`

### 3.3 Test Webhook Locally (Development)

For local development, use Stripe CLI to forward webhooks:

```bash
# 1. Install Stripe CLI: https://stripe.com/docs/stripe-cli

# 2. Authenticate (opens browser)
stripe login

# 3. Forward webhooks to local server
stripe listen --forward-to localhost:8000/v1/billing/webhook/stripe

# Output shows:
# > Ready! Your webhook signing secret is: whsec_test_...
# Copy this to STRIPE_WEBHOOK_SECRET in .env

# 4. In another terminal, trigger test events
stripe trigger payment_intent.succeeded
```

### 3.4 Verify Webhook Connectivity

1. Dashboard → Developers → Webhooks
2. Click your endpoint
3. Scroll to "Events" section
4. Trigger a test event:
   - Click "Send test webhook"
   - Select `payment_intent.succeeded`
   - Click "Send test webhook"
5. Check result → should show "200" (success)

If webhook fails:
- Check server is running and accessible at the URL
- Check `STRIPE_WEBHOOK_SECRET` matches exactly
- Check server logs for HMAC verification errors
- Verify endpoint isn't behind IP whitelist that excludes Stripe IPs

---

## 4. Client Setup

### 4.1 React Native Stripe SDK

In your React Native app:

```bash
npm install @stripe/stripe-react-native
```

### 4.2 Initialize StripeProvider

In `App.tsx`:

```typescript
import { StripeProvider } from '@stripe/stripe-react-native';

export default function App() {
  return (
    <StripeProvider publishableKey={STRIPE_PUBLISHABLE_KEY}>
      {/* rest of app */}
    </StripeProvider>
  );
}
```

The publishableKey is returned by `GET /v1/billing/status`.

### 4.3 Fetch Publishable Key from Server

```typescript
// In your API client
async function getBillingStatus() {
  const response = await fetch('/v1/billing/status', {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return response.json();
  // { publishableKey: "pk_test_...", ... }
}
```

Then initialize StripeProvider with the fetched key, or initialize it statically and update dynamically.

---

## 5. Test Mode Workflow

### 5.1 Development Flow

1. **Set test keys in .env:**
   ```
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   ```

2. **Restart server:**
   ```bash
   python -m uvicorn app.main:app --reload
   ```

3. **Run test suite:**
   ```bash
   python -m pytest tests/ -q
   ```
   Should show all tests passing (121 passed).

4. **Manual testing:**
   - Use test card `4242 4242 4242 4242` (succeeds)
   - Use test card `4000 0025 0000 3155` (requires 3D Secure)
   - Any future expiry, any CVC

### 5.2 Test Cards

| Card Number | Behavior | Use Case |
|---|---|---|
| 4242 4242 4242 4242 | Succeeds | Happy path |
| 4000 0025 0000 3155 | Requires 3D Secure | Authentication flow |
| 4000 0000 0000 0002 | Declines | Error handling |
| 4000 0000 0000 0069 | Network error | Failure recovery |
| 5555 5555 5555 4444 | Mastercard succeeds | Card variety |

Use **any future expiry** (e.g., 12/25) and **any 3-digit CVC** (e.g., 123).

---

## 6. Staging Deployment

### 6.1 Pre-Deployment Checklist

- [ ] All tests passing locally
- [ ] Stripe test keys verified in staging environment
- [ ] Webhook secret configured in staging
- [ ] Webhook endpoint accessible (test with curl)
- [ ] Database migrations run
- [ ] Startup validation passes (checks for STRIPE_SECRET_KEY)

### 6.2 Deploy to Staging

```bash
# 1. Push to staging branch
git push origin main:staging

# 2. CI runs tests
# 3. CD deploys to staging environment
# 4. Verify in Stripe Dashboard:
#    - Stripe is using test keys (not live)
#    - Webhook events appear in Webhooks log

# 5. Manual smoke test:
#    - Add a test card via PaymentMethodScreen
#    - Report a slip (should charge)
#    - Check Stripe Dashboard → Payments for the charge
```

### 6.3 Staging Testing Checklist

- [ ] Sign up and add test card
- [ ] Report slip/miss → charge succeeds
- [ ] Check Stripe Dashboard for payment_intent
- [ ] Remove card → DELETE request succeeds
- [ ] Try to report slip without card → 400 error
- [ ] Add 3D Secure card (`4000 0025 0000 3155`) → charge pending
- [ ] Complete 3D Secure in Stripe Dashboard
- [ ] Charge commits automatically (webhook fires)
- [ ] Refund a charge via admin endpoint → refund appears in Dashboard
- [ ] Check logs for no errors

---

## 7. Production Deployment

⚠️ **PRODUCTION MOVES REAL MONEY. Do not proceed without:**
- [ ] Security review completed
- [ ] Legal review of Terms/Privacy completed
- [ ] Staging testing fully passed
- [ ] Backup/restore procedures tested
- [ ] Monitoring and alerting configured
- [ ] Support runbook prepared
- [ ] First charge manually verified

### 7.1 Transition to Live Keys

1. **In Stripe Dashboard:**
   - Switch to Live keys (top right)
   - Copy `sk_live_...` and `pk_live_...`

2. **Create new webhook for production:**
   - Developers → Webhooks → Add endpoint
   - URL: `https://samvara.app/v1/billing/webhook/stripe`
   - Get the live signing secret (`whsec_live_...`)

3. **Update production environment:**
   ```bash
   # Set these via your deployment system (Fly.io, Heroku, etc.)
   # NEVER commit to git
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_PUBLISHABLE_KEY=pk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_live_...
   ```

4. **Verify keys are correct:**
   - Check server startup logs: should see "stripe initialization successful"
   - No error about STRIPE_SECRET_KEY missing

### 7.2 First Real Charge

1. **Have the owner add their card to production**
2. **Manually create a commitment with $1 stake**
3. **Report a slip → should charge $1 to their actual card**
4. **Verify in Stripe Dashboard:**
   - Payments → PaymentIntents
   - Should see the charge with status "Succeeded"
   - Amount should be $1.00 + Stripe fees
5. **Verify ledger:**
   - Check database: penalty_ledger should show the charge
   - Balance should reflect the charge
6. **Email confirmation should send to cardholder**

### 7.3 Launch Phases

**Phase 1: Invite-Only (Week 1)**
- Small group of trusted testers (5-10)
- Monitor for issues daily
- Real money flowing, but small amounts
- Check Stripe Dashboard daily for unexpected charges

**Phase 2: Expanded Beta (Week 2-3)**
- Open to more users (50-100)
- Monitor metrics: charge success rate, webhook latency
- Watch for support complaints
- Scale database if needed

**Phase 3: Public (Week 4+)**
- Announce publicly
- Expect growth in users and charge volume
- Monitor Stripe API quotas
- Continue watching for fraud/abuse

---

## 8. Monitoring & Alerting

### 8.1 Key Metrics to Monitor

**Stripe API:**
- Charge success rate (should be >99%)
- Webhook delivery latency (should be <1s)
- Webhook delivery failures (should be 0)
- API error rate (should be <1%)

**Application:**
- Payment method add success rate
- Refund request success rate
- Pending charge timeout (charges stuck in requires_action)

### 8.2 Set Up Alerts

**In your monitoring system (e.g., Sentry, Datadog):**

```python
# Alert if charge success rate drops below 95%
if charge_success_rate < 0.95:
    alert("Stripe charge success rate low")

# Alert if webhook delivery is slow
if webhook_latency_p99 > 5000:  # ms
    alert("Stripe webhook latency high")

# Alert if Stripe API fails
if stripe_api_errors > 10:  # per minute
    alert("Stripe API errors spike")
```

### 8.3 Incident Response

**Stripe is down:**
- Users cannot add cards or charge
- Pending charges stuck (user notified to retry)
- Action: Post maintenance notice, disable charge paths temporarily

**Webhook is down:**
- Charges succeed at Stripe but don't commit in database
- Action: Manually trigger reconciliation (resync pending charges from Stripe)

**Card declines spike:**
- Many charges failing
- Action: Review Stripe logs, check if there's a fraud filter triggered

---

## 9. Troubleshooting

### Issue: "STRIPE_SECRET_KEY is not set"

**Cause:** Environment variable not found at startup

**Fix:**
1. Verify `.env` file exists and has the key
2. Check key is not commented out or empty
3. Restart server: `python -m uvicorn app.main:app --reload`
4. Check startup logs for confirmation

### Issue: Webhook returns 401 Unauthorized

**Cause:** HMAC verification failed (wrong secret or tampered request)

**Fix:**
1. Verify `STRIPE_WEBHOOK_SECRET` matches Stripe Dashboard exactly
2. Check Stripe Dashboard → that specific endpoint → Signing secret
3. Verify no typos (copy-paste both and compare)
4. Resync secret if unsure

### Issue: Webhook returns 404 Not Found

**Cause:** Endpoint URL wrong or server not accessible

**Fix:**
1. Verify endpoint URL is exactly: `https://your-domain.com/v1/billing/webhook/stripe`
2. Check server is running: `curl https://your-domain.com/health`
3. Check firewall/proxy isn't blocking POST requests
4. Check Stripe IP addresses aren't blocked (see Stripe docs)

### Issue: Charge succeeds at Stripe but doesn't commit in database

**Cause:** Webhook not delivered or processing failed

**Fix:**
1. Check Stripe Dashboard → Webhooks → that endpoint → Events tab
2. Find the payment_intent.succeeded event
3. Check "Response" column (should show 200)
4. If status is "Retrying" or "Failed", check server logs for errors
5. If webhook was never sent, verify Stripe has correct endpoint URL

### Issue: Test card `4242 4242 4242 4242` declines in production

**Cause:** Stripe live mode doesn't accept test cards (by design)

**Fix:**
1. Use a real card for production testing (use a low stake like $0.01)
2. Or stay in test mode longer
3. Don't switch to `sk_live_` keys until fully ready

### Issue: 3D Secure charge never completes

**Cause:** Customer didn't authenticate in their bank app

**Fix:**
1. Check Stripe Dashboard → Payment → that payment_intent
2. Look for "requires_action" status
3. Check if there's a 3D Secure authentication form
4. Customer must complete bank authentication
5. Webhook will fire when they do

---

## 10. Security Checklist

- [ ] Secret keys never in git or logs
- [ ] HTTPS only (Stripe enforces this for webhooks)
- [ ] Webhook secret verified with HMAC-SHA256
- [ ] Webhook timestamp checked (within 5 minutes)
- [ ] Never trust client-supplied payment method IDs (server looks them up)
- [ ] Card details never logged or stored in database
- [ ] Per-charge caps enforced before Stripe API call
- [ ] Idempotency keys prevent double-charging on retries
- [ ] All Stripe errors logged for audit trail
- [ ] Access logs include request IDs for debugging

---

## 11. Stripe Dashboard Quick Reference

**Common paths:**
- API Keys: Developers → API Keys
- Webhooks: Developers → Webhooks
- Payments: Payments → PaymentIntents
- Customers: Customers
- Refunds: Payouts → Refunds
- Disputes: Disputes
- Settings: Settings → Business Profile

**Test mode tip:** Everything is "test" until you explicitly flip to live keys (toggle at top right).

---

## Reference

- [Stripe API Docs](https://stripe.com/docs/api)
- [Stripe CLI Docs](https://stripe.com/docs/stripe-cli)
- [PaymentIntent Guide](https://stripe.com/docs/payments/payment-intents)
- [3D Secure Guide](https://stripe.com/docs/payments/3d-secure)
- [Webhook Signatures](https://stripe.com/docs/webhooks/signatures)
