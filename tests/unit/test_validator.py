"""Tests for keygen.validator — offline format and HMAC validation."""

import pytest

from vinzy_engine.keygen.generator import generate_key
from vinzy_engine.keygen.validator import validate_format, validate_key, validate_key_multi


HMAC_KEY = "test-hmac-key-for-unit-tests"


class TestValidateFormat:
    def test_valid_key(self):
        key = generate_key("ZUL", HMAC_KEY)
        result = validate_format(key)
        assert result.valid is True
        assert result.code == "FORMAT_OK"
        assert result.product_prefix == "ZUL"

    def test_empty_key(self):
        result = validate_format("")
        assert result.valid is False
        assert result.code == "INVALID_FORMAT"

    def test_none_key(self):
        result = validate_format(None)
        assert result.valid is False
        assert result.code == "INVALID_FORMAT"

    def test_wrong_segment_count(self):
        result = validate_format("ZUL-AAAAA-BBBBB")
        assert result.valid is False
        assert result.code == "INVALID_FORMAT"

    def test_lowercase_prefix(self):
        key = generate_key("ZUL", HMAC_KEY)
        # Force prefix to lowercase
        bad = key[0:3].lower() + key[3:]
        result = validate_format(bad)
        assert result.valid is False
        assert result.code == "INVALID_PREFIX"

    def test_numeric_prefix(self):
        result = validate_format("123-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG")
        assert result.valid is False
        assert result.code == "INVALID_PREFIX"

    def test_invalid_segment_chars(self):
        # '0' is not in base32 alphabet
        result = validate_format("ZUL-00000-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG")
        assert result.valid is False
        assert result.code == "INVALID_SEGMENT"

    def test_short_segment(self):
        result = validate_format("ZUL-AAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG")
        assert result.valid is False
        assert result.code == "INVALID_SEGMENT"

    def test_long_segment(self):
        result = validate_format("ZUL-AAAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG")
        assert result.valid is False
        assert result.code == "INVALID_SEGMENT"

    def test_extracts_product_prefix(self):
        key = generate_key("NXS", HMAC_KEY)
        result = validate_format(key)
        assert result.product_prefix == "NXS"

    def test_integer_input(self):
        result = validate_format(12345)
        assert result.valid is False


class TestValidateKey:
    def test_valid_key(self):
        key = generate_key("ZUL", HMAC_KEY)
        result = validate_key(key, HMAC_KEY)
        assert result.valid is True
        assert result.code == "VALID"
        assert result.product_prefix == "ZUL"

    def test_wrong_hmac_key(self):
        key = generate_key("ZUL", HMAC_KEY)
        result = validate_key(key, "wrong-key")
        assert result.valid is False
        assert result.code == "INVALID_HMAC"

    def test_tampered_key(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        seg = list(parts[3])
        seg[0] = "A" if seg[0] != "A" else "B"
        parts[3] = "".join(seg)
        tampered = "-".join(parts)
        result = validate_key(tampered, HMAC_KEY)
        assert result.valid is False

    def test_invalid_format_fails_fast(self):
        result = validate_key("bad-key", HMAC_KEY)
        assert result.valid is False
        assert result.code == "INVALID_FORMAT"

    def test_message_on_valid(self):
        key = generate_key("ZUL", HMAC_KEY)
        result = validate_key(key, HMAC_KEY)
        assert "valid" in result.message.lower()


class TestValidateKeyMulti:
    def test_valid_key_against_keyring(self):
        keyring = {0: HMAC_KEY, 1: "new-key"}
        key = generate_key("ZUL", HMAC_KEY, version=0)
        result = validate_key_multi(key, keyring)
        assert result.valid is True
        assert result.code == "VALID"

    def test_rotated_key_validates(self):
        keyring = {0: "old-key", 1: "new-key"}
        key = generate_key("ZUL", "new-key", version=1)
        result = validate_key_multi(key, keyring)
        assert result.valid is True

    def test_wrong_keyring_fails(self):
        keyring = {0: "wrong-a", 1: "wrong-b"}
        key = generate_key("ZUL", "real-key", version=0)
        result = validate_key_multi(key, keyring)
        assert result.valid is False
        assert result.code == "INVALID_HMAC"
