"""ORM 模型（T1.2），对应《需求说明书》第 6 章数据模型草案。"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

TSTZ = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- 状态/角色常量（DB 中用 String 存储，避免 PG enum 的迁移负担） ----

class UserRole:
    USER = "user"
    ADMIN = "admin"


class UserStatus:
    PENDING = "pending"    # 待邮箱验证
    ACTIVE = "active"
    DISABLED = "disabled"


class TaskStatus:
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    ARCHIVING = "ARCHIVING"
    ARCHIVE_FAILED = "ARCHIVE_FAILED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


TERMINAL_STATUSES = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)
ACTIVE_WORKSPACE_STATUSES = (
    TaskStatus.PREPARING,
    TaskStatus.RUNNING,
    TaskStatus.ARCHIVING,
    TaskStatus.ARCHIVE_FAILED,
)


class ArchiveStatus:
    PENDING = "PENDING"
    ARCHIVING = "ARCHIVING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WorkspaceStatus:
    READY = "READY"
    ERROR = "ERROR"
    SYNCING = "SYNCING"


class TokenType:
    VERIFY = "verify"
    RESET = "reset"


class NotificationType:
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=UserRole.USER)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.PENDING)
    workspace_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WorkspaceStatus.ERROR)
    workspace_error: Mapped[str | None] = mapped_column(Text)
    program_version: Mapped[str | None] = mapped_column(String(64))
    exe_sha256: Mapped[str | None] = mapped_column(String(64))
    dll_sha256: Mapped[str | None] = mapped_column(String(64))
    program_synced_at: Mapped[datetime | None] = mapped_column(TSTZ)
    program_sync_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, default=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(TSTZ)


class UserProgram(Base):
    __tablename__ = "user_programs"
    __table_args__ = (
        UniqueConstraint("user_id", "program_key", name="uq_user_programs_user_program"),
        Index("ix_user_programs_program_status", "program_key", "workspace_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    program_key: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WorkspaceStatus.ERROR)
    workspace_error: Mapped[str | None] = mapped_column(Text)
    program_version: Mapped[str | None] = mapped_column(String(64))
    exe_sha256: Mapped[str | None] = mapped_column(String(64))
    dll_sha256: Mapped[str | None] = mapped_column(String(64))
    runtime_file_hashes: Mapped[dict | None] = mapped_column(JSONB)
    program_synced_at: Mapped[datetime | None] = mapped_column(TSTZ)
    program_sync_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # verify / reset
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ParamTemplate(Base):
    __tablename__ = "param_templates"
    __table_args__ = (
        UniqueConstraint("user_id", "program_key", "name", name="uq_param_templates_user_program_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    program_key: Mapped[str] = mapped_column(String(64), nullable=False, default="dcr_3d")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parameter_schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="dcr-model-v1")
    created_at: Mapped[datetime] = mapped_column(TSTZ, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, default=utcnow, onupdate=utcnow, nullable=False)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_queued_at", "status", "queued_at"),
        Index("ix_tasks_user_queued_at", "user_id", "queued_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TaskStatus.QUEUED)
    program_key: Mapped[str] = mapped_column(String(64), nullable=False, default="dcr_3d")
    source_type: Mapped[str | None] = mapped_column(String(32))
    stdin_choice: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)  # 参数快照
    parameter_schema_version: Mapped[str | None] = mapped_column(String(32))
    input_filename: Mapped[str | None] = mapped_column(String(255))  # 原始 mesh 文件名
    parameter_filename: Mapped[str | None] = mapped_column(String(255))
    parameter_original_filename: Mapped[str | None] = mapped_column(String(255))
    parameter_sha256: Mapped[str | None] = mapped_column(String(64))
    runtime_file_hashes: Mapped[dict | None] = mapped_column(JSONB)
    storage_dir: Mapped[str | None] = mapped_column(String(512))  # 旧任务目录（迁移兼容）
    staging_dir: Mapped[str | None] = mapped_column(String(512))
    workspace_was_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archive_dir: Mapped[str | None] = mapped_column(String(512))
    archive_version: Mapped[str | None] = mapped_column(String(96))
    archive_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ArchiveStatus.PENDING)
    terminal_status: Mapped[str | None] = mapped_column(String(16))
    archive_error: Mapped[str | None] = mapped_column(Text)
    archive_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archive_retry_at: Mapped[datetime | None] = mapped_column(TSTZ)
    archived_at: Mapped[datetime | None] = mapped_column(TSTZ)
    program_version: Mapped[str | None] = mapped_column(String(64))
    exe_sha256: Mapped[str | None] = mapped_column(String(64))
    dll_sha256: Mapped[str | None] = mapped_column(String(64))
    result_file_count: Mapped[int | None] = mapped_column(Integer)
    result_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    cleanup_error: Mapped[str | None] = mapped_column(Text)
    cleanup_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleanup_retry_at: Mapped[datetime | None] = mapped_column(TSTZ)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(TSTZ, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TSTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TSTZ)
    duration_sec: Mapped[float | None] = mapped_column(Numeric)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


# 系统配置默认值（T1.2 seed；含义见需求说明书 FR-ADMIN-06）
DEFAULT_CONFIG = {
    "max_concurrent_tasks": "50",
    "max_running_per_user": "1",
    "max_queued_per_user": "3",
    "task_timeout_minutes": "60",
    "retention_days": "30",
    "max_upload_mb": "200",
    "min_free_disk_mb": "1024",
}


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column("read", Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TSTZ, default=utcnow, nullable=False)
