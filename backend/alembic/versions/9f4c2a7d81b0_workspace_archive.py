"""user workspace and task archive fields

Revision ID: 9f4c2a7d81b0
Revises: 43e7bf20f8d5
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f4c2a7d81b0"
down_revision: Union[str, Sequence[str], None] = "43e7bf20f8d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "workspace_status", sa.String(length=16), nullable=False,
        server_default="ERROR"))
    op.add_column("users", sa.Column("workspace_error", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("program_version", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("exe_sha256", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("dll_sha256", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column(
        "program_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column(
        "program_sync_pending", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column("tasks", sa.Column("staging_dir", sa.String(length=512), nullable=True))
    op.add_column("tasks", sa.Column(
        "workspace_was_used", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tasks", sa.Column("archive_dir", sa.String(length=512), nullable=True))
    op.add_column("tasks", sa.Column("archive_version", sa.String(length=96), nullable=True))
    op.add_column("tasks", sa.Column(
        "archive_status", sa.String(length=16), nullable=False,
        server_default="PENDING"))
    op.add_column("tasks", sa.Column("terminal_status", sa.String(length=16), nullable=True))
    op.add_column("tasks", sa.Column("archive_error", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column(
        "archive_retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column(
        "archive_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column(
        "archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("program_version", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("exe_sha256", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("dll_sha256", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("result_file_count", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("result_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("tasks", sa.Column("cleanup_error", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column(
        "cleanup_retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column(
        "cleanup_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_archive_status", "tasks", ["archive_status"], unique=False)
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"], unique=False)

    # 单用户固定工作区不允许并行运行。
    op.execute("""
        INSERT INTO system_config (key, value)
        VALUES ('max_running_per_user', '1')
        ON CONFLICT (key) DO UPDATE SET value = '1'
    """)


def downgrade() -> None:
    op.execute("UPDATE system_config SET value = '3' WHERE key = 'max_running_per_user'")

    op.drop_index("ix_tasks_user_status", table_name="tasks")
    op.drop_index("ix_tasks_archive_status", table_name="tasks")
    for column in (
        "cleanup_retry_at", "cleanup_retry_count", "cleanup_error",
        "result_size_bytes", "result_file_count", "dll_sha256", "exe_sha256",
        "program_version", "archived_at", "archive_retry_at", "archive_retry_count",
        "archive_error", "terminal_status", "archive_status", "archive_version", "archive_dir",
        "workspace_was_used", "staging_dir",
    ):
        op.drop_column("tasks", column)

    for column in (
        "program_sync_pending", "program_synced_at", "dll_sha256", "exe_sha256", "program_version",
        "workspace_error", "workspace_status",
    ):
        op.drop_column("users", column)
