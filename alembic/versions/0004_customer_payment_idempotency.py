"""Add payment_provider and payment_id columns to customers for webhook idempotency.

Extracts payment info from JSON metadata into dedicated indexed columns so duplicate
Stripe/Polar webhooks can be detected before creating duplicate customers/licenses.

Revision ID: 0004_customer_payment_idempotency
Revises: 0003_covering_index_license_lookup
Create Date: 2026-03-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_customer_payment_idempotency"
down_revision: Union[str, None] = "0003_covering_index_license_lookup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add dedicated columns for payment tracking
    op.add_column("customers", sa.Column("payment_provider", sa.String(50), server_default="", nullable=False))
    op.add_column("customers", sa.Column("payment_id", sa.String(255), server_default="", nullable=False))

    # Backfill from JSON metadata where available (SQLite syntax)
    op.execute(
        "UPDATE customers SET "
        "payment_provider = COALESCE(json_extract(metadata, '$.payment_provider'), ''), "
        "payment_id = COALESCE(json_extract(metadata, '$.payment_id'), '') "
        "WHERE json_extract(metadata, '$.payment_id') IS NOT NULL "
        "AND json_extract(metadata, '$.payment_id') != ''"
    )

    # Create partial unique index: only enforce when payment_id is non-empty
    op.create_index(
        "uq_customer_payment_idempotency",
        "customers",
        ["payment_provider", "payment_id"],
        unique=True,
        sqlite_where=sa.text("payment_id != ''"),
        postgresql_where=sa.text("payment_id != ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_customer_payment_idempotency", table_name="customers")
    op.drop_column("customers", "payment_id")
    op.drop_column("customers", "payment_provider")
