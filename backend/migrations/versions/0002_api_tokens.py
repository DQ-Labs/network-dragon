"""Frozen read-only API token table; stores SHA-256 digests, never raw tokens."""

from alembic import op

revision = "0002"
down_revision = "0001"

STATEMENTS = [
    "CREATE TABLE api_tokens (\n\ttoken_hash VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tlast_used_at FLOAT, \n\texpires_at FLOAT, \n\tPRIMARY KEY (token_hash), \n\tUNIQUE (name)\n)",
]


def upgrade():
    for statement in STATEMENTS:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Restore a verified backup; destructive downgrade is unsupported")
