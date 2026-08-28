"""Pydantic 请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- 认证与用户 ----

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    status: str
    workspace_status: str
    workspace_error: str | None
    program_version: str | None
    exe_sha256: str | None
    dll_sha256: str | None
    program_synced_at: datetime | None
    program_sync_pending: bool
    created_at: datetime
    last_login_at: datetime | None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=72)


class UpdateMeRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_]+$")


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)


# ---- 参数模板 ----

class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    program_key: str = Field(default="dcr_3d", pattern=r"^dcr_3d$")
    params: dict


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    program_key: str | None = Field(default=None, pattern=r"^dcr_3d$")
    params: dict | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    program_key: str
    params: dict
    created_at: datetime
    updated_at: datetime


# ---- 任务 ----

class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    program_key: str
    source_type: str | None
    stdin_choice: int | None
    params: dict
    input_filename: str | None
    parameter_filename: str | None
    parameter_original_filename: str | None
    parameter_sha256: str | None
    runtime_file_hashes: dict | None
    workspace_was_used: bool
    archive_status: str
    terminal_status: str | None
    archive_version: str | None
    archive_error: str | None
    archive_retry_count: int
    archive_retry_at: datetime | None
    archived_at: datetime | None
    program_version: str | None
    exe_sha256: str | None
    dll_sha256: str | None
    result_file_count: int | None
    result_size_bytes: int | None
    cleanup_error: str | None
    cleanup_retry_count: int
    cleanup_retry_at: datetime | None
    exit_code: int | None
    error_message: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_sec: float | None


class TaskListResponse(BaseModel):
    total: int
    items: list[TaskResponse]


class TaskDetailResponse(TaskResponse):
    queue_position: int | None = None  # QUEUED 时：前面还有多少任务


# ---- 站内通知 ----

class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int | None
    type: str
    message: str
    read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    total: int
    unread_count: int
    items: list[NotificationResponse]


class MarkReadRequest(BaseModel):
    ids: list[int] | None = None  # None 表示全部标记已读


# ---- 管理后台 ----

class DashboardResponse(BaseModel):
    total_users: int
    active_users: int        # 有 RUNNING 任务的去重用户数
    running_tasks: int
    queued_tasks: int
    cpu_percent: float
    memory_percent: float
    disk_percent: float


class AdminTaskItem(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    program_key: str
    source_type: str | None
    stdin_choice: int | None
    input_filename: str | None
    parameter_filename: str | None
    queued_at: datetime
    started_at: datetime | None


class UserListResponse(BaseModel):
    total: int
    items: list[UserResponse]


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


class AdminUserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailStr | None = None
    role: str | None = Field(default=None, pattern=r"^(user|admin)$")


class ResetPasswordResponse(BaseModel):
    temporary_password: str


class ConfigResponse(BaseModel):
    config: dict[str, str]


class ConfigUpdateRequest(BaseModel):
    config: dict[str, str]


class AuditLogResponse(BaseModel):
    id: int
    admin_id: int | None
    admin_username: str | None
    action: str
    target: str | None
    detail: dict | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogResponse]
