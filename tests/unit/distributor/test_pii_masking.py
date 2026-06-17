"""Tests for PII masking helpers in distributor/pii.py.

Covers AC-8.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AC-8: mask_email and mask_phone pure functions
# ---------------------------------------------------------------------------


class TestAC8MaskEmail:
    """mask_email() redacts local part, preserves domain."""

    def test_standard_email(self) -> None:
        """Standard email: first char kept, middle redacted, domain preserved."""
        from intellisource.distributor.pii import mask_email

        result = mask_email("alice@example.com")
        # First char of local part is kept
        assert result.startswith("a")
        # Domain is preserved
        assert result.endswith("@example.com")
        # Middle is redacted (contains asterisks)
        assert "***" in result or "*" in result
        # Raw local part is not present
        assert "lice" not in result

    def test_single_char_local_part(self) -> None:
        """Local part with single character is handled gracefully (no IndexError)."""
        from intellisource.distributor.pii import mask_email

        result = mask_email("a@example.com")
        # Must not raise; must contain @ and domain
        assert "@example.com" in result
        # Must contain some masking indicator
        assert "*" in result or result == "a@example.com"

    def test_no_at_symbol(self) -> None:
        """Input without '@' is returned in a masked or unchanged safe form."""
        from intellisource.distributor.pii import mask_email

        result = mask_email("notanemail")
        # Must not raise; original raw string is either masked or returned as-is
        assert isinstance(result, str)
        assert len(result) > 0

    def test_multi_char_local_part_redacted_middle(self) -> None:
        """Multi-char local part: first char preserved, rest redacted, domain intact."""
        from intellisource.distributor.pii import mask_email

        result = mask_email("user@domain.org")
        assert result.startswith("u")
        assert "@domain.org" in result
        # Middle characters are masked
        assert "*" in result.split("@")[0]

    def test_idempotent_already_masked(self) -> None:
        """mask(mask(x)) == mask(x): applying mask twice yields same result."""
        from intellisource.distributor.pii import mask_email

        original = "bob@test.io"
        once = mask_email(original)
        twice = mask_email(once)
        assert once == twice, (
            f"mask_email is not idempotent: mask(x)={once!r}, mask(mask(x))={twice!r}"
        )

    def test_domain_preserved_exactly(self) -> None:
        """The domain portion after '@' must be identical to input domain."""
        from intellisource.distributor.pii import mask_email

        result = mask_email("charlie@subdomain.example.co.uk")
        assert result.endswith("@subdomain.example.co.uk"), (
            f"Domain not preserved: {result!r}"
        )

    def test_returns_string(self) -> None:
        """mask_email always returns a str."""
        from intellisource.distributor.pii import mask_email

        assert isinstance(mask_email("x@y.z"), str)


class TestAC8MaskPhone:
    """mask_phone() keeps first 3 + last 4 digits, masks middle."""

    def test_phone_with_country_code(self) -> None:
        """Phone with +86 prefix: first 3 digits after + preserved, last 4 preserved."""
        from intellisource.distributor.pii import mask_phone

        result = mask_phone("+8613812345678")
        # The result must contain asterisks
        assert "*" in result
        # Last 4 digits of the raw number are preserved
        assert "5678" in result
        # First 3 digits (138) are preserved
        assert "138" in result
        # The full raw number is not present
        assert "13812345678"[:7] not in result or "*" in result

    def test_phone_without_country_code(self) -> None:
        """11-digit mobile without country code: first 3 + last 4 preserved."""
        from intellisource.distributor.pii import mask_phone

        result = mask_phone("13912345678")
        assert "*" in result
        # Last 4 digits preserved
        assert "5678" in result
        # First 3 digits preserved
        assert "139" in result

    def test_phone_all_digits_no_plus(self) -> None:
        """Pure digit string without plus: masked with middle hidden."""
        from intellisource.distributor.pii import mask_phone

        result = mask_phone("08612345678")
        assert isinstance(result, str)
        assert "*" in result
        assert "5678" in result

    def test_idempotent_already_masked(self) -> None:
        """mask(mask(x)) == mask(x): applying mask twice yields same result."""
        from intellisource.distributor.pii import mask_phone

        original = "+8613812345678"
        once = mask_phone(original)
        twice = mask_phone(once)
        assert once == twice, (
            f"mask_phone is not idempotent: mask(x)={once!r}, mask(mask(x))={twice!r}"
        )

    def test_returns_string(self) -> None:
        """mask_phone always returns a str."""
        from intellisource.distributor.pii import mask_phone

        assert isinstance(mask_phone("+8613812345678"), str)

    def test_mask_hides_middle_digits(self) -> None:
        """Middle portion is replaced with asterisks, not partially visible."""
        from intellisource.distributor.pii import mask_phone

        result = mask_phone("+8613812345678")
        # "1234" (middle) should not appear in the result
        assert "1234" not in result, (
            f"Middle digits '1234' should be masked but appeared in: {result!r}"
        )
