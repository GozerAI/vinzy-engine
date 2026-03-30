#!/usr/bin/env bash
# export_public.sh - Creates a clean public export of Vinzy-Engine for GozerAI/vinzy-engine.
# Usage: bash scripts/export_public.sh [target_dir]
#
# Strips proprietary Pro/Enterprise modules and internal infrastructure,
# leaving only community-tier code + license gate stubs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-${REPO_ROOT}/../vinzy-engine-public-export}"

echo "=== Vinzy-Engine Public Export ==="
echo "Source: ${REPO_ROOT}"
echo "Target: ${TARGET}"

# Clean target
rm -rf "${TARGET}"
mkdir -p "${TARGET}"

# Use git archive to get a clean copy (respects .gitignore, excludes .git)
cd "${REPO_ROOT}"
git archive HEAD | tar -x -C "${TARGET}"

# ===== STRIP PROPRIETARY MODULES =====

# Pro tier
rm -rf "${TARGET}/src/vinzy_engine/anomaly/"
rm -rf "${TARGET}/src/vinzy_engine/dashboard/"

# Enterprise tier
rm -rf "${TARGET}/src/vinzy_engine/audit/"
rm -rf "${TARGET}/src/vinzy_engine/provisioning/"
rm -rf "${TARGET}/src/vinzy_engine/tenants/"

# ===== STRIP TESTS FOR PROPRIETARY MODULES =====

# Unit tests - Pro
rm -f "${TARGET}/tests/unit/test_anomaly.py"

# Unit tests - Enterprise
rm -f "${TARGET}/tests/unit/test_audit.py"
rm -f "${TARGET}/tests/unit/test_provisioning.py"
rm -f "${TARGET}/tests/unit/test_tenants.py"

# Integration tests - Pro
rm -f "${TARGET}/tests/integration/test_anomaly_router.py"

# Integration tests - Enterprise
rm -f "${TARGET}/tests/integration/test_audit_router.py"
rm -f "${TARGET}/tests/integration/test_provisioning_pipeline.py"
rm -f "${TARGET}/tests/integration/test_tenant_router.py"

# Root-level tests - Pro
rm -f "${TARGET}/tests/test_dashboard.py"
rm -f "${TARGET}/tests/test_dashboard_auth.py"

# ===== CREATE STUB __init__.py FOR STRIPPED PACKAGES =====

STUB_CONTENT=$(cat << 'STUBEOF'
"""This module requires a commercial license.

Visit https://gozerai.com/pricing for Pro and Enterprise tier details.
Set VINZY_LICENSE_KEY to unlock licensed features.
"""

raise ImportError(
    f"{__name__} requires a commercial license. "
    "Visit https://gozerai.com/pricing for details."
)
STUBEOF
)

for pkg in anomaly dashboard audit provisioning tenants; do
    mkdir -p "${TARGET}/src/vinzy_engine/${pkg}"
    echo "${STUB_CONTENT}" > "${TARGET}/src/vinzy_engine/${pkg}/__init__.py"
done

# ===== PATCH app.py - remove stripped router imports and mounts =====

sed -i '/from vinzy_engine\.tenants\.router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/from vinzy_engine\.audit\.router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/from vinzy_engine\.anomaly\.router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/from vinzy_engine\.provisioning\.router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/from vinzy_engine\.dashboard\.router/d' "${TARGET}/src/vinzy_engine/app.py"

sed -i '/app\.include_router(tenant_router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/app\.include_router(audit_router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/app\.include_router(anomaly_router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/app\.include_router(provisioning_router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/app\.include_router(checkout_router/d' "${TARGET}/src/vinzy_engine/app.py"
sed -i '/app\.mount.*dashboard/d' "${TARGET}/src/vinzy_engine/app.py"

# ===== REPLACE deps.py - remove stripped service imports and singletons =====

python3 "$(dirname "$0")/write_deps.py" "${TARGET}/src/vinzy_engine/deps.py"

# ===== UPDATE docs/pricing - replace chrisarseno links with GozerAI =====

if [ -f "${TARGET}/docs/pricing/index.html" ]; then
    sed -i 's|github.com/chrisarseno/vinzy-engine|github.com/GozerAI/vinzy-engine|g' "${TARGET}/docs/pricing/index.html"
fi

# ===== UPDATE pyproject.toml - update URLs =====

sed -i 's|chrisarseno/vinzy-engine|GozerAI/vinzy-engine|g' "${TARGET}/pyproject.toml"

# ===== UPDATE COMMERCIAL-LICENSE.md if present =====

if [ -f "${TARGET}/COMMERCIAL-LICENSE.md" ]; then
    sed -i 's|github.com/chrisarseno|github.com/GozerAI|g' "${TARGET}/COMMERCIAL-LICENSE.md"
fi

# ===== UPDATE README =====

python3 "$(dirname "$0")/write_readme.py" "${TARGET}/README.md" vinzy-engine

echo ""
echo "=== Export complete: ${TARGET} ==="
echo ""
echo "Community-tier modules included:"
echo "  activation, keygen, licensing, usage, webhooks, common, client, cli"
echo ""
echo "Stripped (Pro/Enterprise/Private):"
echo "  anomaly, dashboard, audit, provisioning, tenants"
