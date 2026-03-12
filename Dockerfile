FROM python:3.12-slim

LABEL org.opencontainers.image.title="Vinzy-Engine"
LABEL org.opencontainers.image.description="Cryptographic License Key Generator & Entitlement Manager"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.vendor="GozerAI"

# Create non-root user
RUN groupadd --gid 1000 vinzy && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash vinzy

WORKDIR /app

# Install runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/

RUN pip install --no-cache-dir ".[postgres,stripe]"

RUN mkdir -p data && chown -R vinzy:vinzy /app

USER vinzy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "vinzy_engine.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
