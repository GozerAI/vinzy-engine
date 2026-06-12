"""Add covering index for license key lookups during activation checks.

Index on (product_code via product_id, key_hash, status) avoids full table scans.
Also adds composite index on (key_hash, is_deleted) for soft-delete-aware lookups.

Revision ID: 0003_covering_index_license_lookup
Revises: 0002_blind_pass_columns
Create Date: 2026-03-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_covering_index_license_lookup"
down_revision: Union[str, None] = "0002_blind_pass_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Covering index for activation checks: product lookup + key validation + status filter
    op.create_index(
        "ix_licenses_product_keyhash_status",
        "licenses",
        ["product_id", "key_hash", "status"],
    )
    # Composite index for soft-delete-aware key lookups
    op.create_index(
        "ix_licenses_keyhash_deleted",
        "licenses",
        ["key_hash", "is_deleted"],
    )
    # Index for background expiration processing
    op.create_index(
        "ix_licenses_status_expires",
        "licenses",
        ["status", "expires_at"],
    )
    # Index for hard-delete cleanup
    op.create_index(
        "ix_licenses_deleted_at",
        "licenses",
        ["is_deleted", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_licenses_deleted_at", table_name="licenses")
    op.drop_index("ix_licenses_status_expires", table_name="licenses")
    op.drop_index("ix_licenses_keyhash_deleted", table_name="licenses")
    op.drop_index("ix_licenses_product_keyhash_status", table_name="licenses")
