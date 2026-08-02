# Samvara Billing: Usage Recipes

This guide provides practical code examples for common billing workflows.

---

## Table of Contents

1. [Python Client Library](#python-client-library)
2. [React Native Client](#react-native-client)
3. [Admin Operations](#admin-operations)
4. [Error Handling](#error-handling)
5. [Testing](#testing)

---

## Python Client Library

### Recipe 1: Check User Billing Status

**Goal:** Get current user's billing status (provider, payment method on file, pricing info)

```python
from samvara_billing_client import SamvaraBillingClient

client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    session_id="user-session-token",
)

try:
    status = client.get_billing_status()
    print(f"Provider: {status.provider}")
    print(f"Has payment method: {status.has_payment_method}")
    print(f"Card: {status.card_display}")
except Exception as e:
    print(f"Error: {e}")
```

### Recipe 2: Add Payment Method (Full Flow)

**Goal:** Add a new card for a user (setup intent → Stripe UI → save to profile)

```python
from samvara_billing_client import SamvaraBillingClient, SetupIntent

client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    session_id="user-session-token",
)

# 1. Create setup intent
try:
    intent: SetupIntent = client.create_setup_intent()
    print(f"Setup intent created: {intent.id}")
    
    # 2. Pass clientSecret to mobile app's Stripe Payment Sheet
    client_secret = intent.client_secret
    # Send to frontend: 
    #   await stripe.confirmSetupIntent(clientSecret)
    
    # 3. After Stripe SDK confirms, save the payment method
    setup_intent_id = intent.id
    payment_method = client.save_payment_method(setup_intent_id)
    
    print(f"Card saved: {payment_method.brand} ending in {payment_method.last4}")
    
except Exception as e:
    print(f"Error setting up card: {e}")
```

### Recipe 3: Admin: List All Charges

**Goal:** Retrieve paginated list of all charges for compliance/auditing

```python
from samvara_billing_client import SamvaraBillingClient

admin_client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    api_token="your-admin-api-token",
)

# Get first page
charges = admin_client.admin_list_charges(limit=50, offset=0)
print(f"Total charges: {charges['total']}")

for charge in charges['charges']:
    print(f"{charge['id']}: ${charge['amount']/100:.2f} - {charge['status']}")

# Get next page
next_page = admin_client.admin_list_charges(limit=50, offset=50)
```

### Recipe 4: Admin: Issue Refund

**Goal:** Process a customer refund request (full or partial)

```python
from samvara_billing_client import SamvaraBillingClient, BillingNotFoundError

admin_client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    api_token="your-admin-api-token",
)

charge_id = "charge-abc123"

try:
    # Full refund (no amount specified)
    result = admin_client.admin_refund_charge(charge_id)
    print(f"Refund successful: {result['status']}")
    
    # Partial refund ($10 out of $20)
    # result = admin_client.admin_refund_charge(charge_id, amount=10.00)
    
except BillingNotFoundError:
    print(f"Charge {charge_id} not found")
except Exception as e:
    print(f"Refund failed: {e}")
```

### Recipe 5: Batch Processing

**Goal:** Refund multiple charges in bulk

```python
from samvara_billing_client import SamvaraBillingClient
import csv
from datetime import datetime

admin_client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    api_token="your-admin-api-token",
)

# Load charge IDs from CSV
refund_log = []

with open('refunds.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        charge_id = row['charge_id']
        amount = float(row.get('amount')) if row.get('amount') else None
        
        try:
            result = admin_client.admin_refund_charge(charge_id, amount)
            refund_log.append({
                'charge_id': charge_id,
                'status': 'success',
                'refund_id': result.get('provider_refund_id'),
                'timestamp': datetime.now().isoformat(),
            })
            print(f"✓ {charge_id}")
        except Exception as e:
            refund_log.append({
                'charge_id': charge_id,
                'status': 'failed',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            })
            print(f"✗ {charge_id}: {e}")

# Save results
with open('refunds_result.csv', 'w') as f:
    writer = csv.DictWriter(f, fieldnames=['charge_id', 'status', 'refund_id', 'error', 'timestamp'])
    writer.writeheader()
    writer.writerows(refund_log)

print(f"Processed {len(refund_log)} refunds")
```

### Recipe 6: Error Handling with Retries

**Goal:** Robust API calls with exponential backoff

```python
from samvara_billing_client import SamvaraBillingClient, BillingServerError
import time

client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    api_token="your-token",
)

def robust_get_charge(charge_id: str, max_retries: int = 3):
    """Get charge with retry logic."""
    for attempt in range(max_retries):
        try:
            return client.admin_get_charge(charge_id)
        except BillingServerError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"Attempt {attempt + 1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise

try:
    charge = robust_get_charge("charge-xyz789")
    print(f"Charge: {charge['amount']} ({charge['status']})")
except Exception as e:
    print(f"Failed after retries: {e}")
```

---

## React Native Client

### Recipe 1: Load Billing Status on Screen Mount

**Goal:** Fetch billing status when screen loads, with offline fallback

```typescript
import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, Alert } from 'react-native';
import * as billingClient from '../../services/billingClient';

export default function BillingScreen() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadBillingStatus();
  }, []);

  async function loadBillingStatus() {
    setLoading(true);
    try {
      const data = await billingClient.getBillingStatus();
      setStatus(data);
      setError(null);
    } catch (err) {
      const billingError = err as billingClient.BillingError;
      setError(billingError.userMessage);
      // Status may still be set from cache
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={{ padding: 16 }}>
      {error && <Text style={{ color: 'red' }}>{error}</Text>}
      {status && <Text>Provider: {status.provider}</Text>}
    </View>
  );
}
```

### Recipe 2: Add Payment Method

**Goal:** Guide user through card setup (create intent → Stripe UI → confirm)

```typescript
import { useStripe } from '@stripe/stripe-react-native';
import * as billingClient from '../../services/billingClient';

export function CardSetupFlow() {
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState(null);

  async function addCard() {
    setIsProcessing(true);
    setError(null);

    try {
      // 1. Create setup intent
      const intent = await billingClient.createSetupIntent();
      
      if (!billingClient.isValidSetupIntentId(intent.id)) {
        throw new Error('Invalid setup intent');
      }

      // 2. Initialize Stripe payment sheet
      const { error: initError } = await initPaymentSheet({
        setupIntentClientSecret: intent.clientSecret,
        merchantDisplayName: 'Saṃvara',
      });

      if (initError) {
        throw new Error(`Payment sheet init failed: ${initError.message}`);
      }

      // 3. Present payment sheet to user
      const { error: presentError } = await presentPaymentSheet();
      
      if (presentError && presentError.code !== 'Canceled') {
        throw new Error(`Payment failed: ${presentError.message}`);
      }

      if (presentError?.code === 'Canceled') {
        // User dismissed sheet
        return;
      }

      // 4. Save payment method to server
      await billingClient.savePaymentMethod(intent.id);

      // 5. Reload billing status
      await billingClient.getBillingStatus();

      Alert.alert('Success', 'Card saved successfully');
    } catch (err) {
      const billingError = err as billingClient.BillingError;
      setError(billingError.userMessage);
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <View>
      {error && <Text style={{ color: 'red' }}>{error}</Text>}
      <Button
        title="Add Card"
        onPress={addCard}
        disabled={isProcessing}
      />
    </View>
  );
}
```

### Recipe 3: Handle Billing Errors with User-Friendly Messages

**Goal:** Normalize errors and show appropriate user messages

```typescript
import * as billingClient from '../../services/billingClient';

async function chargeUser(amount: number) {
  try {
    const result = await makeCharge(amount);
    return result;
  } catch (err) {
    const error = err as billingClient.BillingError;

    switch (error.type) {
      case 'network':
        Alert.alert(
          'Connection Error',
          error.userMessage,
          [{ text: 'Retry', onPress: () => chargeUser(amount) }]
        );
        break;

      case 'validation':
        Alert.alert(
          'Invalid Input',
          error.userMessage,
          [{ text: 'OK' }]
        );
        break;

      case 'server':
        Alert.alert(
          'Service Error',
          error.userMessage,
          [{ text: 'Retry', onPress: () => chargeUser(amount) }]
        );
        break;

      case 'user_action':
        Alert.alert(
          'Action Required',
          error.userMessage,
          [{ text: 'Go to Settings', onPress: () => navigateTo('billing') }]
        );
        break;

      default:
        Alert.alert(
          'Error',
          'Something went wrong. Please try again.',
          [{ text: 'OK' }]
        );
    }

    throw error; // Propagate for logging
  }
}
```

### Recipe 4: Offline Mode with Cached Data

**Goal:** Show cached billing status when offline

```typescript
import { useEffect, useState } from 'react';
import { useNetInfo } from '@react-native-community/netinfo';
import * as billingClient from '../../services/billingClient';

export function BillingStatusWithOfflineSupport() {
  const netInfo = useNetInfo();
  const [status, setStatus] = useState(null);
  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    loadBillingStatus();
  }, [netInfo.isConnected]);

  async function loadBillingStatus() {
    try {
      const data = await billingClient.getBillingStatus();
      setStatus(data);
      setIsOffline(false);
    } catch (err) {
      const error = err as billingClient.BillingError;
      
      // If network error AND we have cached data, use cache
      if (error.type === 'network' && status) {
        setIsOffline(true);
        // Keep using `status` from previous successful load
      } else {
        // No cache available or not a network error
        Alert.alert('Error', error.userMessage);
      }
    }
  }

  return (
    <View>
      {isOffline && (
        <Text style={{ color: 'orange' }}>
          ⚠️ Offline - showing cached data
        </Text>
      )}
      {status && (
        <Text>
          Payment method: {status.cardDisplay || 'None on file'}
        </Text>
      )}
    </View>
  );
}
```

---

## Admin Operations

### Recipe 1: Generate Monthly Billing Report

**Goal:** Export all charges from a month for accounting/compliance

```python
from samvara_billing_client import SamvaraBillingClient
from datetime import datetime, timedelta
import csv

admin_client = SamvaraBillingClient(
    base_url="http://localhost:8000",
    api_token="admin-token",
)

def generate_monthly_report(year: int, month: int):
    """Generate CSV report of charges for a month."""
    # Date range
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)
    
    # Fetch all charges (paginate)
    all_charges = []
    offset = 0
    while True:
        result = admin_client.admin_list_charges(limit=100, offset=offset)
        charges = result.get('charges', [])
        
        # Filter to date range
        for charge in charges:
            created = datetime.fromisoformat(charge['created_at'].replace('Z', '+00:00'))
            if start_date <= created < end_date:
                all_charges.append(charge)
        
        # Check if more pages
        if len(charges) < 100:
            break
        offset += 100
    
    # Write CSV
    filename = f"charges_{year}_{month:02d}.csv"
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'charge_id', 'user_id', 'amount', 'status', 'created_at'
        ])
        writer.writeheader()
        
        total_amount = 0
        for charge in all_charges:
            writer.writerow({
                'charge_id': charge['id'],
                'user_id': charge['user_id'],
                'amount': f"${charge['amount']/100:.2f}",
                'status': charge['status'],
                'created_at': charge['created_at'],
            })
            if charge['status'] == 'succeeded':
                total_amount += charge['amount']
    
    print(f"Generated {filename}")
    print(f"Total charges: {len(all_charges)}")
    print(f"Total amount: ${total_amount/100:.2f}")
    
    return filename

# Usage
report = generate_monthly_report(2024, 1)
```

---

## Error Handling

### Recipe 1: Comprehensive Error Handler

**Goal:** Log errors with context for debugging

```python
from samvara_billing_client import (
    BillingClient,
    BillingAuthError,
    BillingNotFoundError,
    BillingValidationError,
    BillingServerError,
)
import logging

logger = logging.getLogger(__name__)

async def safe_charge_refund(charge_id: str, amount: float = None):
    """Refund with comprehensive error handling and logging."""
    try:
        client = BillingClient(api_token="token")
        result = await client.admin_refund_charge(charge_id, amount)
        logger.info(f"Refund successful", extra={
            'charge_id': charge_id,
            'refund_id': result.get('provider_refund_id'),
        })
        return result

    except BillingAuthError as e:
        logger.error(f"Auth error: invalid/expired token", extra={
            'charge_id': charge_id,
            'error': str(e),
        })
        raise

    except BillingNotFoundError as e:
        logger.warning(f"Charge not found", extra={
            'charge_id': charge_id,
        })
        raise

    except BillingValidationError as e:
        logger.error(f"Validation error: invalid amount or charge status", extra={
            'charge_id': charge_id,
            'amount': amount,
            'error': str(e),
        })
        raise

    except BillingServerError as e:
        logger.error(f"Server error during refund", extra={
            'charge_id': charge_id,
            'error': str(e),
        })
        # Could implement retry logic here
        raise

    except Exception as e:
        logger.exception(f"Unexpected error", extra={
            'charge_id': charge_id,
        })
        raise
```

---

## Testing

### Recipe 1: Mock Billing Client for Tests

**Goal:** Unit test code that uses billing client without making real API calls

```python
import pytest
from unittest.mock import patch, MagicMock
from samvara_billing_client import SamvaraBillingClient

@pytest.fixture
def mock_billing_client():
    """Mock billing client for testing."""
    with patch('samvara_billing_client.SamvaraBillingClient') as mock:
        yield mock

def test_add_card_success(mock_billing_client):
    """Test successful card addition."""
    # Setup mock
    mock_instance = MagicMock()
    mock_billing_client.return_value = mock_instance
    mock_instance.createSetupIntent.return_value = {
        'id': 'seti_test_123',
        'clientSecret': 'secret_abc',
    }
    mock_instance.savePaymentMethod.return_value = {
        'id': 'pm_test_456',
        'brand': 'visa',
        'last4': '4242',
    }

    # Test code
    client = SamvaraBillingClient(base_url="http://localhost:8000")
    intent = client.createSetupIntent()
    assert intent['id'] == 'seti_test_123'

    payment_method = client.savePaymentMethod(intent['id'])
    assert payment_method['brand'] == 'visa'
```

---

## Related Resources

- [Python Client: API Reference](./backend/samvara_billing_client.py)
- [TypeScript Client: billingClient.ts](./client/src/services/billingClient.ts)
- [Admin Guide](./BILLING_ADMIN_GUIDE.md)
- [API Reference](./BILLING_API.md)
- [Error Handling Guide](./BILLING_ERROR_HANDLING.md)
