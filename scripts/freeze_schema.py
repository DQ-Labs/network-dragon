"""One-time initial migration generator; never rerun after releasing schema 0001."""
from pathlib import Path

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from network_dragon.persistence.models import Base

statements = []
for table in Base.metadata.sorted_tables:
    statements.append(str(CreateTable(table).compile(dialect=sqlite.dialect())).strip())
    statements.extend(str(CreateIndex(index).compile(dialect=sqlite.dialect())).strip() for index in sorted(table.indexes, key=lambda i: i.name))
source = '''"""Frozen initial schema: independent of future ORM changes."""
from alembic import op

revision = "0001"
down_revision = None

STATEMENTS = ''' + repr(statements) + '''


def upgrade():
    for statement in STATEMENTS:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Restore a verified backup; destructive downgrade is unsupported")
'''
Path('backend/migrations/versions/0001_initial.py').write_text(source)
