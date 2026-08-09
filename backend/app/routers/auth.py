"""注册、邮箱验证、登录、密码找回（T2.1~T2.3）。"""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import EmailToken, TokenType, User, UserRole, UserStatus, utcnow
from ..schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from ..security import create_access_token, hash_password, verify_password
from ..services.emailer import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

VERIFY_TOKEN_HOURS = 24
RESET_TOKEN_HOURS = 1


def _new_token(session: AsyncSession, user_id: int, type_: str, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    session.add(EmailToken(
        user_id=user_id, type=type_, token=token,
        expires_at=utcnow() + timedelta(hours=hours),
    ))
    return token


def _validate_token(rec: EmailToken | None) -> EmailToken:
    if rec is None or rec.used or rec.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "链接无效或已过期")
    return rec


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(
        select(User).where(or_(User.username == body.username, User.email == body.email))
    )
    if existing is not None:
        # 同一账号仍处于待验证状态：视为重新注册，重发验证邮件
        if (existing.status == UserStatus.PENDING
                and existing.username == body.username and existing.email == body.email):
            existing.password_hash = hash_password(body.password)
            token = _new_token(session, existing.id, TokenType.VERIFY, VERIFY_TOKEN_HOURS)
            await session.commit()
            await send_verification_email(existing.email, token)
            return {"detail": "验证邮件已重新发送，请查收"}
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名或邮箱已被注册")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=UserRole.USER,
        status=UserStatus.PENDING,
    )
    session.add(user)
    await session.flush()
    token = _new_token(session, user.id, TokenType.VERIFY, VERIFY_TOKEN_HOURS)
    await session.commit()
    await send_verification_email(user.email, token)
    return {"detail": "注册成功，验证邮件已发送，请查收"}


@router.get("/verify")
async def verify_email(token: str, session: AsyncSession = Depends(get_session)):
    rec = await session.scalar(
        select(EmailToken).where(EmailToken.token == token, EmailToken.type == TokenType.VERIFY)
    )
    _validate_token(rec)
    rec.used = True
    user = await session.get(User, rec.user_id)
    user.status = UserStatus.ACTIVE
    await session.commit()
    return {"detail": "邮箱验证成功，请登录"}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if user.status == UserStatus.PENDING:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号未激活，请先完成邮箱验证")
    if user.status == UserStatus.DISABLED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用，请联系管理员")
    user.last_login_at = utcnow()
    await session.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is not None and user.status == UserStatus.ACTIVE:
        token = _new_token(session, user.id, TokenType.RESET, RESET_TOKEN_HOURS)
        await session.commit()
        await send_password_reset_email(user.email, token)
    # 不泄露邮箱是否已注册
    return {"detail": "如果该邮箱已注册，重置密码邮件已发送"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, session: AsyncSession = Depends(get_session)):
    rec = await session.scalar(
        select(EmailToken).where(EmailToken.token == body.token, EmailToken.type == TokenType.RESET)
    )
    _validate_token(rec)
    rec.used = True
    user = await session.get(User, rec.user_id)
    user.password_hash = hash_password(body.new_password)
    await session.commit()
    return {"detail": "密码重置成功，请使用新密码登录"}


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
