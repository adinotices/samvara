"""
Samvara Billing API Client

Python client library for interacting with Samvara billing endpoints.
Provides a clean, typed interface with automatic retry logic and error handling.

Usage:
    client = SamvaraBillingClient(base_url="http://localhost:8000", api_token="...")
    status = client.get_billing_status(user_id="user-123")
    intent = client.create_setup_intent(user_id="user-123")
"""

import httpx
import time
from typing import Any, Optional, Dict
from dataclasses import dataclass
from enum import Enum


class BillingProvider(str, Enum):
    """Billing provider type."""
    SAMVARA = "samvara"
    BEEMINDER = "beeminder"


@dataclass
class BillingStatus:
    """User's billing status."""
    provider: BillingProvider
    has_payment_method: bool
    card_display: Optional[str]
    can_use_beeminder: bool
    publishable_key: str


@dataclass
class SetupIntent:
    """Stripe setup intent for adding payment methods."""
    id: str
    client_secret: str
    status: str


@dataclass
class PaymentMethod:
    """Payment method details."""
    id: str
    brand: Optional[str]
    last4: Optional[str]
    exp_month: Optional[int]
    exp_year: Optional[int]


class BillingClientError(Exception):
    """Base exception for billing client errors."""
    pass


class BillingValidationError(BillingClientError):
    """Raised when input validation fails."""
    pass


class BillingAuthError(BillingClientError):
    """Raised when authentication fails (401/403)."""
    pass


class BillingNotFoundError(BillingClientError):
    """Raised when requested resource not found (404)."""
    pass


class BillingServerError(BillingClientError):
    """Raised when server returns 5xx error."""
    pass


class SamvaraBillingClient:
    """
    Client for Samvara billing API.

    Args:
        base_url: Base URL of Samvara API (e.g., http://localhost:8000)
        api_token: Optional API token for admin operations
        session_id: Optional session ID for user operations
        timeout: Request timeout in seconds (default: 30)
        max_retries: Maximum retry attempts for transient errors (default: 3)
    """

    def __init__(
        self,
        base_url: str,
        api_token: Optional[str] = None,
        session_id: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.session_id = session_id
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=timeout)

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with auth."""
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        if self.session_id:
            headers["Cookie"] = f"session_id={self.session_id}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic."""
        url = f"{self.base_url}{path}"
        headers = self._get_headers()

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(
                    method, url, json=json, params=params, headers=headers
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                # Handle auth errors (don't retry)
                if status in (401, 403):
                    raise BillingAuthError(f"Authentication failed: {status}")

                # Handle not found (don't retry)
                if status == 404:
                    raise BillingNotFoundError(f"Resource not found: {path}")

                # Handle validation errors (don't retry)
                if status == 400:
                    try:
                        error = e.response.json()
                        raise BillingValidationError(
                            error.get("detail", "Validation error")
                        )
                    except ValueError:
                        raise BillingValidationError("Validation error")

                # Handle server errors (retry)
                if status >= 500:
                    if attempt < self.max_retries:
                        wait_time = (2 ** attempt)  # Exponential backoff
                        time.sleep(wait_time)
                        continue
                    raise BillingServerError(f"Server error: {status}")

                # Other client errors
                raise BillingClientError(f"HTTP {status}")

            except httpx.RequestError as e:
                # Network errors (retry)
                if attempt < self.max_retries:
                    wait_time = (2 ** attempt)
                    time.sleep(wait_time)
                    continue
                raise BillingClientError(f"Network error: {e}")

        raise BillingClientError("Max retries exceeded")

    # User endpoints (require session_id)

    def get_billing_status(self) -> BillingStatus:
        """
        Get current user's billing status.

        Returns:
            BillingStatus with provider, payment method, and pricing info

        Raises:
            BillingAuthError: If not authenticated
            BillingServerError: If server error
        """
        data = self._request("GET", "/v1/billing/status")
        return BillingStatus(
            provider=BillingProvider(data["provider"]),
            has_payment_method=data["has_payment_method"],
            card_display=data.get("card_display"),
            can_use_beeminder=data["can_use_beeminder"],
            publishable_key=data["publishable_key"],
        )

    def create_setup_intent(self) -> SetupIntent:
        """
        Create Stripe setup intent for adding/updating payment method.

        Returns:
            SetupIntent with client secret for Stripe Payment Sheet

        Raises:
            BillingAuthError: If not authenticated
            BillingServerError: If server error
        """
        data = self._request("POST", "/v1/billing/setup-intent")
        return SetupIntent(
            id=data["id"],
            client_secret=data["client_secret"],
            status=data.get("status", "requires_payment_method"),
        )

    def save_payment_method(self, setup_intent_id: str) -> PaymentMethod:
        """
        Save payment method after Stripe payment sheet completes.

        Args:
            setup_intent_id: Setup intent ID returned from Stripe Payment Sheet

        Returns:
            PaymentMethod that was saved

        Raises:
            BillingValidationError: If setup intent ID invalid
            BillingAuthError: If not authenticated
            BillingServerError: If server error
        """
        data = self._request(
            "POST",
            "/v1/billing/payment-method",
            json={"setup_intent_id": setup_intent_id},
        )
        return PaymentMethod(
            id=data["id"],
            brand=data.get("brand"),
            last4=data.get("last4"),
            exp_month=data.get("exp_month"),
            exp_year=data.get("exp_year"),
        )

    def remove_payment_method(self) -> Dict[str, str]:
        """
        Remove saved payment method.

        Returns:
            Response with status confirmation

        Raises:
            BillingAuthError: If not authenticated
            BillingServerError: If server error
        """
        return self._request("DELETE", "/v1/billing/payment-method")

    # Admin endpoints (require api_token)

    def admin_list_charges(
        self, limit: int = 100, offset: int = 0
    ) -> Dict[str, Any]:
        """
        List all charges (admin only).

        Args:
            limit: Number of charges to return (default: 100)
            offset: Number of charges to skip (default: 0)

        Returns:
            Dict with charges list and pagination info

        Raises:
            BillingAuthError: If not admin authenticated
        """
        return self._request(
            "GET",
            "/v1/admin/charges",
            params={"limit": limit, "offset": offset},
        )

    def admin_get_charge(self, charge_id: str) -> Dict[str, Any]:
        """
        Get specific charge details (admin only).

        Args:
            charge_id: Database charge ID

        Returns:
            Charge details including status, amounts, user info

        Raises:
            BillingAuthError: If not admin authenticated
            BillingNotFoundError: If charge doesn't exist
        """
        return self._request("GET", f"/v1/admin/charges/{charge_id}")

    def admin_refund_charge(
        self, charge_id: str, amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Issue refund for charge (admin only).

        Args:
            charge_id: Database charge ID
            amount: Optional amount to refund. If None, refunds full amount.

        Returns:
            Refund response with status and transaction ID

        Raises:
            BillingAuthError: If not admin authenticated
            BillingNotFoundError: If charge doesn't exist
            BillingValidationError: If charge status invalid or amount > charge amount
        """
        params = {}
        if amount is not None:
            params["amount"] = amount
        return self._request("DELETE", f"/v1/admin/charges/{charge_id}/refund", params=params)

    def close(self):
        """Close HTTP client connection."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
