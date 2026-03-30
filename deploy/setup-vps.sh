#!/usr/bin/env bash
# Vinzy-Engine VPS Setup Script
# Run as root or with sudo
set -euo pipefail

APP_DIR="/opt/vinzy"
REPO_URL="https://github.com/chrisarseno/vinzy-engine.git"

echo "=== Vinzy-Engine VPS Setup ==="

# 1. Create directory
echo "[1/5] Setting up directory..."
mkdir -p "$APP_DIR"

# 2. Clone repo
echo "[2/5] Cloning Vinzy-Engine..."
if [ ! -d "$APP_DIR/repo" ]; then
    git clone "$REPO_URL" "$APP_DIR/repo"
else
    cd "$APP_DIR/repo" && git pull
fi

# 3. Environment file
echo "[3/5] Setting up environment..."
if [ ! -f "$APP_DIR/repo/.env" ]; then
    cp "$APP_DIR/repo/.env.example" "$APP_DIR/repo/.env"
    # Generate random secrets
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    HMAC_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    SUPER_ADMIN_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

    sed -i "s|VINZY_SECRET_KEY=change-me-to-a-random-secret|VINZY_SECRET_KEY=$SECRET_KEY|" "$APP_DIR/repo/.env"
    sed -i "s|VINZY_HMAC_KEY=change-me-to-a-random-hmac-key|VINZY_HMAC_KEY=$HMAC_KEY|" "$APP_DIR/repo/.env"
    sed -i "s|VINZY_API_KEY=change-me-to-a-random-api-key|VINZY_API_KEY=$API_KEY|" "$APP_DIR/repo/.env"
    sed -i "s|VINZY_SUPER_ADMIN_KEY=change-me-to-a-random-super-admin-key|VINZY_SUPER_ADMIN_KEY=$SUPER_ADMIN_KEY|" "$APP_DIR/repo/.env"
    sed -i "s|VINZY_ENVIRONMENT=development|VINZY_ENVIRONMENT=production|" "$APP_DIR/repo/.env"

    echo ""
    echo "  >> Generated secrets written to $APP_DIR/repo/.env"
    echo "  >> IMPORTANT: Set these in $APP_DIR/repo/.env:"
    echo "     - VINZY_ZUULTIMATE_SERVICE_TOKEN (copy from Zuultimate's ZUUL_SERVICE_TOKEN)"
    echo "     - VINZY_PRODUCT_CALLBACK_TOKEN (same token for Arclane callback auth)"
    echo "     - VINZY_PRODUCT_CALLBACKS (JSON map of product webhooks)"
    echo "     - VINZY_STRIPE_SECRET_KEY, VINZY_STRIPE_WEBHOOK_SECRET"
    echo ""
fi

# 4. Ensure shared Docker networks exist
echo "[4/5] Setting up Docker networks..."
docker network create webproxy 2>/dev/null || true
docker network create backend 2>/dev/null || true

# 5. Build and start
echo "[5/5] Building and starting services..."
cd "$APP_DIR/repo/deploy"
docker compose -f docker-compose.vps.yml up -d --build

# Run migrations
echo "Running database migrations..."
docker compose -f docker-compose.vps.yml exec vinzy python -m alembic upgrade head \
    || echo "  >> Migration skipped (first run — tables created by init)"

echo ""
echo "=== Vinzy-Engine Setup Complete ==="
echo "Health: http://localhost:8080/health"
echo ""
echo "Next steps:"
echo "  1. Set VINZY_ZUULTIMATE_SERVICE_TOKEN (from Zuultimate's ZUUL_SERVICE_TOKEN)"
echo "  2. Set VINZY_PRODUCT_CALLBACKS and VINZY_PRODUCT_CALLBACK_TOKEN"
echo "  3. Set Stripe keys when ready"
echo "  4. docker compose -f docker-compose.vps.yml logs -f"
