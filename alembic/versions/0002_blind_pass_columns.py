"""Add blind_pass_token and client_key_shard columns to licenses table.

Revision ID: 0002_blind_pass_columns
Revises: 0001_initial_schema
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_blind_pass_columns"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("licenses", sa.Column("blind_pass_token", sa.String(512), nullable=True))
    op.add_column("licenses", sa.Column("client_key_shard", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("licenses", "client_key_shard")
    op.drop_column("licenses", "blind_pass_token")
