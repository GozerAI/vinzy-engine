"""IP allowlist middleware for Vinzy-Engine."""

import ipaddress
from typing import Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject requests from IPs not in the allowlist.

    When enabled with a non-empty allowlist, only requests from listed
    IPs/CIDRs are permitted.  Localhost (127.0.0.1, ::1) is always allowed.
    """

    def __init__(self, app, *, allowlist: Sequence[str]):
        super().__init__(app)
        self._networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for entry in allowlist:
            self._networks.append(ipaddress.ip_network(entry, strict=False))
        # Always allow localhost
        self._networks.append(ipaddress.ip_network("127.0.0.1/32"))
        self._networks.append(ipaddress.ip_network("::1/128"))

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "127.0.0.1"
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid client IP address"},
            )

        if not any(addr in net for net in self._networks):
            return JSONResponse(
                status_code=403,
                content={"detail": f"IP {client_ip} is not in the allowlist"},
            )

        return await call_next(request)
