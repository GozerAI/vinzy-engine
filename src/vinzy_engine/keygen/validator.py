"""
Offline license key format validation.

Validates structure and HMAC without requiring database access.
"""

import re

from vinzy_engine.keygen.generator import (
    BASE32_ALPHABET,
    HMAC_SEGMENTS,
    PREFIX_LEN,
    RANDOM_SEGMENTS,
    SEGMENT_LEN,
    verify_hmac,
    verify_hmac_multi,
)

# Total segments: prefix(1) + random(5) + hmac(2) = 8 parts
EXPECTED_PARTS = 1 + RANDOM_SEGMENTS + HMAC_SEGMENTS
BASE32_PATTERN = re.compile(f"^[{BASE32_ALPHABET}]{{{SEGMENT_LEN}}}$")
PREFIX_PATTERN = re.compile(f"^[A-Z]{{{PREFIX_LEN}}}$")


class ValidationResult:
    """Result of offline key validation."""

    __slots__ = ("valid", "code", "message", "product_prefix")

    def __init__(
        self,
        valid: bool,
        code: str = "",
        message: str = "",
        product_prefix: str = "",
    ):
        self.valid = valid
        self.code = code
        self.message = message
        self.product_prefix = product_prefix


def validate_format(key: str) -> ValidationResult:
    """
    Validate the structural format of a license key (no HMAC check).

    Checks:
    - Correct number of segments (8)
    - 3-char uppercase prefix
    - All segments are valid base32

    Returns:
        ValidationResult with format check outcome
    """
    if not key or not isinstance(key, str):
        return ValidationResult(False, "INVALID_FORMAT", "Key is empty or not a string")

    parts = key.split("-")
    if len(parts) != EXPECTED_PARTS:
        return ValidationResult(
            False,
            "INVALID_FORMAT",
            f"Expected {EXPECTED_PARTS} segments, got {len(parts)}",
        )

    prefix = parts[0]
    if not PREFIX_PATTERN.match(prefix):
        return ValidationResult(
            False,
            "INVALID_PREFIX",
            f"Prefix must be {PREFIX_LEN} uppercase letters",
        )

    for i, segment in enumerate(parts[1:], start=1):
        if not BASE32_PATTERN.match(segment):
            return ValidationResult(
                False,
                "INVALID_SEGMENT",
                f"Segment {i} is not valid base32 (got '{segment}')",
            )

    return ValidationResult(True, "FORMAT_OK", "Key format is valid", prefix)


def validate_key(key: str, hmac_key: str) -> ValidationResult:
    """
    Full offline validation: format + HMAC check.

    Args:
        key: License key string
        hmac_key: HMAC signing key

    Returns:
        ValidationResult with validation outcome
    """
    fmt_result = validate_format(key)
    if not fmt_result.valid:
        return fmt_result

    if not verify_hmac(key, hmac_key):
        return ValidationResult(
            False,
            "INVALID_HMAC",
            "Key HMAC signature does not match — key may be tampered",
            fmt_result.product_prefix,
        )

    return ValidationResult(
        True,
        "VALID",
        "Key is structurally valid with correct HMAC",
        fmt_result.product_prefix,
    )


def validate_key_multi(key: str, hmac_keys: dict[int, str]) -> ValidationResult:
    """
    Full offline validation against a keyring: format + multi-key HMAC check.

    Args:
        key: License key string
        hmac_keys: Dict mapping version (int) to HMAC key string

    Returns:
        ValidationResult with validation outcome
    """
    fmt_result = validate_format(key)
    if not fmt_result.valid:
        return fmt_result

    if not verify_hmac_multi(key, hmac_keys):
        return ValidationResult(
            False,
            "INVALID_HMAC",
            "Key HMAC signature does not match — key may be tampered",
            fmt_result.product_prefix,
        )

    return ValidationResult(
        True,
        "VALID",
        "Key is structurally valid with correct HMAC",
        fmt_result.product_prefix,
    )
