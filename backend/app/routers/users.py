"""账户自助管理（T2.4）。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas import ChangePasswordRequest, UpdateMeRequest, UserResponse
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/users", tags=["users"])


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateMeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.username != user.username:
        exists = await session.scalar(select(User.id).where(User.username == body.username))
        if exists is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用")
        user.username = body.username
        await session.commit()
    return user


@router.put("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")
    user.password_hash = hash_password(body.new_password)
    await session.commit()
    return {"detail": "密码修改成功"}
