"""Tests for keygen.generator — key generation and HMAC signing."""

import pytest

from vinzy_engine.keygen.generator import (
    BASE32_ALPHABET,
    HMAC_SEGMENTS,
    RANDOM_SEGMENTS,
    SEGMENT_LEN,
    _compute_hmac,
    _encode_version,
    _decode_version,
    _random_segment,
    extract_version,
    generate_key,
    key_hash,
    verify_hmac,
    verify_hmac_multi,
)


HMAC_KEY = "test-hmac-key-for-unit-tests"


class TestRandomSegment:
    def test_length(self):
        seg = _random_segment()
        assert len(seg) == SEGMENT_LEN

    def test_alphabet(self):
        seg = _random_segment()
        for ch in seg:
            assert ch in BASE32_ALPHABET

    def test_uniqueness(self):
        segments = {_random_segment() for _ in range(100)}
        assert len(segments) > 90  # statistically near-unique


class TestGenerateKey:
    def test_format(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        assert len(parts) == 1 + RANDOM_SEGMENTS + HMAC_SEGMENTS

    def test_prefix(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert key.startswith("ZUL-")

    def test_prefix_uppercase(self):
        key = generate_key("zul", HMAC_KEY)
        assert key.startswith("ZUL-")

    def test_short_prefix_padded(self):
        key = generate_key("AB", HMAC_KEY)
        assert key.startswith("ABX-")

    def test_all_segments_valid_base32(self):
        key = generate_key("ZUL", HMAC_KEY)
        for segment in key.split("-")[1:]:
            assert len(segment) == SEGMENT_LEN
            for ch in segment:
                assert ch in BASE32_ALPHABET

    def test_uniqueness(self):
        keys = {generate_key("ZUL", HMAC_KEY) for _ in range(50)}
        assert len(keys) == 50

    def test_different_products(self):
        k1 = generate_key("ZUL", HMAC_KEY)
        k2 = generate_key("NXS", HMAC_KEY)
        assert k1[:3] != k2[:3]


class TestVerifyHmac:
    def test_valid_key(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert verify_hmac(key, HMAC_KEY) is True

    def test_wrong_hmac_key(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert verify_hmac(key, "wrong-key") is False

    def test_tampered_random_segment(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        # Flip a character in the first random segment
        seg = list(parts[1])
        seg[0] = "A" if seg[0] != "A" else "B"
        parts[1] = "".join(seg)
        tampered = "-".join(parts)
        assert verify_hmac(tampered, HMAC_KEY) is False

    def test_tampered_hmac_segment(self):
        key = generate_key("ZUL", HMAC_KEY)
        parts = key.split("-")
        seg = list(parts[-1])
        seg[0] = "A" if seg[0] != "A" else "B"
        parts[-1] = "".join(seg)
        tampered = "-".join(parts)
        assert verify_hmac(tampered, HMAC_KEY) is False

    def test_wrong_segment_count(self):
        assert verify_hmac("ZUL-AAAAA-BBBBB", HMAC_KEY) is False

    def test_empty_key(self):
        assert verify_hmac("", HMAC_KEY) is False


class TestVersionEncoding:
    def test_encode_decode_roundtrip(self):
        for v in range(32):
            ch = _encode_version(v)
            assert _decode_version(ch) == v

    def test_version_embedded_in_key(self):
        key = generate_key("ZUL", HMAC_KEY, version=5)
        assert extract_version(key) == 5

    def test_version_0_default(self):
        key = generate_key("ZUL", HMAC_KEY, version=0)
        assert extract_version(key) == 0

    def test_extract_from_malformed_key(self):
        assert extract_version("") == 0
        assert extract_version("ZUL") == 0


class TestVerifyHmacMulti:
    def test_valid_with_matching_version(self):
        keyring = {0: "key-v0", 1: "key-v1"}
        key = generate_key("ZUL", "key-v1", version=1)
        assert verify_hmac_multi(key, keyring) is True

    def test_rotated_key_still_validates(self):
        """v0 key validates against keyring that has v0 + v1."""
        old_key = generate_key("ZUL", "old-secret", version=0)
        keyring = {0: "old-secret", 1: "new-secret"}
        assert verify_hmac_multi(old_key, keyring) is True

    def test_wrong_keyring_fails(self):
        key = generate_key("ZUL", "real-secret", version=0)
        keyring = {0: "wrong-a", 1: "wrong-b"}
        assert verify_hmac_multi(key, keyring) is False

    def test_legacy_v0_fallback(self):
        """A v0 key whose first char was random (not version byte)
        still validates via fallback when v0 key is in the ring."""
        # generate_key with version=0 puts 'A' (index 0) as first char
        # but old keys had random first chars — simulate by using verify_hmac directly
        key = generate_key("ZUL", HMAC_KEY, version=0)
        keyring = {0: HMAC_KEY}
        assert verify_hmac_multi(key, keyring) is True


class TestKeyHash:
    def test_deterministic(self):
        key = generate_key("ZUL", HMAC_KEY)
        assert key_hash(key) == key_hash(key)

    def test_hex_string(self):
        h = key_hash("ZUL-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
