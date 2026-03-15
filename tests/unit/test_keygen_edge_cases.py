"""Edge-case tests for keygen.generator — format, HMAC, uniqueness, character set."""

import re

import pytest

from vinzy_engine.keygen.generator import (
    BASE32_ALPHABET,
    HMAC_SEGMENTS,
    PREFIX_LEN,
    RANDOM_SEGMENTS,
    SEGMENT_LEN,
    _compute_hmac,
    generate_key,
    key_hash,
    verify_hmac,
)
from vinzy_engine.keygen.validator import validate_format, validate_key


HMAC_KEY = "test-hmac-key-for-unit-tests"

# Expected pattern: {PRD}-{5x5}-{5x5}-{5x5}-{5x5}-{5x5}-{5x5}-{5x5}
# Prefix is 3 uppercase letters, each segment is 5 base32 chars
_KEY_REGEX = re.compile(
    r"^[A-Z]{3}"
    + r"(-[A-Z2-7]{5})" * (RANDOM_SEGMENTS + HMAC_SEGMENTS)
    + r"$"
)


class TestKeyFormatRegex:
    """Validate the full key matches the expected regex pattern."""

    def test_default_product_matches_pattern(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert _KEY_REGEX.match(key), f"Key did not match pattern: {key}"

    def test_multiple_products_match_pattern(self):
        for code in ("ZUL", "AGW", "NXS", "VNZ", "CSM"):
            key = generate_key(code, HMAC_KEY)
            assert _KEY_REGEX.match(key), f"{code} key did not match: {key}"

    def test_total_segments_count(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        expected = 1 + RANDOM_SEGMENTS + HMAC_SEGMENTS  # 8
        assert len(parts) == expected

    def test_segment_lengths_all_five(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        assert len(parts[0]) == PREFIX_LEN
        for seg in parts[1:]:
            assert len(seg) == SEGMENT_LEN


class TestDifferentProductCodes:
    """Test key generation with various product codes."""

    def test_three_letter_codes(self):
        for code in ("ZUL", "AGW", "NXS", "VNZ", "CSM", "STD", "ARC"):
            key = generate_key(code, HMAC_KEY)
            assert key.startswith(f"{code}-")

    def test_lowercase_converted_to_upper(self):
        key = generate_key("zul", HMAC_KEY)
        assert key.startswith("ZUL-")

    def test_mixed_case_converted(self):
        key = generate_key("zUl", HMAC_KEY)
        assert key.startswith("ZUL-")

    def test_short_prefix_padded_with_x(self):
        key = generate_key("AB", HMAC_KEY)
        assert key.startswith("ABX-")

    def test_single_char_prefix_padded(self):
        key = generate_key("A", HMAC_KEY)
        assert key.startswith("AXX-")

    def test_empty_prefix_padded(self):
        key = generate_key("", HMAC_KEY)
        assert key.startswith("XXX-")

    def test_long_prefix_truncated(self):
        key = generate_key("ABCDEF", HMAC_KEY)
        assert key.startswith("ABC-")

    def test_numeric_chars_in_prefix_uppercased(self):
        # Numbers don't uppercase, but they get used as-is then padded/truncated
        key = generate_key("A1B", HMAC_KEY)
        prefix = key.split("-")[0]
        assert len(prefix) == PREFIX_LEN


class TestHmacVerification:
    """HMAC self-verification: every generated key must validate."""

    def test_key_validates_against_own_hmac(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert verify_hmac(key, HMAC_KEY) is True

    def test_wrong_hmac_key_rejects(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert verify_hmac(key, "completely-different-key") is False

    def test_different_product_same_hmac(self):
        k1 = generate_key("ZUL", HMAC_KEY)
        k2 = generate_key("NXS", HMAC_KEY)
        # Each key validates with the same HMAC key
        assert verify_hmac(k1, HMAC_KEY) is True
        assert verify_hmac(k2, HMAC_KEY) is True

    def test_tampered_prefix_invalidates(self):
        key = generate_key("ZUL", HMAC_KEY)
        tampered = "NXS" + key[3:]
        assert verify_hmac(tampered, HMAC_KEY) is False

    def test_swapped_segments_invalidates(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        # Swap two random segments
        parts[1], parts[2] = parts[2], parts[1]
        tampered = "-".join(parts)
        # May still pass if segments happen to be identical (extremely unlikely)
        # but in general should fail
        if parts[1] != parts[2]:
            assert verify_hmac(tampered, HMAC_KEY) is False


class TestInvalidProductCodes:
    """Ensure validate_format rejects keys with malformed prefixes."""

    def test_lowercase_prefix_in_raw_key_fails_format(self):
        # Manually construct a key with lowercase prefix
        key = generate_key("ZUL", HMAC_KEY)
        bad_key = key[:3].lower() + key[3:]
        result = validate_format(bad_key)
        assert result.valid is False
        assert result.code == "INVALID_PREFIX"

    def test_numeric_prefix_fails_format(self):
        bad_key = "123-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG"
        result = validate_format(bad_key)
        assert result.valid is False
        assert result.code == "INVALID_PREFIX"

    def test_too_short_prefix_in_raw_key(self):
        bad_key = "ZU-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG"
        result = validate_format(bad_key)
        assert result.valid is False
        assert result.code == "INVALID_PREFIX"

    def test_too_long_prefix_in_raw_key(self):
        bad_key = "ZULU-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG"
        result = validate_format(bad_key)
        assert result.valid is False
        # Either INVALID_PREFIX (4 chars) or INVALID_FORMAT (wrong segment count)
        assert result.valid is False

    def test_empty_key_fails(self):
        result = validate_format("")
        assert result.valid is False

    def test_none_key_fails(self):
        result = validate_format(None)
        assert result.valid is False

    def test_wrong_segment_count_fails(self):
        result = validate_format("ZUL-AAAAA-BBBBB")
        assert result.valid is False
        assert result.code == "INVALID_FORMAT"


class TestKeyUniqueness:
    """Generate many keys and ensure all are unique."""

    def test_100_keys_all_unique(self):
        keys = [generate_key("ZUL", HMAC_KEY) for _ in range(100)]
        assert len(set(keys)) == 100

    def test_100_keys_different_products_unique(self):
        keys = []
        for code in ("ZUL", "AGW", "NXS", "VNZ"):
            keys.extend(generate_key(code, HMAC_KEY) for _ in range(25))
        assert len(set(keys)) == 100

    def test_key_hashes_unique(self):
        keys = [generate_key("ZUL", HMAC_KEY) for _ in range(50)]
        hashes = [key_hash(k) for k in keys]
        assert len(set(hashes)) == 50


class TestKeyCharacterSet:
    """All segments (except prefix) use only valid base32 characters."""

    def test_random_segments_valid_base32(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        for seg in parts[1:]:
            for ch in seg:
                assert ch in BASE32_ALPHABET, f"Invalid char '{ch}' in segment '{seg}'"

    def test_hmac_segments_valid_base32(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        hmac_parts = parts[1 + RANDOM_SEGMENTS:]
        for seg in hmac_parts:
            for ch in seg:
                assert ch in BASE32_ALPHABET, f"Invalid char '{ch}' in HMAC segment '{seg}'"

    def test_no_digit_ambiguous_chars(self):
        """Base32 alphabet excludes digits 0, 1, 8, 9 to avoid ambiguity."""
        key = generate_key("ZUL", HMAC_KEY)
        segments = key.split("-")[1:]  # skip prefix
        all_chars = "".join(segments)
        for ambiguous in "0189":
            assert ambiguous not in all_chars


class TestDeterministicHmac:
    """Same input must produce the same HMAC output."""

    def test_same_input_same_hmac(self):
        h1 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        h2 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        assert h1 == h2

    def test_different_random_different_hmac(self):
        h1 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        h2 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-FFFFF", HMAC_KEY)
        assert h1 != h2

    def test_different_prefix_different_hmac(self):
        h1 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        h2 = _compute_hmac("NXS", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        assert h1 != h2

    def test_different_hmac_key_different_output(self):
        h1 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        h2 = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", "other-key")
        assert h1 != h2

    def test_hmac_length(self):
        h = _compute_hmac("ZUL", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", HMAC_KEY)
        assert len(h) == SEGMENT_LEN * HMAC_SEGMENTS  # 10 chars

    def test_validate_key_full_roundtrip(self):
        key = generate_key("ZUL", HMAC_KEY)
        result = validate_key(key, HMAC_KEY)
        assert result.valid is True
        assert result.code == "VALID"
        assert result.product_prefix == "ZUL"
