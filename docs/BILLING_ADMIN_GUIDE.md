# Samvara Billing: Admin Reference Guide

This guide covers admin operations for managing charges, issuing refunds, and troubleshooting billing issues.

---

## Overview

Admin endpoints provide powerful tools for:
- **Viewing all charges** across all users
- **Inspecting charge details** (amounts, status, payment intent)
- **Issuing refunds** (full or partial)
- **Auditing billing history** for support and compliance

All admin endpoints require authentication via:
- API token (recommended for scripts/automation)
- Owner session (built-in for development)

---

## Authentication

### Option 1: API Token (Recommended for Automation)

Set the `ADMIN_API_TOKEN` environment variable:

```bash
export ADMIN_API_TOKEN="your-secret-token"
```

Include in all admin requests:

```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  http://localhost:8000/v1/admin/charges
```

### Option 2: Owner Session (Development)

If you're logged in as the account owner:

```bash
# Session cookie is sent automatically by browser
curl -b "session_id=..." \
  http://localhost:8000/v1/admin/charges
```

### Generating Tokens

For production, use a secure random token:

```python
import secrets
token = secrets.token_urlsafe(32)
print(token)  # Store this in your .env
```

---

## Endpoints

### 1. List All Charges

```
GET /v1/admin/charges?limit=100&offset=0
```

**Parameters:**
- `limit` (int, optional): Number of results per page (default: 100, max: 1000)
- `offset` (int, optional): Number of results to skip (default: 0)

**Example:**

```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "http://localhost:8000/v1/admin/charges?limit=50&offset=0"
```

**Response:**

```json
{
  "charges": [
    {
      "id": "charge-abc123",
      "user_id": "user-xyz789",
      "provider": "samvara",
      "provider_charge_id": "pi_1234567890",
      "amount": 2000,
      "currency": "usd",
      "status": "succeeded",
      "description": "Missed goal: Loss aversion",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:35:00Z"
    },
    {
      "id": "charge-def456",
      "user_id": "user-abc111",
      "provider": "samvara",
      "provider_charge_id": "pi_0987654321",
      "amount": 5000,
      "currency": "usd",
      "status": "requires_action",
      "description": "Missed goal: Akrasia",
      "created_at": "2024-01-15T09:15:00Z",
      "updated_at": "2024-01-15T09:15:00Z"
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1247
}
```

**Charge Status Values:**
- `pending`: Payment processing (waiting for customer auth)
- `requires_action`: Customer must authenticate (3D Secure)
- `succeeded`: Charge completed successfully
- `failed`: Charge failed (declined, network error, etc.)
- `refunded`: Charge refunded in full
- `partially_refunded`: Charge refunded in part

---

### 2. Get Single Charge

```
GET /v1/admin/charges/{charge_id}
```

**Parameters:**
- `charge_id` (path): Database charge ID (e.g., `charge-abc123`)

**Example:**

```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  http://localhost:8000/v1/admin/charges/charge-abc123
```

**Response:**

```json
{
  "id": "charge-abc123",
  "user_id": "user-xyz789",
  "user_email": "alice@example.com",
  "provider": "samvara",
  "provider_charge_id": "pi_1234567890",
  "amount": 2000,
  "currency": "usd",
  "status": "succeeded",
  "description": "Missed goal: Loss aversion",
  "payment_method": {
    "brand": "visa",
    "last4": "4242",
    "exp_month": 12,
    "exp_year": 2026
  },
  "refund_amount": 0,
  "refund_reason": null,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:35:00Z",
  "metadata": {
    "goal_id": "goal-123",
    "goal_name": "Write daily",
    "derailment_date": "2024-01-15"
  }
}
```

**Response Codes:**
- `200 OK`: Charge found
- `403 Forbidden`: Not authenticated as admin
- `404 Not Found`: Charge doesn't exist

---

### 3. Issue Refund

```
DELETE /v1/admin/charges/{charge_id}/refund?amount={amount}
```

**Parameters:**
- `charge_id` (path): Database charge ID
- `amount` (query, optional): Amount to refund in dollars (e.g., `5.00`). If omitted, refunds full amount.

**Examples:**

Full refund:
```bash
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  http://localhost:8000/v1/admin/charges/charge-abc123/refund
```

Partial refund ($5 of $20 charge):
```bash
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "http://localhost:8000/v1/admin/charges/charge-abc123/refund?amount=5.00"
```

**Response:**

```json
{
  "status": "succeeded",
  "charge_id": "charge-abc123",
  "provider_refund_id": "re_1234567890",
  "amount_refunded": 2000,
  "total_refunded": 2000,
  "charge_status": "refunded",
  "message": "Charge refunded successfully"
}
```

**Response Codes:**
- `200 OK`: Refund succeeded
- `400 Bad Request`: Invalid amount or charge status
- `403 Forbidden`: Not authenticated as admin
- `404 Not Found`: Charge doesn't exist
- `409 Conflict`: Charge can't be refunded (e.g., already refunded)
- `500 Server Error`: Stripe API error (check logs)

**Refund Validation:**
- Can only refund succeeded charges (not pending/failed)
- Amount must be ≤ charge amount (no negative refunds)
- Can refund same charge multiple times (partial refunds)
- Cannot exceed total charge amount across all refunds
- Amount must be ≥ $0.01

---

## Use Cases

### Case 1: Customer Requests Refund (Support Ticket)

1. Find the charge:
```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "http://localhost:8000/v1/admin/charges?limit=100" | \
  jq '.charges[] | select(.user_email == "customer@example.com")'
```

2. Review charge details:
```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  http://localhost:8000/v1/admin/charges/charge-abc123
```

3. Issue refund:
```bash
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  http://localhost:8000/v1/admin/charges/charge-abc123/refund
```

4. Confirm with customer:
```
Hi! I've processed a refund of $20.00 to your card ending in 4242. 
It should appear within 5-10 business days.
```

### Case 2: Partial Refund for Partial Service

Customer was charged for a month but left after 2 weeks:

```bash
# Get charge
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  http://localhost:8000/v1/admin/charges/charge-xyz789

# Issue 50% refund (e.g., charged $20, refund $10)
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "http://localhost:8000/v1/admin/charges/charge-xyz789/refund?amount=10.00"
```

### Case 3: Audit Billing for Compliance

Export all charges for a date range:

```bash
# Get all charges
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "http://localhost:8000/v1/admin/charges?limit=1000" | \
  jq '.charges[] | select(.created_at > "2024-01-01T00:00:00Z" and .created_at < "2024-02-01T00:00:00Z")' > charges_january.json

# Summary
cat charges_january.json | jq '[.amount] | add'  # Total charged
cat charges_january.json | jq '[select(.status == "succeeded") | .amount] | add'  # Successful charges
```

### Case 4: Monitor Pending Charges

Charges stuck in `requires_action` (awaiting 3D Secure) for >24 hours:

```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "http://localhost:8000/v1/admin/charges?limit=100" | \
  jq '.charges[] | select(.status == "requires_action" and (.created_at < now - 86400))'
```

Recovery: Manually replay webhook or contact customer to complete authentication.

---

## Scripting Examples

### Python Script: Bulk Refund

```python
import requests
import os

API_TOKEN = os.getenv("ADMIN_API_TOKEN")
BASE_URL = "http://localhost:8000"

def refund_charge(charge_id: str, amount: float = None) -> dict:
    """Issue refund for charge."""
    url = f"{BASE_URL}/v1/admin/charges/{charge_id}/refund"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    params = {}
    if amount:
        params["amount"] = amount
    
    response = requests.delete(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Example: Refund multiple charges
charge_ids = ["charge-abc123", "charge-def456"]
for cid in charge_ids:
    result = refund_charge(cid)
    print(f"{cid}: {result['status']}")
```

### Bash Script: Daily Report

```bash
#!/bin/bash

TOKEN=$ADMIN_API_TOKEN
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
YESTERDAY=$(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ)

# Get charges from last 24 hours
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v1/admin/charges?limit=1000" | jq ".charges[] | select(.created_at > \"$YESTERDAY\")" > /tmp/charges.json

# Generate report
echo "=== Daily Billing Report ==="
echo "Date: $TIMESTAMP"
echo ""
echo "Total Charges: $(jq 'length' /tmp/charges.json)"
echo "Total Amount: \$$(jq '[.amount] | add / 100' /tmp/charges.json)"
echo ""
echo "By Status:"
jq -r '.status' /tmp/charges.json | sort | uniq -c | while read count status; do
  echo "  $status: $count"
done
```

### Node.js Script: Charge Lookup

```javascript
const fetch = require('node-fetch');

async function getCharge(chargeId) {
  const response = await fetch(
    `http://localhost:8000/v1/admin/charges/${chargeId}`,
    {
      headers: {
        'Authorization': `Bearer ${process.env.ADMIN_API_TOKEN}`
      }
    }
  );
  
  if (!response.ok) {
    throw new Error(`${response.status}: ${response.statusText}`);
  }
  
  return response.json();
}

// Usage
getCharge('charge-abc123')
  .then(charge => console.log(charge))
  .catch(err => console.error(err.message));
```

---

## Troubleshooting

### "403 Forbidden"

**Cause:** Token missing or incorrect
**Fix:**
1. Check `ADMIN_API_TOKEN` is set: `echo $ADMIN_API_TOKEN`
2. Verify token in `-H "Authorization: Bearer $ADMIN_API_TOKEN"`
3. Try owner session if you're logged in

### "404 Not Found"

**Cause:** Charge ID doesn't exist or user doesn't have access
**Fix:**
1. Verify charge ID format (should be `charge-...`)
2. Check charge belongs to your account (not another Samvara instance)
3. List all charges to find the right ID: `GET /v1/admin/charges`

### "409 Conflict - Charge already refunded"

**Cause:** Charge already fully refunded
**Fix:**
1. Check charge status: `GET /v1/admin/charges/{charge_id}`
2. Look at `refund_amount` field
3. For partial additional refund, ensure total ≤ original amount

### "400 Bad Request - Invalid amount"

**Cause:** Amount malformed or exceeds charge amount
**Fix:**
1. Use format: `?amount=5.00` (not `5` or `$5`)
2. Verify amount ≤ charge amount
3. Amount must be ≥ $0.01

### Stripe API Errors (500 Server Error)

**Cause:** Stripe API unavailable or auth issue
**Fix:**
1. Check Stripe dashboard status
2. Verify API keys in environment
3. Check server logs for details: `grep "Stripe API" /var/log/samvara.log`
4. Retry after 1-2 minutes

---

## Safety & Audit

### Best Practices

✅ **DO:**
- Use strong API tokens (rotate monthly)
- Log all refunds for audit trail
- Notify customer before issuing refund
- Test in staging before production
- Monitor for unauthorized admin access

❌ **DON'T:**
- Commit API tokens to git
- Use same token across environments
- Refund without customer approval
- Refund more than charged amount
- Ignore failed refund responses

### Audit Trail

All refunds are logged with:
- Admin user/token ID
- Timestamp
- Charge ID
- Amount refunded
- Reason (if provided)

View logs:
```bash
grep "refund" /var/log/samvara.log | tail -20
```

---

## Rate Limits

Admin endpoints are rate-limited to prevent abuse:

- **List charges:** 60 requests/minute
- **Get charge:** 120 requests/minute
- **Issue refund:** 30 requests/minute

Exceeding limits returns `429 Too Many Requests`. Back off exponentially.

---

## FAQ

**Q: Can I undo a refund?**
A: No. Refunds are permanent. To reverse, you'd need to manually charge the customer again (contact Stripe support).

**Q: How long until refund appears?**
A: Usually 5-10 business days (bank-dependent). Immediately shows in charge status as "refunded".

**Q: Can I refund more than charged?**
A: No. Validation prevents refunding > original charge amount.

**Q: What if refund fails?**
A: Server returns 500 error. Check:
  - Stripe API status
  - Charge can be refunded (succeeded status)
  - No duplicate refund request
  - Amount valid

**Q: Are admins logged for compliance?**
A: Yes. All operations logged with admin ID, timestamp, charge ID, and amount.

---

## Related Docs

- [API Reference](BILLING_API.md) — Full endpoint documentation
- [Webhook Reliability](BILLING_WEBHOOK_RELIABILITY.md) — Webhook handling
- [Security Review](BILLING_SECURITY_REVIEW.md) — Admin authorization patterns
- [Deployment Guide](BILLING_DEPLOYMENT.md) — Setup and monitoring
