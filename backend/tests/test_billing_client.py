"""Tests for SamvaraBillingClient."""

import pytest
from unittest.mock import patch, MagicMock
import httpx
from samvara_billing_client import (
    SamvaraBillingClient,
    BillingStatus,
    SetupIntent,
    PaymentMethod,
    BillingAuthError,
    BillingNotFoundError,
    BillingValidationError,
    BillingServerError,
    BillingProvider,
)


@pytest.fixture
def client():
    """Create test client."""
    return SamvaraBillingClient(
        base_url="http://localhost:8000",
        session_id="test-session-123",
    )


@pytest.fixture
def admin_client():
    """Create admin test client."""
    return SamvaraBillingClient(
        base_url="http://localhost:8000",
        api_token="test-admin-token",
    )


class TestBillingStatus:
    """Tests for get_billing_status."""

    def test_get_billing_status_success(self, client):
        """Should parse billing status response."""
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {
                "provider": "samvara",
                "has_payment_method": True,
                "card_display": "Visa •••• 4242",
                "can_use_beeminder": False,
                "publishable_key": "pk_test_123",
            }

            status = client.get_billing_status()

            assert isinstance(status, BillingStatus)
            assert status.provider == BillingProvider.SAMVARA
            assert status.has_payment_method is True
            assert status.card_display == "Visa •••• 4242"
            assert status.can_use_beeminder is False
            mock_request.assert_called_once_with("GET", "/v1/billing/status")

    def test_get_billing_status_no_card(self, client):
        """Should handle user without payment method."""
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {
                "provider": "beeminder",
                "has_payment_method": False,
                "card_display": None,
                "can_use_beeminder": True,
                "publishable_key": "pk_test_123",
            }

            status = client.get_billing_status()

            assert status.provider == BillingProvider.BEEMINDER
            assert status.has_payment_method is False
            assert status.card_display is None


class TestSetupIntent:
    """Tests for create_setup_intent."""

    def test_create_setup_intent_success(self, client):
        """Should create setup intent and return details."""
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {
                "id": "seti_test_123",
                "client_secret": "seti_test_123_secret_abc",
                "status": "requires_payment_method",
            }

            intent = client.create_setup_intent()

            assert isinstance(intent, SetupIntent)
            assert intent.id == "seti_test_123"
            assert intent.client_secret == "seti_test_123_secret_abc"
            mock_request.assert_called_once_with("POST", "/v1/billing/setup-intent")

    def test_create_setup_intent_server_error(self, client):
        """Should raise on server error."""
        with patch.object(client, "_request") as mock_request:
            mock_request.side_effect = BillingServerError("Server error")

            with pytest.raises(BillingServerError):
                client.create_setup_intent()


class TestPaymentMethod:
    """Tests for payment method operations."""

    def test_save_payment_method_success(self, client):
        """Should save payment method and return details."""
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {
                "id": "pm_test_123",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 12,
                "exp_year": 2026,
            }

            method = client.save_payment_method("seti_test_123")

            assert isinstance(method, PaymentMethod)
            assert method.id == "pm_test_123"
            assert method.brand == "visa"
            assert method.last4 == "4242"
            mock_request.assert_called_once_with(
                "POST",
                "/v1/billing/payment-method",
                json={"setup_intent_id": "seti_test_123"},
            )

    def test_save_payment_method_invalid_setup_intent(self, client):
        """Should raise on invalid setup intent."""
        with patch.object(client, "_request") as mock_request:
            mock_request.side_effect = BillingValidationError("Invalid setup intent")

            with pytest.raises(BillingValidationError):
                client.save_payment_method("invalid")

    def test_remove_payment_method_success(self, client):
        """Should remove payment method."""
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {"status": "deleted"}

            result = client.remove_payment_method()

            assert result["status"] == "deleted"
            mock_request.assert_called_once_with("DELETE", "/v1/billing/payment-method")


class TestAdminEndpoints:
    """Tests for admin endpoints."""

    def test_admin_list_charges_success(self, admin_client):
        """Should list charges with pagination."""
        with patch.object(admin_client, "_request") as mock_request:
            mock_request.return_value = {
                "charges": [
                    {
                        "id": "charge-1",
                        "provider_charge_id": "pi_test_123",
                        "status": "succeeded",
                        "amount": 1000,
                    },
                    {
                        "id": "charge-2",
                        "provider_charge_id": "pi_test_456",
                        "status": "pending",
                        "amount": 2000,
                    },
                ],
                "limit": 100,
                "offset": 0,
                "total": 2,
            }

            result = admin_client.admin_list_charges(limit=100)

            assert len(result["charges"]) == 2
            assert result["total"] == 2
            mock_request.assert_called_once_with(
                "GET",
                "/v1/admin/charges",
                params={"limit": 100, "offset": 0},
            )

    def test_admin_list_charges_pagination(self, admin_client):
        """Should support pagination parameters."""
        with patch.object(admin_client, "_request") as mock_request:
            mock_request.return_value = {"charges": [], "limit": 10, "offset": 20}

            admin_client.admin_list_charges(limit=10, offset=20)

            mock_request.assert_called_once_with(
                "GET",
                "/v1/admin/charges",
                params={"limit": 10, "offset": 20},
            )

    def test_admin_get_charge_success(self, admin_client):
        """Should get charge details."""
        with patch.object(admin_client, "_request") as mock_request:
            mock_request.return_value = {
                "id": "charge-1",
                "provider_charge_id": "pi_test_123",
                "status": "succeeded",
                "amount": 1000,
                "user_id": "user-123",
            }

            result = admin_client.admin_get_charge("charge-1")

            assert result["id"] == "charge-1"
            assert result["status"] == "succeeded"
            mock_request.assert_called_once_with("GET", "/v1/admin/charges/charge-1")

    def test_admin_get_charge_not_found(self, admin_client):
        """Should raise on nonexistent charge."""
        with patch.object(admin_client, "_request") as mock_request:
            mock_request.side_effect = BillingNotFoundError("Not found")

            with pytest.raises(BillingNotFoundError):
                admin_client.admin_get_charge("nonexistent")

    def test_admin_refund_charge_full(self, admin_client):
        """Should issue full refund."""
        with patch.object(admin_client, "_request") as mock_request:
            mock_request.return_value = {
                "status": "succeeded",
                "amount": 1000,
                "charge_id": "charge-1",
            }

            result = admin_client.admin_refund_charge("charge-1")

            assert result["status"] == "succeeded"
            mock_request.assert_called_once_with(
                "DELETE",
                "/v1/admin/charges/charge-1}/refund",
                params={},
            )

    def test_admin_refund_charge_partial(self, admin_client):
        """Should issue partial refund with amount."""
        with patch.object(admin_client, "_request") as mock_request:
            mock_request.return_value = {
                "status": "succeeded",
                "amount": 500,
                "charge_id": "charge-1",
            }

            result = admin_client.admin_refund_charge("charge-1", amount=500)

            assert result["amount"] == 500
            mock_request.assert_called_once_with(
                "DELETE",
                "/v1/admin/charges/charge-1}/refund",
                params={"amount": 500},
            )


class TestErrorHandling:
    """Tests for error handling and retry logic."""

    def test_auth_error_no_retry(self, client):
        """Should not retry on 401/403."""
        with patch.object(client._client, "request") as mock_request:
            response = MagicMock()
            response.status_code = 401
            mock_request.side_effect = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=response)

            with pytest.raises(BillingAuthError):
                client._request("GET", "/v1/billing/status")

            assert mock_request.call_count == 1

    def test_not_found_error_no_retry(self, client):
        """Should not retry on 404."""
        with patch.object(client._client, "request") as mock_request:
            response = MagicMock()
            response.status_code = 404
            mock_request.side_effect = httpx.HTTPStatusError("Not found", request=MagicMock(), response=response)

            with pytest.raises(BillingNotFoundError):
                client._request("GET", "/v1/admin/charges/fake")

            assert mock_request.call_count == 1

    def test_server_error_with_retry(self, client):
        """Should retry on 5xx errors."""
        with patch.object(client._client, "request") as mock_request:
            response = MagicMock()
            response.status_code = 503
            mock_request.side_effect = httpx.HTTPStatusError("Service unavailable", request=MagicMock(), response=response)

            with pytest.raises(BillingServerError):
                client._request("GET", "/v1/billing/status")

            # Should attempt multiple times (default 3 retries = 4 total attempts)
            assert mock_request.call_count == 4


class TestContextManager:
    """Tests for context manager usage."""

    def test_context_manager(self):
        """Should support with statement for cleanup."""
        with SamvaraBillingClient("http://localhost:8000") as client:
            assert client is not None
