"""Alembic uses DATABASE_URL, or an explicit connection supplied by tests."""

from alembic import context

from backend.app.persistence.database import PersistenceSettings, create_database_engine
from backend.app.persistence.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=PersistenceSettings.from_env().database_url,
                      target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        run(connection)
    else:
        engine = create_database_engine(PersistenceSettings.from_env())
        try:
            with engine.connect() as connection:
                run(connection)
        finally:
            engine.dispose()
