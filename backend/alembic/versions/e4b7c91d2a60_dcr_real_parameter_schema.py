"""DCR real parameter schema version markers.

Revision ID: e4b7c91d2a60
Revises: c7a4e2f19b63
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b7c91d2a60"
down_revision = "c7a4e2f19b63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "param_templates",
        sa.Column(
            "parameter_schema_version", sa.String(length=32),
            nullable=False, server_default="legacy-placeholder-v1",
        ),
    )
    op.alter_column("param_templates", "parameter_schema_version", server_default=None)
    op.add_column(
        "tasks",
        sa.Column("parameter_schema_version", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE tasks SET parameter_schema_version = 'legacy-placeholder-v1' "
        "WHERE program_key = 'dcr_3d'"
    )


def downgrade() -> None:
    op.drop_column("tasks", "parameter_schema_version")
    op.drop_column("param_templates", "parameter_schema_version")
