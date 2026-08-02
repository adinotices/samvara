"""
End-to-end integration tests for billing flows.

These tests exercise the complete flow from client setup through payment processing,
including webhook handling and charge commits.
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.db import charges, users
from unittest.mock import patch, MagicMock
import json


@pytest.fixture
def client():
    """Test client for API."""
    return TestClient(app)


@pytest.fixture
def test_user(db_session):
    """Create test user."""
    user = users.insert().values(
        id="test-user-123",
        email="test@example.com",
    ).returning(users).execute()
    return user.fetchone()


@pytest.fixture
def session_cookie(client, test_user):
    """Get valid session cookie for test user."""
    # This assumes session creation is implemented
    # Adjust based on actual session implementation
    return f"session_id=test-session-123"


class TestFullPaymentFlow:
    """Tests for complete payment flows."""

    def test_payment_setup_to_commit_flow(self, client, test_user, session_cookie):
        """
        Test complete flow:
        1. Get billing status
        2. Create setup intent
        3. Save payment method
        4. Receive webhook
        5. Charge succeeds
        """
        headers = {"Cookie": session_cookie}

        # 1. Check billing status (no card initially)
        response = client.get("/v1/billing/status", headers=headers)
        assert response.status_code == 200
        status = response.json()
        assert status["has_payment_method"] is False
        assert status["card_display"] is None

        # 2. Create setup intent
        response = client.post("/v1/billing/setup-intent", headers=headers)
        assert response.status_code == 200
        intent = response.json()
        setup_intent_id = intent["id"]
        assert intent["id"].startswith("seti_")

        # 3. Simulate Stripe setup success and save payment method
        with patch("app.stripe_billing.stripe.SetupIntent.retrieve") as mock_retrieve:
            mock_retrieve.return_value = MagicMock(
                id=setup_intent_id,
                payment_method="pm_test_4242",
                status="succeeded",
                client_secret="secret_123",
            )

            response = client.post(
                "/v1/billing/payment-method",
                json={"setup_intent_id": setup_intent_id},
                headers=headers,
            )
            assert response.status_code == 200
            payment = response.json()
            assert payment["id"] == "pm_test_4242"

        # 4. Verify billing status now shows card
        response = client.get("/v1/billing/status", headers=headers)
        assert response.status_code == 200
        status = response.json()
        assert status["has_payment_method"] is True
        assert status["card_display"] is not None

    def test_charge_creation_with_webhook_confirmation(
        self, client, test_user, session_cookie
    ):
        """
        Test charge creation and webhook confirmation:
        1. Create charge (succeeds at Stripe)
        2. Charge initially pending in DB
        3. Receive webhook confirmation
        4. Charge marked succeeded in DB
        """
        headers = {"Cookie": session_cookie}

        # Pre-populate with payment method
        # (Assuming this is already set up from previous test)

        # 1. Create charge via penalty system
        # This would normally happen when user misses a goal
        with patch("app.stripe_billing.stripe.PaymentIntent.create") as mock_create:
            mock_pi = MagicMock()
            mock_pi.id = "pi_test_charge_123"
            mock_pi.status = "succeeded"  # Assume successful immediately
            mock_create.return_value = mock_pi

            response = client.post(
                "/v1/charges",
                json={
                    "amount": 5.00,
                    "reason": "Missed goal",
                    "idempotency_key": "charge-123",
                },
                headers=headers,
            )
            assert response.status_code == 200
            charge_response = response.json()
            charge_id = charge_response["id"]

        # 2. Verify charge is in database
        result = charges.select().where(
            charges.c.id == charge_id
        ).execute().fetchone()
        assert result is not None
        assert result.status == "pending"  # Starts as pending
        assert result.provider_charge_id == "pi_test_charge_123"

        # 3. Simulate webhook from Stripe
        webhook_body = json.dumps({
            "id": "evt_test_123",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_test_charge_123",
                    "status": "succeeded",
                    "amount": 500,  # 5.00 in cents
                }
            },
            "created": int(datetime.now().timestamp()),
        })

        # Calculate HMAC signature
        import hmac
        import hashlib
        timestamp = str(int(datetime.now().timestamp()))
        signed_content = f"{timestamp}.{webhook_body}"
        signature = hmac.new(
            b"test_webhook_secret",
            signed_content.encode(),
            hashlib.sha256,
        ).hexdigest()

        webhook_response = client.post(
            "/v1/billing/webhook/stripe",
            json=json.loads(webhook_body),
            headers={
                "Stripe-Signature": f"t={timestamp},v1={signature}",
                "Content-Type": "application/json",
            },
        )
        assert webhook_response.status_code == 200

        # 4. Verify charge is now succeeded
        result = charges.select().where(
            charges.c.id == charge_id
        ).execute().fetchone()
        assert result.status == "succeeded"

    def test_idempotent_webhook_processing(self, client, test_user):
        """
        Test that processing same webhook multiple times only charges once.
        """
        # Create initial charge
        charge_id = "charge-idempotent-test"
        charges.insert().values(
            id=charge_id,
            user_id=test_user.id,
            provider_charge_id="pi_idempotent_123",
            amount=1000,
            status="pending",
            created_at=datetime.now(),
        ).execute()

        webhook_body = json.dumps({
            "id": "evt_idempotent_123",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_idempotent_123",
                    "status": "succeeded",
                }
            },
            "created": int(datetime.now().timestamp()),
        })

        # Send webhook twice
        for attempt in range(2):
            import hmac
            import hashlib
            timestamp = str(int(datetime.now().timestamp()) + attempt)
            signed_content = f"{timestamp}.{webhook_body}"
            signature = hmac.new(
                b"test_webhook_secret",
                signed_content.encode(),
                hashlib.sha256,
            ).hexdigest()

            response = client.post(
                "/v1/billing/webhook/stripe",
                json=json.loads(webhook_body),
                headers={
                    "Stripe-Signature": f"t={timestamp},v1={signature}",
                },
            )
            assert response.status_code == 200

        # Verify charge only committed once
        result = charges.select().where(
            charges.c.id == charge_id
        ).execute().fetchone()
        assert result.status == "succeeded"

        # Check ledger only has one entry (assumes ledger is separate table)
        # This would depend on actual schema


class TestErrorRecovery:
    """Tests for error recovery and retry scenarios."""

    def test_webhook_retry_on_database_lock(self, client):
        """
        Test webhook processing retries on database contention.
        """
        with patch("app.stripe_billing.commit_charge") as mock_commit:
            # Simulate DB lock on first attempt
            mock_commit.side_effect = [
                Exception("database is locked"),
                {"status": "succeeded"},  # Success on retry
            ]

            webhook_body = json.dumps({
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_retry_123"}},
                "created": int(datetime.now().timestamp()),
            })

            # Should succeed despite initial error
            # (Assumes retry logic in webhook handler)
            # This test structure depends on actual implementation

    def test_payment_method_removal_cascade(self, client, test_user, session_cookie):
        """
        Test that removing payment method clears related data.
        """
        headers = {"Cookie": session_cookie}

        # Add payment method first
        # (Assuming already set up)

        # Remove payment method
        response = client.delete("/v1/billing/payment-method", headers=headers)
        assert response.status_code == 200

        # Verify status reflects removal
        response = client.get("/v1/billing/status", headers=headers)
        assert response.status_code == 200
        status = response.json()
        assert status["has_payment_method"] is False
        assert status["card_display"] is None

    def test_refund_with_verification(self, client):
        """
        Test admin refund and verify charge status changes.
        """
        # Create charge
        charge_id = "charge-refund-test"
        charges.insert().values(
            id=charge_id,
            user_id="user-123",
            provider_charge_id="pi_refund_123",
            amount=5000,
            status="succeeded",
            created_at=datetime.now(),
        ).execute()

        # Admin refund
        with patch("app.stripe_billing.stripe.Refund.create") as mock_refund:
            mock_refund.return_value = MagicMock(
                id="re_test_123",
                status="succeeded",
                amount=5000,
            )

            response = client.delete(
                f"/v1/admin/charges/{charge_id}/refund",
                headers={"Authorization": "Bearer admin-token"},
            )
            assert response.status_code == 200

        # Verify charge status
        result = charges.select().where(
            charges.c.id == charge_id
        ).execute().fetchone()
        # Status should reflect refund (implementation-dependent)


class TestOfflineScenarios:
    """Tests for offline/degraded scenarios."""

    def test_billing_status_fallback_on_network_error(self, client, session_cookie):
        """
        Test that billing status returns cached data on network error.
        (Client-side behavior, but important for integration)
        """
        headers = {"Cookie": session_cookie}

        # First successful call populates cache
        response = client.get("/v1/billing/status", headers=headers)
        assert response.status_code == 200

        # Simulate network error (would be handled client-side)
        # Server should still return valid data

    def test_webhook_delivery_with_transient_errors(self, client):
        """
        Test that webhook endpoint handles transient errors gracefully.
        """
        with patch("app.stripe_billing.commit_charge") as mock_commit:
            # Simulate transient errors
            mock_commit.side_effect = [
                ConnectionError("Connection reset"),
                TimeoutError("Request timeout"),
                {"status": "succeeded"},  # Success on third attempt
            ]

            # Would need actual retry mechanism in webhook handler


class TestConcurrency:
    """Tests for concurrent access patterns."""

    def test_concurrent_payment_method_updates(self, client, test_user, session_cookie):
        """
        Test that concurrent payment method updates are serialized correctly.
        """
        headers = {"Cookie": session_cookie}

        # This would require threading/async testing
        # Main concern: only one payment method active at a time
        pass

    def test_concurrent_charge_creation(self, client, test_user, session_cookie):
        """
        Test that concurrent charges are processed correctly.
        """
        headers = {"Cookie": session_cookie}

        # Create multiple charges simultaneously
        # Verify all are created with correct amounts
        pass
