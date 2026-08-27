"""环境配置（研发任务分解 T1.1）。

所有配置项均可通过环境变量或仓库根目录的 .env 文件覆盖。
"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/fortran_platform"

    # 文件存储根目录（每用户固定工作区 storage/{user_id}/）
    storage_root: Path = REPO_ROOT / "storage"

    # 计算执行模式：mock 使用固定路径版 Python Mock；dcr3d 使用用户根目录 DCR_3D.exe。
    execution_mode: str = "mock"

    # 正式程序统一模板目录，包含 DCR_3D.exe / libiomp5md.dll / program-manifest.json。
    fortran_program_template_dir: Path = REPO_ROOT / "program_template"

    # 兼容旧部署的命令模板；仅旧版测试/迁移期间使用，新执行链路不得在 dcr3d 模式调用。
    fortran_command: str = f'"{REPO_ROOT / ".venv" / "Scripts" / "python.exe"}" "{REPO_ROOT / "mock" / "mock_program.py"}" {{params}} {{data}}'

    # 固定路径版 Mock 程序；runner 在用户根目录中无参数启动。
    mock_dcr3d_command: str = f'"{REPO_ROOT / ".venv" / "Scripts" / "python.exe"}" "{REPO_ROOT / "mock" / "mock_dcr3d.py"}"'

    # Forward_data ZIP 缓存目录；历史清理时同步清理。
    result_zip_cache_root: Path = REPO_ROOT / "storage" / ".zip-cache"

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

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mock", "dcr3d"}:
            raise ValueError("execution_mode 必须为 mock 或 dcr3d")
        return normalized


settings = Settings()
