"""Run migrations on the connection explicitly supplied by the application."""

from alembic import context
from sqlalchemy import Connection

from stridelog.db.models import Base

connection = context.config.attributes.get("connection")
if not isinstance(connection, Connection):
    raise RuntimeError("Run migrations through stridelog doctor --initialize.")
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
