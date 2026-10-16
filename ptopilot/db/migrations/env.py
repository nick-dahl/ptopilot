"""Alembic environment: runs migrations against DATABASE_URL, or a URL set on the config by tests."""

from logging.config import fileConfig

from alembic import context

from ptopilot.db.models import Base
from ptopilot.db.session import make_engine
from ptopilot.settings import Settings

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

url = config.get_main_option("sqlalchemy.url") or Settings.from_env().database_url

with make_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
