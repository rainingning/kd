"""环境配置（研发任务分解 T1.1）。

所有配置项均可通过环境变量或仓库根目录的 .env 文件覆盖。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/fortran_platform"

    # 文件存储根目录（任务文件按 storage/{user_id}/{task_id}/ 组织）
    storage_root: Path = REPO_ROOT / "storage"

    # 计算程序命令模板，{params} / {data} 为占位符。
    # 生产环境示例: C:/lab/program.exe {params} {data}
    fortran_command: str = f'"{REPO_ROOT / ".venv" / "Scripts" / "python.exe"}" "{REPO_ROOT / "mock" / "mock_program.py"}" {{params}} {{data}}'

    # JWT
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_expire_hours: int = 24

    # SMTP（邮箱验证 / 密码找回）
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # 前端地址，用于拼接邮件中的验证/重置链接
    app_base_url: str = "http://localhost:5173"


settings = Settings()
