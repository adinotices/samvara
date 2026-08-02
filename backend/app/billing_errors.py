"""Billing error messages and error handling.

Provides structured, helpful error messages for billing operations
with context and recovery suggestions.
"""
from __future__ import annotations


class BillingError(Exception):
    """Base billing error with message and context."""

    def __init__(self, message: str, context: dict | None = None):
        self.message = message
        self.context = context or {}
        super().__init__(self.message)

    def to_user_message(self) -> str:
        """Return a user-safe message (no internals)."""
        return self.message


class ConfigurationError(BillingError):
    """Misconfigured billing system."""

    @staticmethod
    def missing_stripe_key(key_name: str) -> ConfigurationError:
        """Stripe environment variable not set."""
        return ConfigurationError(
            f"Billing system not configured (missing {key_name}). "
            "Contact support or try again later.",
            context={"key_name": key_name, "environment": "server"}
        )

    @staticmethod
    def missing_customer() -> ConfigurationError:
        """User has no Stripe customer on file."""
        return ConfigurationError(
            "No payment method on file. Add a card in Settings before reporting a lapse/miss.",
            context={"missing": "stripe_customer_id"}
        )

    @staticmethod
    def missing_payment_method() -> ConfigurationError:
        """User has no saved payment method."""
        return ConfigurationError(
            "No payment method on file. Add a card in Settings before reporting a lapse/miss.",
            context={"missing": "payment_method_id"}
        )

    @staticmethod
    def invalid_charge_provider(provider: str) -> ConfigurationError:
        """Unknown charge provider."""
        return ConfigurationError(
            f"Unknown payment provider '{provider}'. Contact support.",
            context={"invalid_provider": provider}
        )


class ChargeValidationError(BillingError):
    """Charge amount validation failed."""

    @staticmethod
    def below_minimum(amount: float, minimum: float) -> ChargeValidationError:
        """Charge amount below minimum."""
        return ChargeValidationError(
            f"Charge ${amount:.2f} is below the ${minimum:.2f} minimum. "
            f"This shouldn't happen; contact support.",
            context={"amount": amount, "minimum": minimum}
        )

    @staticmethod
    def exceeds_maximum(amount: float, maximum: float) -> ChargeValidationError:
        """Charge amount exceeds maximum."""
        return ChargeValidationError(
            f"Charge ${amount:.2f} exceeds the maximum of ${maximum:.2f}. "
            f"Report an error or contact support.",
            context={"amount": amount, "maximum": maximum}
        )

    @staticmethod
    def invalid_amount() -> ChargeValidationError:
        """Charge amount is invalid (zero, negative, etc)."""
        return ChargeValidationError(
            "Invalid charge amount. Contact support.",
            context={"validation": "invalid_amount"}
        )


class StripeAPIError(BillingError):
    """Stripe API call failed."""

    @staticmethod
    def network_error(original_error: Exception) -> StripeAPIError:
        """Network failure calling Stripe."""
        return StripeAPIError(
            "Connection to payment service failed. Check your internet connection and try again.",
            context={"type": "network", "original": str(original_error)}
        )

    @staticmethod
    def api_error(status_code: int, error_message: str) -> StripeAPIError:
        """Stripe API returned an error."""
        # Map common Stripe errors to user messages
        if status_code == 402:
            user_msg = f"Card was declined: {error_message}. Try a different card."
        elif status_code == 429:
            user_msg = "Too many requests. Wait a moment and try again."
        elif status_code == 401:
            user_msg = "Payment service authentication failed. Contact support."
        elif status_code >= 500:
            user_msg = "Payment service is temporarily unavailable. Try again in a moment."
        else:
            user_msg = f"Payment failed: {error_message}. Contact support if it persists."

        return StripeAPIError(
            user_msg,
            context={"http_status": status_code, "stripe_error": error_message}
        )

    @staticmethod
    def timeout() -> StripeAPIError:
        """Stripe API call timed out."""
        return StripeAPIError(
            "Payment service took too long to respond. Check your connection and try again.",
            context={"type": "timeout"}
        )


class ChargeDeclineError(BillingError):
    """Card was declined by Stripe."""

    @staticmethod
    def declined(reason: str = "Your card was declined") -> ChargeDeclineError:
        return ChargeDeclineError(
            f"{reason}. Try a different card or contact your bank.",
            context={"decline_type": "card_declined"}
        )

    @staticmethod
    def insufficient_funds() -> ChargeDeclineError:
        return ChargeDeclineError(
            "Insufficient funds. Check your account balance and try again.",
            context={"decline_type": "insufficient_funds"}
        )

    @staticmethod
    def lost_card() -> ChargeDeclineError:
        return ChargeDeclineError(
            "Card reported as lost or stolen. Update your payment method.",
            context={"decline_type": "lost_card"}
        )

    @staticmethod
    def expired_card() -> ChargeDeclineError:
        return ChargeDeclineError(
            "Card has expired. Update your payment method.",
            context={"decline_type": "expired_card"}
        )

    @staticmethod
    def incorrect_cvc() -> ChargeDeclineError:
        return ChargeDeclineError(
            "Incorrect security code. Check and try again.",
            context={"decline_type": "incorrect_cvc"}
        )


class SetupIntentError(BillingError):
    """SetupIntent operation failed."""

    @staticmethod
    def no_attached_payment_method() -> SetupIntentError:
        return SetupIntentError(
            "Card setup was not confirmed. Please try adding your card again.",
            context={"setup_issue": "no_payment_method"}
        )

    @staticmethod
    def confirmation_failed(reason: str = "unknown") -> SetupIntentError:
        return SetupIntentError(
            f"Card setup failed: {reason}. Try again or use a different card.",
            context={"setup_issue": "confirmation_failed", "reason": reason}
        )


class PaymentMethodError(BillingError):
    """Payment method operation failed."""

    @staticmethod
    def detach_failed() -> PaymentMethodError:
        return PaymentMethodError(
            "Could not remove payment method. It may already be removed. Try adding a new card.",
            context={"operation": "detach"}
        )

    @staticmethod
    def lookup_failed(payment_method_id: str) -> PaymentMethodError:
        return PaymentMethodError(
            "Payment method not found. Try adding your card again.",
            context={"operation": "lookup", "payment_method_id": payment_method_id}
        )


class RefundError(BillingError):
    """Refund operation failed."""

    @staticmethod
    def no_charge_id() -> RefundError:
        return RefundError(
            "No charge to refund. Contact support for assistance.",
            context={"operation": "refund", "reason": "no_charge_id"}
        )

    @staticmethod
    def charge_not_found(charge_id: str) -> RefundError:
        return RefundError(
            "Charge not found. Verify the charge ID and try again.",
            context={"operation": "refund", "charge_id": charge_id}
        )

    @staticmethod
    def already_refunded(charge_id: str) -> RefundError:
        return RefundError(
            "This charge has already been refunded.",
            context={"operation": "refund", "charge_id": charge_id, "status": "already_refunded"}
        )

    @staticmethod
    def invalid_amount(charge_id: str, amount: float) -> RefundError:
        return RefundError(
            f"Invalid refund amount ${amount:.2f}. Contact support.",
            context={"operation": "refund", "charge_id": charge_id, "amount": amount}
        )

    @staticmethod
    def api_error(charge_id: str, error: str) -> RefundError:
        return RefundError(
            f"Refund failed: {error}. Contact support if issue persists.",
            context={"operation": "refund", "charge_id": charge_id, "stripe_error": error}
        )


class WebhookError(BillingError):
    """Webhook processing failed."""

    @staticmethod
    def invalid_signature() -> WebhookError:
        return WebhookError(
            "Webhook signature verification failed. This may indicate tampering.",
            context={"webhook_issue": "invalid_signature"}
        )

    @staticmethod
    def expired_timestamp() -> WebhookError:
        return WebhookError(
            "Webhook timestamp is too old (possible replay attack).",
            context={"webhook_issue": "expired_timestamp"}
        )

    @staticmethod
    def unknown_event() -> WebhookError:
        return WebhookError(
            "Received unknown webhook event type.",
            context={"webhook_issue": "unknown_event"}
        )

    @staticmethod
    def missing_data() -> WebhookError:
        return WebhookError(
            "Webhook data is incomplete or malformed.",
            context={"webhook_issue": "missing_data"}
        )


# Human-readable error messages for logging/support
ERROR_MESSAGES = {
    "charge_declined": "Customer's card was declined",
    "lost_card": "Card reported as lost/stolen",
    "expired_card": "Card has expired",
    "insufficient_funds": "Insufficient funds",
    "network_error": "Network error contacting payment service",
    "timeout": "Payment service request timed out",
    "configuration_error": "Billing system misconfiguration",
    "validation_error": "Charge validation failed (amount out of range)",
    "unknown_error": "Unexpected error during payment processing",
}


def error_to_status_code(error: BillingError) -> int:
    """Map billing errors to HTTP status codes."""
    if isinstance(error, ConfigurationError):
        return 500 if "Billing system not configured" in error.message else 409
    elif isinstance(error, ChargeValidationError):
        return 400
    elif isinstance(error, ChargeDeclineError):
        return 402
    elif isinstance(error, SetupIntentError):
        return 400
    elif isinstance(error, PaymentMethodError):
        return 502
    elif isinstance(error, RefundError):
        if "not found" in error.message.lower():
            return 404
        elif "already" in error.message.lower():
            return 409
        else:
            return 502
    elif isinstance(error, WebhookError):
        if "signature" in error.message.lower():
            return 401
        else:
            return 400
    elif isinstance(error, StripeAPIError):
        if error.context.get("type") == "timeout":
            return 504
        elif error.context.get("http_status"):
            return min(error.context["http_status"], 502)
        else:
            return 502
    else:
        return 500


def format_error_for_logging(error: BillingError) -> dict:
    """Format error for structured logging."""
    return {
        "error_type": error.__class__.__name__,
        "message": error.message,
        "context": error.context,
    }
