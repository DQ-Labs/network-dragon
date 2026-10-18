"""Nullable MAC vendor label on devices, as reported by Nmap's OUI lookup."""

from alembic import op

revision = "0003"
down_revision = "0002"

STATEMENTS = ["ALTER TABLE devices ADD COLUMN vendor VARCHAR"]


def upgrade():
    for statement in STATEMENTS:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Restore a verified backup; destructive downgrade is unsupported")
