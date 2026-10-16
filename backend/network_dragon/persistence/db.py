from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def engine_for(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine


@contextmanager
def transaction(engine):
    with Session(engine) as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def migrate(engine):
    from alembic import command
    from alembic.config import Config

    config = Config()
    migrations = Path(__file__).parents[2] / "migrations"
    if not migrations.exists():
        migrations = Path(__file__).parents[1] / "migrations"
    config.set_main_option("script_location", str(migrations))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
