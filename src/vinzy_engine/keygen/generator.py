"""
License key generator using HMAC-SHA256 signing.

Format: {PRD}-{AAAAA}-{BBBBB}-{CCCCC}-{DDDDD}-{EEEEE}-{HHHHH}-{HHHHH}
- 3-char product prefix
- 5 segments x 5 base32 chars = 25 random chars (32^25 ≈ 10^37 unique keys per product)
- 2 segments of HMAC-SHA256 truncation (50 bits) for tamper detection

Version encoding:
- The first character of the first random segment encodes the HMAC key version (0-31).
- Existing v0 keys have a random first char; they are verified by fallback when no
  explicit version match is found in the keyring.
"""

import base64
import hashlib
import hmac
import os

# Base32 alphabet (uppercase + digits 2-7, no 0/1/8/9/O/I to avoid ambiguity)
BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
SEGMENT_LEN = 5
RANDOM_SEGMENTS = 5
HMAC_SEGMENTS = 2
TOTAL_SEGMENTS = RANDOM_SEGMENTS + HMAC_SEGMENTS
PREFIX_LEN = 3


def _random_segment() -> str:
    """Generate a random 5-char base32 segment."""
    return "".join(
        BASE32_ALPHABET[b % 32] for b in os.urandom(SEGMENT_LEN)
    )


def _encode_version(version: int) -> str:
    """Encode a version number (0-31) as a single base32 character."""
    return BASE32_ALPHABET[version % 32]


def _decode_version(char: str) -> int:
    """Decode a base32 character back to a version number (0-31)."""
    idx = BASE32_ALPHABET.find(char)
    if idx == -1:
        return 0
    return idx


def extract_version(key: str) -> int:
    """Extract the HMAC key version from a license key.

    The version is encoded in the first character of the first random segment
    (the 5th character, after the prefix and its dash).
    """
    parts = key.split("-")
    if len(parts) < 2 or len(parts[1]) < 1:
        return 0
    return _decode_version(parts[1][0])


def _compute_hmac(product_prefix: str, random_part: str, hmac_key: str) -> str:
    """Compute HMAC-SHA256 over prefix+random, return 10-char base32 truncation."""
    message = f"{product_prefix}-{random_part}".encode()
    digest = hmac.new(hmac_key.encode(), message, hashlib.sha256).digest()
    b32 = base64.b32encode(digest).decode("ascii").rstrip("=")
    return b32[:SEGMENT_LEN * HMAC_SEGMENTS]


def generate_key(product_prefix: str, hmac_key: str, version: int = 0) -> str:
    """
    Generate a complete license key.

    Args:
        product_prefix: 3-char product code (e.g., 'ZUL')
        hmac_key: HMAC signing key
        version: HMAC key version (0-31), encoded in key's first random char

    Returns:
        Formatted license key string
    """
    prefix = product_prefix.upper()[:PREFIX_LEN].ljust(PREFIX_LEN, "X")

    # Generate 5 random segments
    random_segments = [_random_segment() for _ in range(RANDOM_SEGMENTS)]

    # Encode version in first char of first random segment
    seg0 = list(random_segments[0])
    seg0[0] = _encode_version(version)
    random_segments[0] = "".join(seg0)

    random_part = "-".join(random_segments)

    # Compute HMAC signature segments
    hmac_str = _compute_hmac(prefix, random_part, hmac_key)
    hmac_seg1 = hmac_str[:SEGMENT_LEN]
    hmac_seg2 = hmac_str[SEGMENT_LEN:SEGMENT_LEN * 2]

    return f"{prefix}-{random_part}-{hmac_seg1}-{hmac_seg2}"


def verify_hmac(key: str, hmac_key: str) -> bool:
    """
    Verify the HMAC signature of a license key (offline validation).

    Args:
        key: Full license key string
        hmac_key: HMAC signing key

    Returns:
        True if the HMAC matches
    """
    parts = key.split("-")
    if len(parts) != 1 + RANDOM_SEGMENTS + HMAC_SEGMENTS:
        return False

    prefix = parts[0]
    random_part = "-".join(parts[1 : 1 + RANDOM_SEGMENTS])
    provided_hmac = "".join(parts[1 + RANDOM_SEGMENTS :])

    expected_hmac = _compute_hmac(prefix, random_part, hmac_key)
    return hmac.compare_digest(provided_hmac, expected_hmac)


def verify_hmac_multi(key: str, hmac_keys: dict[int, str]) -> bool:
    """
    Verify HMAC against a keyring (multiple versioned keys).

    Tries the key corresponding to the embedded version first,
    then falls back to all other keys (supports v0 legacy keys
    where the first char was random, not a version byte).

    Args:
        key: Full license key string
        hmac_keys: Dict mapping version (int) to HMAC key string

    Returns:
        True if the HMAC matches any key in the ring
    """
    version = extract_version(key)

    # Try the versioned key first
    if version in hmac_keys:
        if verify_hmac(key, hmac_keys[version]):
            return True

    # Fall back to all other keys (handles v0 legacy keys)
    for v, k in hmac_keys.items():
        if v == version:
            continue
        if verify_hmac(key, k):
            return True

    return False


def key_hash(key: str) -> str:
    """Compute SHA-256 hash of a key for DB indexing (never store raw key)."""
    return hashlib.sha256(key.encode()).hexdigest()
