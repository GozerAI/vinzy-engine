"""Vinzy-Engine: Cryptographic key generator and license manager."""

from vinzy_engine.client import LicenseClient
from vinzy_engine.keygen.generator import generate_key, verify_hmac, verify_hmac_multi, key_hash
from vinzy_engine.keygen.validator import validate_key, validate_key_multi, validate_format

__all__ = [
    "LicenseClient",
    "generate_key",
    "verify_hmac",
    "verify_hmac_multi",
    "key_hash",
    "validate_key",
    "validate_key_multi",
    "validate_format",
]
__version__ = "0.1.0"
