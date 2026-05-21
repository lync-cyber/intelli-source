"""PII masking helpers for distributor logging and persistence."""

from __future__ import annotations


def mask_email(email: str) -> str:
    """Mask *email*: keep first char of local part + full domain."""
    if "@" not in email:
        if not email:
            return ""
        return email[:1] + "***"
    local, _, domain = email.partition("@")
    if not local:
        return "@" + domain
    if "*" in local:
        # Already masked — idempotent: return as-is.
        return email
    return local[:1] + "***@" + domain


def mask_phone(phone: str) -> str:
    """Mask *phone*: keep first 3 + last 4 digits; middle replaced with ***."""
    if "***" in phone:
        # Already masked — idempotent.
        return phone
    digits = [c for c in phone if c.isdigit()]
    if len(digits) < 7:
        return phone
    # When a '+' prefix is present, strip country code digits so the local
    # subscriber number is isolated (typical mobile is 11 digits).
    local_digits = digits
    if phone.startswith("+") and len(digits) > 11:
        # Skip leading country code digits until ≤ 11 remain.
        local_digits = digits[len(digits) - 11 :]
    first3 = "".join(local_digits[:3])
    last4 = "".join(local_digits[-4:])
    return first3 + "***" + last4
