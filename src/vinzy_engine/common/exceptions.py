"""Vinzy-Engine exception hierarchy."""


class VinzyError(Exception):
    """Base exception for all Vinzy errors."""

    def __init__(self, message: str = "", code: str = "VINZY_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class InvalidKeyError(VinzyError):
    """Raised when a license key fails format or HMAC validation."""

    def __init__(self, message: str = "Invalid license key"):
        super().__init__(message, code="INVALID_KEY")


class LicenseNotFoundError(VinzyError):
    """Raised when a license cannot be found in the database."""

    def __init__(self, message: str = "License not found"):
        super().__init__(message, code="NOT_FOUND")


class LicenseExpiredError(VinzyError):
    """Raised when a license has expired."""

    def __init__(self, message: str = "License has expired"):
        super().__init__(message, code="EXPIRED")


class LicenseSuspendedError(VinzyError):
    """Raised when a license is suspended or revoked."""

    def __init__(self, message: str = "License is suspended"):
        super().__init__(message, code="SUSPENDED")


class ActivationLimitError(VinzyError):
    """Raised when machine activation limit is reached."""

    def __init__(self, message: str = "Machine activation limit reached"):
        super().__init__(message, code="ACTIVATION_LIMIT")


class EntitlementError(VinzyError):
    """Raised when an entitlement check fails."""

    def __init__(self, message: str = "Entitlement not available"):
        super().__init__(message, code="ENTITLEMENT_DENIED")
