"""multi scientific programs and per-user installations

Revision ID: c7a4e2f19b63
Revises: 9f4c2a7d81b0
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c7a4e2f19b63"
down_revision: Union[str, Sequence[str], None] = "9f4c2a7d81b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_programs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("program_key", sa.String(length=64), nullable=False),
        sa.Column("workspace_status", sa.String(length=16), nullable=False, server_default="ERROR"),
        sa.Column("workspace_error", sa.Text(), nullable=True),
        sa.Column("program_version", sa.String(length=64), nullable=True),
        sa.Column("exe_sha256", sa.String(length=64), nullable=True),
        sa.Column("dll_sha256", sa.String(length=64), nullable=True),
        sa.Column("runtime_file_hashes", postgresql.JSONB(), nullable=True),
        sa.Column("program_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("program_sync_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("user_id", "program_key", name="uq_user_programs_user_program"),
        sa.CheckConstraint(
            "program_key IN ('dcr_3d','be_fetd','fdem3d_frequency_domain')",
            name="ck_user_programs_program_key",
        ),
    )
    op.create_index(
        "ix_user_programs_program_status", "user_programs",
        ["program_key", "workspace_status"], unique=False)
    op.execute("""
        INSERT INTO user_programs (
            user_id, program_key, workspace_status, workspace_error,
            program_version, exe_sha256, dll_sha256, program_synced_at,
            program_sync_pending
        )
        SELECT id, 'dcr_3d', workspace_status, workspace_error,
               program_version, exe_sha256, dll_sha256, program_synced_at,
               program_sync_pending
        FROM users
    """)

    op.add_column("param_templates", sa.Column(
        "program_key", sa.String(length=64), nullable=False, server_default="dcr_3d"))
    op.create_unique_constraint(
        "uq_param_templates_user_program_name", "param_templates",
        ["user_id", "program_key", "name"])

    op.add_column("tasks", sa.Column(
        "program_key", sa.String(length=64), nullable=False, server_default="dcr_3d"))
    op.add_column("tasks", sa.Column("source_type", sa.String(length=32), nullable=True))
    op.add_column("tasks", sa.Column("stdin_choice", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("parameter_filename", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("parameter_original_filename", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("parameter_sha256", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("runtime_file_hashes", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_tasks_program_key", "tasks",
        "program_key IN ('dcr_3d','be_fetd','fdem3d_frequency_domain')")
    op.create_check_constraint(
        "ck_tasks_program_input", "tasks",
        "(program_key = 'dcr_3d' AND source_type IS NULL AND stdin_choice IS NULL) OR "
        "(program_key IN ('be_fetd','fdem3d_frequency_domain') AND "
        "((source_type = 'grounded_wire' AND stdin_choice = 1) OR "
        "(source_type = 'loop' AND stdin_choice = 2)))")
    op.create_index("ix_tasks_program_status", "tasks", ["program_key", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_program_status", table_name="tasks")
    op.drop_constraint("ck_tasks_program_input", "tasks", type_="check")
    op.drop_constraint("ck_tasks_program_key", "tasks", type_="check")
    for column in (
        "runtime_file_hashes", "parameter_sha256", "parameter_original_filename",
        "parameter_filename", "stdin_choice", "source_type", "program_key",
    ):
        op.drop_column("tasks", column)

    op.drop_constraint(
        "uq_param_templates_user_program_name", "param_templates", type_="unique")
    op.drop_column("param_templates", "program_key")

    op.drop_index("ix_user_programs_program_status", table_name="user_programs")
    op.drop_table("user_programs")
