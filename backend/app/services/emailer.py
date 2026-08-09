"""邮件发送（T2.1/T2.3）。

SMTP 未配置时将邮件内容写入后端日志，便于开发环境联调。
"""
import logging
from email.message import EmailMessage

import aiosmtplib

from ..config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        logger.warning("SMTP 未配置，邮件仅记录日志 → to=%s subject=%s body=%s", to, subject, body)
        return

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body, "utf-8")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        use_tls=settings.smtp_use_tls,
    )


async def send_verification_email(to: str, token: str) -> None:
    link = f"{settings.app_base_url}/verify?token={token}"
    await send_email(
        to,
        "【Fortran 计算平台】邮箱验证",
        f"您好，\n\n请点击以下链接完成邮箱验证（24 小时内有效）：\n{link}\n\n如非本人操作请忽略本邮件。\n",
    )


async def send_password_reset_email(to: str, token: str) -> None:
    link = f"{settings.app_base_url}/reset-password?token={token}"
    await send_email(
        to,
        "【Fortran 计算平台】重置密码",
        f"您好，\n\n请点击以下链接重置密码（1 小时内有效）：\n{link}\n\n如非本人操作请忽略本邮件。\n",
    )
