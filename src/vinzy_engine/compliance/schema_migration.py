"""Database schema migration auto-generation.

Inspects SQLAlchemy model metadata and produces migration plans by
comparing current model state against a stored schema snapshot.
Generates Alembic-compatible migration operations.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MigrationOpType(str, Enum):
    ADD_TABLE = "add_table"
    DROP_TABLE = "drop_table"
    ADD_COLUMN = "add_column"
    DROP_COLUMN = "drop_column"
    ALTER_COLUMN = "alter_column"
    ADD_INDEX = "add_index"
    DROP_INDEX = "drop_index"


@dataclass
class MigrationOp:
    """A single migration operation."""

    op_type: MigrationOpType
    table_name: str
    column_name: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_type": self.op_type.value,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "details": self.details,
        }

    def to_alembic_line(self) -> str:
        """Generate an Alembic-style Python line for this operation."""
        if self.op_type == MigrationOpType.ADD_TABLE:
            cols = self.details.get("columns", [])
            col_strs = []
            for c in cols:
                col_strs.append(f"sa.Column('{c['name']}', sa.{c['type']}())")
            cols_joined = ", ".join(col_strs)
            return f"op.create_table('{self.table_name}', {cols_joined})"
        elif self.op_type == MigrationOpType.DROP_TABLE:
            return f"op.drop_table('{self.table_name}')"
        elif self.op_type == MigrationOpType.ADD_COLUMN:
            col_type = self.details.get("type", "String")
            nullable = self.details.get("nullable", True)
            return (
                f"op.add_column('{self.table_name}', "
                f"sa.Column('{self.column_name}', sa.{col_type}(), nullable={nullable}))"
            )
        elif self.op_type == MigrationOpType.DROP_COLUMN:
            return f"op.drop_column('{self.table_name}', '{self.column_name}')"
        elif self.op_type == MigrationOpType.ALTER_COLUMN:
            new_type = self.details.get("new_type", "String")
            return (
                f"op.alter_column('{self.table_name}', '{self.column_name}', "
                f"type_=sa.{new_type}())"
            )
        elif self.op_type == MigrationOpType.ADD_INDEX:
            columns = self.details.get("columns", [self.column_name or ""])
            idx_name = self.details.get("index_name", f"ix_{self.table_name}_{'_'.join(columns)}")
            return f"op.create_index('{idx_name}', '{self.table_name}', {columns!r})"
        elif self.op_type == MigrationOpType.DROP_INDEX:
            idx_name = self.details.get("index_name", "")
            return f"op.drop_index('{idx_name}', table_name='{self.table_name}')"
        return f"# Unknown op: {self.op_type.value}"


@dataclass
class SchemaSnapshot:
    """A snapshot of the database schema at a point in time."""

    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    captured_at: float = field(default_factory=time.monotonic)
    checksum: str = ""

    def compute_checksum(self) -> str:
        """Compute a stable hash of the schema for change detection."""
        raw = str(sorted(self.tables.items()))
        self.checksum = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self.checksum


@dataclass
class MigrationPlan:
    """A complete migration plan."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    operations: list[MigrationOp] = field(default_factory=list)
    from_checksum: str = ""
    to_checksum: str = ""
    generated_at: float = field(default_factory=time.monotonic)

    @property
    def is_empty(self) -> bool:
        return len(self.operations) == 0

    def to_alembic_script(self, revision: str = "auto") -> str:
        """Generate an Alembic migration script body."""
        upgrade_lines = []
        downgrade_lines = []

        for op in self.operations:
            upgrade_lines.append(f"    {op.to_alembic_line()}")

        for op in reversed(self.operations):
            inverse = self._inverse_op(op)
            if inverse:
                downgrade_lines.append(f"    {inverse.to_alembic_line()}")

        up_body = "\n".join(upgrade_lines) if upgrade_lines else "    pass"
        down_body = "\n".join(downgrade_lines) if downgrade_lines else "    pass"

        return (
            f'"""Auto-generated migration {revision}."""\n\n'
            f"import sqlalchemy as sa\n"
            f"from alembic import op\n\n"
            f'revision = "{revision}"\n'
            f'down_revision = None\n\n\n'
            f"def upgrade():\n{up_body}\n\n\n"
            f"def downgrade():\n{down_body}\n"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operations": [o.to_dict() for o in self.operations],
            "operation_count": len(self.operations),
            "from_checksum": self.from_checksum,
            "to_checksum": self.to_checksum,
            "generated_at": self.generated_at,
        }

    @staticmethod
    def _inverse_op(op: MigrationOp) -> Optional[MigrationOp]:
        """Generate the inverse operation for downgrade."""
        inverse_map = {
            MigrationOpType.ADD_TABLE: MigrationOpType.DROP_TABLE,
            MigrationOpType.DROP_TABLE: MigrationOpType.ADD_TABLE,
            MigrationOpType.ADD_COLUMN: MigrationOpType.DROP_COLUMN,
            MigrationOpType.DROP_COLUMN: MigrationOpType.ADD_COLUMN,
            MigrationOpType.ADD_INDEX: MigrationOpType.DROP_INDEX,
            MigrationOpType.DROP_INDEX: MigrationOpType.ADD_INDEX,
        }
        inv_type = inverse_map.get(op.op_type)
        if inv_type is None:
            return None
        return MigrationOp(
            op_type=inv_type,
            table_name=op.table_name,
            column_name=op.column_name,
            details=op.details,
        )


class SchemaMigrationGenerator:
    """Compares schema snapshots and generates migration plans.

    Usage:
        gen = SchemaMigrationGenerator()

        # Capture current state from model metadata
        old_snap = gen.capture_from_metadata(metadata_old)
        new_snap = gen.capture_from_metadata(metadata_new)

        # Or build snapshots manually
        snap = gen.create_snapshot({"users": {"columns": {...}}})

        plan = gen.diff(old_snap, new_snap)
        script = plan.to_alembic_script("001_initial")
    """

    def __init__(self) -> None:
        self._history: list[MigrationPlan] = []

    def create_snapshot(self, tables: dict[str, dict[str, Any]]) -> SchemaSnapshot:
        """Create a schema snapshot from a table definition dict.

        tables format: {
            "table_name": {
                "columns": {
                    "col_name": {"type": "String", "nullable": True, ...},
                },
                "indexes": [{"name": "ix_...", "columns": ["col1"]}],
            },
        }
        """
        snap = SchemaSnapshot(tables=tables)
        snap.compute_checksum()
        return snap

    def capture_from_metadata(self, metadata: Any) -> SchemaSnapshot:
        """Capture a snapshot from SQLAlchemy MetaData object."""
        tables: dict[str, dict[str, Any]] = {}
        for table in metadata.sorted_tables:
            columns = {}
            for col in table.columns:
                columns[col.name] = {
                    "type": type(col.type).__name__,
                    "nullable": col.nullable,
                    "primary_key": col.primary_key,
                    "index": col.index if hasattr(col, "index") else False,
                }
            indexes = []
            for idx in table.indexes:
                indexes.append({
                    "name": idx.name,
                    "columns": [c.name for c in idx.columns],
                    "unique": idx.unique,
                })
            tables[table.name] = {"columns": columns, "indexes": indexes}

        snap = SchemaSnapshot(tables=tables)
        snap.compute_checksum()
        return snap

    def diff(self, old: SchemaSnapshot, new: SchemaSnapshot) -> MigrationPlan:
        """Compute the migration plan to go from old to new."""
        plan = MigrationPlan(
            from_checksum=old.checksum,
            to_checksum=new.checksum,
        )

        old_tables = set(old.tables.keys())
        new_tables = set(new.tables.keys())

        # New tables
        for tname in sorted(new_tables - old_tables):
            cols = []
            for cname, cinfo in new.tables[tname].get("columns", {}).items():
                cols.append({"name": cname, "type": cinfo.get("type", "String")})
            plan.operations.append(MigrationOp(
                op_type=MigrationOpType.ADD_TABLE,
                table_name=tname,
                details={"columns": cols},
            ))

        # Dropped tables
        for tname in sorted(old_tables - new_tables):
            plan.operations.append(MigrationOp(
                op_type=MigrationOpType.DROP_TABLE,
                table_name=tname,
            ))

        # Modified tables (columns)
        for tname in sorted(old_tables & new_tables):
            old_cols = set((old.tables[tname].get("columns") or {}).keys())
            new_cols = set((new.tables[tname].get("columns") or {}).keys())

            for cname in sorted(new_cols - old_cols):
                cinfo = new.tables[tname]["columns"][cname]
                plan.operations.append(MigrationOp(
                    op_type=MigrationOpType.ADD_COLUMN,
                    table_name=tname,
                    column_name=cname,
                    details={
                        "type": cinfo.get("type", "String"),
                        "nullable": cinfo.get("nullable", True),
                    },
                ))

            for cname in sorted(old_cols - new_cols):
                plan.operations.append(MigrationOp(
                    op_type=MigrationOpType.DROP_COLUMN,
                    table_name=tname,
                    column_name=cname,
                ))

            # Type changes
            for cname in sorted(old_cols & new_cols):
                old_type = (old.tables[tname].get("columns") or {}).get(cname, {}).get("type")
                new_type = (new.tables[tname].get("columns") or {}).get(cname, {}).get("type")
                if old_type != new_type and old_type is not None and new_type is not None:
                    plan.operations.append(MigrationOp(
                        op_type=MigrationOpType.ALTER_COLUMN,
                        table_name=tname,
                        column_name=cname,
                        details={"old_type": old_type, "new_type": new_type},
                    ))

        self._history.append(plan)
        return plan

    def get_history(self, limit: int = 50) -> list[MigrationPlan]:
        return self._history[-limit:]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_migrations_generated": len(self._history),
        }

    def clear(self) -> None:
        self._history.clear()
