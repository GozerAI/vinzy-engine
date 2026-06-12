"""Response compression middleware with gzip and brotli support.

Adds transparent compression based on the Accept-Encoding header.
Gzip is always available; brotli is used when the brotli package is installed.
"""

import gzip
import io
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

logger = logging.getLogger(__name__)

# Minimum response size to compress (bytes)
MIN_COMPRESS_SIZE = 500

# Content types eligible for compression
COMPRESSIBLE_TYPES = frozenset({
    "application/json",
    "text/plain",
    "text/html",
    "text/css",
    "application/javascript",
    "text/xml",
    "application/xml",
})

# Try to import brotli
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False


def _should_compress(content_type: str | None, content_length: int) -> bool:
    """Check if a response should be compressed."""
    if content_length < MIN_COMPRESS_SIZE:
        return False
    if not content_type:
        return False
    # Check base content type (strip charset etc)
    base_type = content_type.split(";")[0].strip().lower()
    return base_type in COMPRESSIBLE_TYPES


def _get_preferred_encoding(accept_encoding: str) -> Optional[str]:
    """Parse Accept-Encoding and return the best supported encoding."""
    if not accept_encoding:
        return None

    encodings = {}
    for part in accept_encoding.split(","):
        part = part.strip()
        if ";q=" in part:
            enc, q = part.split(";q=", 1)
            try:
                encodings[enc.strip()] = float(q.strip())
            except ValueError:
                encodings[enc.strip()] = 0.0
        else:
            encodings[part] = 1.0

    # Prefer brotli > gzip
    if HAS_BROTLI and encodings.get("br", 0) > 0:
        return "br"
    if encodings.get("gzip", 0) > 0:
        return "gzip"
    return None


def compress_gzip(data: bytes, level: int = 6) -> bytes:
    """Compress data using gzip."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level) as f:
        f.write(data)
    return buf.getvalue()


def compress_brotli(data: bytes, quality: int = 4) -> bytes:
    """Compress data using brotli (if available)."""
    if not HAS_BROTLI:
        raise RuntimeError("brotli package not installed")
    return brotli.compress(data, quality=quality)


class CompressionMiddleware(BaseHTTPMiddleware):
    """Middleware that compresses responses based on Accept-Encoding.

    Supports gzip (always) and brotli (when brotli package is installed).
    Only compresses responses above MIN_COMPRESS_SIZE bytes with
    compressible content types.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        response: StarletteResponse = await call_next(request)

        # Skip if already encoded
        if response.headers.get("content-encoding"):
            return response

        accept_encoding = request.headers.get("accept-encoding", "")
        encoding = _get_preferred_encoding(accept_encoding)
        if encoding is None:
            return response

        # Read the response body
        body_parts = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            body_parts.append(chunk)
        body = b"".join(body_parts)

        content_type = response.headers.get("content-type")
        if not _should_compress(content_type, len(body)):
            return StarletteResponse(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        try:
            if encoding == "br" and HAS_BROTLI:
                compressed = compress_brotli(body)
            elif encoding == "gzip":
                compressed = compress_gzip(body)
            else:
                return StarletteResponse(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
        except Exception:
            logger.exception("Compression failed, returning uncompressed response")
            return StarletteResponse(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        headers = dict(response.headers)
        headers["content-encoding"] = encoding
        headers["content-length"] = str(len(compressed))
        headers["vary"] = "Accept-Encoding"

        return StarletteResponse(
            content=compressed,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
