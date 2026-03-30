"""Dashboard cookie-based session authentication."""

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.requests import Request
from starlette.responses import RedirectResponse

COOKIE_NAME = "vinzy_dash_session"
MAX_AGE = 8 * 3600  # 8 hours


def _get_serializer() -> URLSafeTimedSerializer:
    from vinzy_engine.common.config import get_settings
    return URLSafeTimedSerializer(get_settings().secret_key, salt="dashboard-session")


def create_session_cookie(role: str) -> str:
    """Sign a session payload and return the cookie value."""
    s = _get_serializer()
    return s.dumps({"role": role})


def verify_session_cookie(cookie: str) -> dict | None:
    """Verify and decode a session cookie. Returns payload or None."""
    s = _get_serializer()
    try:
        return s.loads(cookie, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_session(request: Request) -> dict | None:
    """Extract and verify the session from a request."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    return verify_session_cookie(cookie)


def require_login(request: Request) -> dict | None:
    """Check if user is logged in, return session or None."""
    return get_session(request)


def login_redirect() -> RedirectResponse:
    """Create a redirect to the login page."""
    return RedirectResponse("/dashboard/login", status_code=302)
