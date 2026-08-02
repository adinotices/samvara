# Samvara Billing: Monitoring & Logging Guide

This guide covers monitoring, logging, and alerting strategies for Stripe billing operations to ensure reliability and detect issues quickly.

---

## Overview

Billing operations are critical and move real money. Effective monitoring allows you to:

1. **Detect failures immediately** (card declines, Stripe API issues)
2. **Spot trends** (increasing failure rates, fraud patterns)
3. **Debug production issues** (trace a charge from user action to ledger)
4. **Respond to incidents** (runbook for when things break)

---

## 1. Logging Strategy

### 1.1 What Gets Logged

**Every charge operation logs:**
- User ID (for audit trail)
- Amount and currency
- Customer ID and payment method ID
- Charge provider (Stripe vs. Beeminder)
- Status (succeeded, requires_action, failed)
- Provider charge ID (for tracking)
- Duration (latency to Stripe)
- Any errors with full context

**Example:**
```json
{
  "ts": "2026-08-02T12:41:35.257Z",
  "level": "INFO",
  "logger": "samvara.stripe",
  "request_id": "62b0e29bae6b",
  "message": "stripe charge succeeded",
  "amount": 5.0,
  "customer": "cus_1234",
  "payment_method": "pm_5678",
  "provider_charge_id": "pi_abcd"
}
```

**Webhook operations log:**
- Event type (payment_intent.succeeded)
- Payment intent ID
- Event timestamp
- Signature verification result
- Charge lookup result
- Commitment update result

**Card management logs:**
- Setup intent ID
- Payment method ID
- Customer ID
- Card brand and last 4
- Operation (add, remove, update)
- Result (success/failure)

### 1.2 Log Levels

**ERROR** — Something broke that requires immediate attention:
- Stripe API returned 5xx error
- Network timeout
- Webhook signature verification failed
- Database corruption detected

**WARNING** — Unusual but recoverable:
- Card declined (expected occasionally)
- SetupIntent has no payment method (client error)
- Webhook received after 5-minute window (possible clock skew)

**INFO** — Normal operations:
- Charge succeeded
- Charge pending (3D Secure)
- Card added/removed
- Webhook processed

**DEBUG** — Verbose operational details:
- Request/response bodies
- HMAC calculation intermediates
- Query execution times

### 1.3 Structured Logging

All billing logs include:

```python
{
  "ts": "ISO8601 timestamp",
  "level": "INFO|WARNING|ERROR|DEBUG",
  "logger": "samvara.stripe",
  "request_id": "unique correlation id across request",
  "user_id": "user performing action (if available)",
  "message": "human-readable summary",
  # operation-specific fields:
  "charge_id": "pi_...",
  "amount": 5.0,
  "status": "succeeded",
  "error": "if applicable",
  "duration_ms": 234
}
```

**Why structured:** Each field is query-able in centralized logging (e.g., Datadog, Sentry). You can find "all charges >$100 that took >5s" with one query.

---

## 2. Key Metrics to Track

### 2.1 Charge Metrics

**Success Rate**
```
successful_charges / total_charge_attempts
Target: >99%
Alert if: drops below 95%
```

**Latency**
```
time from charge() call to Stripe response
P50 (median): <500ms
P99 (99th percentile): <2000ms
Alert if: P99 > 5000ms for 10 minutes
```

**Failure Breakdown**
```
- Card declined: X%
- Network timeout: Y%
- Stripe 5xx error: Z%
- Other: W%
```

**Example dashboard:**
```
Today's Charges
├─ Total: 342 charges
├─ Succeeded: 338 (98.8%)
├─ Declined: 3 (0.9%)
├─ Failed (Stripe error): 1 (0.3%)
├─ P50 latency: 380ms
└─ P99 latency: 1840ms
```

### 2.2 Card Management Metrics

**Setup Intents**
```
successful_setups / total_setup_attempts
Target: >95% (accounts for user abandonment)
Alert if: drops below 80%
```

**Payment Method Removals**
```
successful_removals / total_removal_attempts
Target: 100% (should rarely fail)
Alert if: any failures
```

### 2.3 Webhook Metrics

**Delivery Latency**
```
time from Stripe sends webhook to server processes it
Target: <1000ms
Alert if: P99 > 5000ms
```

**Delivery Reliability**
```
successful_deliveries / total_deliveries_attempted
(Stripe retries automatically on non-2xx response)
Target: 100%
Alert if: any failures
```

**Charge Commit Lag**
```
time from charge() returns "requires_action"
to webhook fires "succeeded"
Target: <60 seconds (most 3D Secure completes quickly)
Alert if: charge stuck in requires_action for >24 hours
```

### 2.4 Business Metrics

**Daily Revenue**
```
sum(successful_charges)
Trend over time to spot declines
Alert if: revenue drops >30% vs. 30-day average
```

**User Onboarding**
```
users_with_payment_method / total_users
Target: high (more users can be charged)
Trend: should increase after feature launch
Alert if: stays flat (users can't add cards)
```

**Repeat Charge Success**
```
successful_repeat_charges / total_repeat_charges
(charges after first one per user)
Target: >99% (should be better than first charge)
Alert if: drops below first-charge rate
```

---

## 3. Logging Implementation

### 3.1 Standard Python Logging

```python
import logging

log = logging.getLogger("samvara.stripe")

# Successful charge
log.info("stripe charge succeeded", extra={
    "amount": 5.0,
    "provider_charge_id": "pi_123",
    "duration_ms": 234
})

# Error with context
log.error("stripe charge failed", extra={
    "amount": 5.0,
    "error": "Card declined",
    "error_code": "card_declined",
    "duration_ms": 450
})
```

### 3.2 Request ID Correlation

Every request gets a unique ID for tracing across logs:

```python
# In middleware (already implemented in main.py)
request_id = request.headers.get("X-Request-Id") or generate_id()

# Log it everywhere
log.info("message", extra={"request_id": request_id, ...})

# Client can pass it for debugging
curl -H "X-Request-Id: my-unique-id" https://api.samvara.app/v1/commitments/123/slip
```

### 3.3 Structured Context

```python
# BAD: unstructured message
log.error("Charge failed: 402 Card declined for user 123")

# GOOD: structured fields
log.error("stripe charge failed", extra={
    "http_status": 402,
    "stripe_error_code": "card_declined",
    "user_id": 123,
    "amount": 5.0,
    "commitment_id": "c_456"
})
```

---

## 4. Centralized Logging Setup

### 4.1 Send Logs to External Service

**Option A: Sentry (Error Tracking)**

```python
import sentry_sdk

sentry_sdk.init(
    dsn="https://key@sentry.io/project",
    traces_sample_rate=0.1,  # log 10% of transactions
)

# Automatically captures exceptions and sends
log.error("charge failed", extra={...})
```

**Option B: Datadog (Logs + Metrics)**

```python
from datadog import statsd, initialize

initialize(statsd_port=8125)

# Log via syslog or JSON
log.info("charge succeeded", extra={...})

# Metric
statsd.increment("stripe.charge.succeeded", tags=[f"user:{user_id}"])
```

**Option C: ELK Stack (Elasticsearch + Logstash + Kibana)**

Self-hosted, more control, log everything.

**Option D: CloudWatch (AWS)**

If running on AWS, use CloudWatch Logs for centralized storage.

### 4.2 Log Aggregation

```python
# Ship all logs to central system
import logging.handlers

handler = logging.handlers.SysLogHandler(address=("log-server", 514))
handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(handler)
```

---

## 5. Alerting

### 5.1 Alert Rules

**CRITICAL (Page on-call):**
- Stripe API down (5xx errors for >5 minutes)
- Webhook signature verification failing
- Database connection lost (can't commit charges)

**HIGH (Alert immediately, may not require page):**
- Charge success rate drops below 90% for 15 minutes
- Webhook latency P99 > 10 seconds for 10 minutes
- Pending charges stuck for >6 hours
- More than 10 payment method removals failing in 1 hour

**MEDIUM (Alert daily summary):**
- Charge success rate below 95%
- Card decline rate above 5%
- Any refund operation failing

**LOW (Track but don't alert):**
- Daily revenue trending
- User onboarding metrics
- First-time setup success rate

### 5.2 Alert Implementation

**Using Prometheus + AlertManager:**

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'samvara'
    static_configs:
      - targets: ['localhost:8000']

# alert.rules
alert:
  - name: StripeChargeHighFailureRate
    expr: |
      rate(stripe_charge_failed[5m]) / 
      rate(stripe_charge_attempted[5m]) > 0.1
    for: 10m
    annotations:
      summary: "Stripe charge failure rate >10%"
      
  - name: StripeWebhookLatencyHigh
    expr: stripe_webhook_latency_p99 > 10000
    for: 10m
    annotations:
      summary: "Stripe webhook P99 latency >10s"
```

**Using Sentry:**

```python
import sentry_sdk

sentry_sdk.capture_exception(exception)  # auto-alerts on new issue types
```

---

## 6. Incident Response Playbook

### 6.1 "Charge success rate is low"

1. **Check Stripe Status** → https://status.stripe.com
   - Is Stripe having an outage? Wait.

2. **Check Recent Logs**
   ```bash
   grep -i "stripe charge failed" /var/log/samvara.log | tail -50
   ```

3. **Identify Root Cause**
   - All failures are "card declined"? → Likely customer cards, not our issue.
   - All failures are network timeouts? → Check internet connection.
   - Mix of errors? → Check Stripe API keys, webhook secret.

4. **Action**
   - Network issue: Restore connectivity.
   - Stripe down: Post maintenance notice, disable charge endpoints.
   - Customer cards: Auto-disable charges temporarily, notify users.

### 6.2 "Webhooks are not processing"

1. **Check Recent Logs**
   ```bash
   grep -i "webhook" /var/log/samvara.log | tail -20
   ```

2. **Is the webhook endpoint accessible?**
   ```bash
   curl -X POST https://api.samvara.app/v1/billing/webhook/stripe \
     -H "Stripe-Signature: invalid" -d '{}'
   # Should return 401 (signature mismatch), not 502 or 504
   ```

3. **Check STRIPE_WEBHOOK_SECRET**
   - Is it set? `echo $STRIPE_WEBHOOK_SECRET | wc -c` (should be >20)
   - Does it match Stripe Dashboard? Copy-paste both and compare.

4. **Manually Trigger Webhook**
   ```bash
   stripe trigger payment_intent.succeeded
   # Check logs within 2 seconds
   ```

5. **If still failing:**
   - Manually reconcile pending charges:
     ```bash
     # Get all pending charges from database
     SELECT * FROM penalty_ledger WHERE status='pending' AND created_at < NOW() - INTERVAL '1 hour';
     
     # For each, check Stripe status
     curl https://api.stripe.com/v1/payment_intents/pi_xxx \
       -u "sk_test_..."
     
     # If succeeded at Stripe, manually commit in DB
     ```

### 6.3 "Pending charge is stuck"

1. **Check Stripe Dashboard**
   - Payments → PaymentIntents → find the payment_intent_id
   - What's the status? (requires_action, processing, succeeded, failed)

2. **If status = "succeeded"**
   - Webhook didn't fire or failed to commit
   - Manually commit in database:
     ```sql
     UPDATE penalty_ledger 
     SET status='succeeded' 
     WHERE provider_charge_id='pi_xxx' AND status='pending';
     ```

3. **If status = "requires_action"**
   - User didn't complete 3D Secure authentication
   - Send reminder notification or auto-dismiss after 24 hours

4. **If status = "failed"**
   - Already marked failed; no action needed

---

## 7. Metrics Dashboards

### 7.1 Real-Time Dashboard

**Display (auto-refreshing every 30s):**
```
╔════════════════════════════════════════════════════════╗
║ STRIPE BILLING — LAST 24 HOURS                         ║
├────────────────────────────────────────────────────────┤
║ Charges Attempted:     1,247                            ║
║ Succeeded:              1,238 (99.3%)  ✓                ║
║ Declined:                    6  (0.5%)                 ║
║ Failed (Stripe):              3  (0.2%)  ⚠              ║
│                                                          │
║ P50 Latency:            420ms                            ║
║ P99 Latency:          1,850ms                            ║
│                                                          │
║ Webhooks Received:        1,205                         ║
║ Webhooks Succeeded:       1,205 (100%) ✓                ║
║ Webhooks Failed:              0                         ║
│                                                          │
║ Cards Added:                 42                         ║
║ Cards Removed:               15                         ║
║ Revenue (USD):           $6,240.50                       ║
╚════════════════════════════════════════════════════════╝
```

### 7.2 Datadog Dashboard (Example)

- Top: Charge success rate (line chart, >95% green, <90% red)
- Middle: Charge latency (P50, P95, P99 bars)
- Bottom: Webhook delivery rate (metric + error distribution)
- Right: Daily revenue (bar chart)

### 7.3 Grafana Dashboard (Prometheus)

Query examples:
```promql
# Charge success rate
sum(rate(stripe_charge_succeeded[5m])) / sum(rate(stripe_charge_attempted[5m]))

# Charge latency P99
histogram_quantile(0.99, stripe_charge_latency_seconds_bucket)

# Webhook latency P99
histogram_quantile(0.99, stripe_webhook_latency_seconds_bucket)
```

---

## 8. Debugging Production Issues

### 8.1 Trace a Single Charge

Use request ID to find all related logs:

```bash
# 1. Find charge in API logs
grep "request_id=abc123" /var/log/samvara.log

# 2. Should see:
# - /v1/commitments/123/slip called
# - Charge attempted (payment_intent created)
# - Response returned to client

# 3. If charge required 3D Secure:
# - Status: "requires_action"
# - Payment intent ID: pi_xyz
# - Wait for webhook

# 4. Check webhook delivery
grep "payment_intent_id=pi_xyz" /var/log/samvara.log

# 5. Should see:
# - Webhook received
# - Signature verified
# - Charge lookup (found pending)
# - Charge committed (ledger updated)
```

### 8.2 Common Issues & Log Signatures

**Card Declined**
```
log message: "stripe charge failed"
http_status: 402
stripe_error_code: "card_declined"
```

**Network Timeout**
```
log message: "stripe request failed"
error_type: "ConnectError" or "TimeoutError"
duration_ms: ~15000 (timeout threshold)
```

**Invalid Secret Key**
```
log message: "stripe request failed"
http_status: 401
stripe_error: "Invalid API Key"
```

**Webhook Signature Failed**
```
log message: "webhook verification failed"
reason: "invalid hmac" or "timestamp too old"
```

---

## 9. Performance Tuning

### 9.1 Stripe API Performance

**Expected Latencies:**
- Create PaymentIntent: 100-300ms
- Confirm PaymentIntent: 100-300ms
- Get PaymentMethod: 50-150ms
- Create SetupIntent: 100-300ms
- Create Refund: 150-400ms

**If latency is high:**
1. Check Stripe status page
2. Check your internet connection
3. Check server CPU usage (if high, Stripe calls queue)
4. Check Stripe API rate limits (via dashboard)

### 9.2 Database Performance

**Expected for charge commit:**
- Update charge status: <5ms (indexed by provider_charge_id)
- Insert ledger entry: <5ms
- Update user settings: <5ms

**If slow:**
1. Check database CPU usage
2. Check for table locks (concurrent transactions)
3. Add index if missing: `CREATE INDEX charge_provider_id ON penalty_ledger(provider_charge_id)`

### 9.3 Concurrency

**If multiple charges happen simultaneously:**
- Each charge serialized behind `_charge_lock` (asyncio.Lock)
- Lock held ~500ms (duration of Stripe API call)
- Queue builds up during high load
- Consider: Postgres row locks for scaling (see Phase 1 plan)

---

## 10. Security Monitoring

Monitor for:
- **Fraud:** Same card declined 10+ times in 1 hour (might be testing)
- **Abuse:** Single user 100+ charge attempts in 1 hour (might be automation)
- **Compromise:** Card details in logs (should never happen; immediate alert)
- **Replay:** Same idempotency key used by different user (impossible, but log it)

Example rule:
```python
# Alert on fraud-like pattern
if charge_failures_per_card > 10 and time_window == "1h":
    log.error("potential fraud pattern", extra={
        "card": card_last4,
        "failures": charge_failures_per_card
    })
    alert("Investigate potential fraud")
```

---

## Reference

- [Stripe Webhook Events](https://stripe.com/docs/api/events/types)
- [Monitoring Best Practices](https://stripe.com/docs/guides/webhooks#monitor)
- [SLA Targets](https://stripe.com/docs/about/sla)
