"""Alembic environment configuration for Vinzy-Engine."""

import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure src/ is on sys.path for editable installs
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vinzy_engine.common.models import Base

# Import all models so they register with Base.metadata
import vinzy_engine.tenants.models  # noqa: F401
import vinzy_engine.licensing.models  # noqa: F401
import vinzy_engine.activation.models  # noqa: F401
import vinzy_engine.usage.models  # noqa: F401
import vinzy_engine.audit.models  # noqa: F401
import vinzy_engine.anomaly.models  # noqa: F401
import vinzy_engine.webhooks.models  # noqa: F401

config = context.config

# Allow CLI override: alembic -x sqlalchemy.url=... upgrade head
cmd_url = context.get_x_argument(as_dictionary=True).get("sqlalchemy.url")
if cmd_url:
    config.set_main_option("sqlalchemy.url", cmd_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
