"""参数模板 CRUD（T3.2，FR-PARAM-04）。"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import ParamTemplate, User
from ..param_schema import SCHEMA_VERSION, ParamValidationError, validate_params
from ..schemas import TemplateCreate, TemplateResponse, TemplateUpdate
from ..services.programs import DCR_3D

router = APIRouter(prefix="/api/templates", tags=["templates"])


async def _get_own(session: AsyncSession, template_id: int, user_id: int) -> ParamTemplate:
    tpl = await session.get(ParamTemplate, template_id)
    if tpl is None or tpl.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    return tpl


async def _check_name_unique(
    session: AsyncSession, user_id: int, program_key: str, name: str,
    exclude_id: int | None = None,
):
    stmt = select(ParamTemplate.id).where(
        ParamTemplate.user_id == user_id,
        ParamTemplate.program_key == program_key,
        ParamTemplate.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(ParamTemplate.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名模板已存在")


def _validate_or_422(params: dict) -> dict:
    try:
        return validate_params(params)
    except ParamValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=e.errors)


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    program_key: str = Query(default=DCR_3D),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if program_key != DCR_3D:
        return []
    rows = await session.scalars(
        select(ParamTemplate)
        .where(
            ParamTemplate.user_id == user.id,
            ParamTemplate.program_key == program_key,
        )
        .order_by(ParamTemplate.updated_at.desc())
    )
    return list(rows)


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.program_key != DCR_3D:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "本期仅 DCR_3D 支持结构化参数模板")
    normalized = _validate_or_422(body.params)
    await _check_name_unique(session, user.id, body.program_key, body.name)
    tpl = ParamTemplate(
        user_id=user.id, program_key=body.program_key,
        name=body.name, params=normalized,
        parameter_schema_version=SCHEMA_VERSION,
    )
    session.add(tpl)
    await session.commit()
    return tpl


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    body: TemplateUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tpl = await _get_own(session, template_id, user.id)
    if body.program_key is not None and body.program_key != tpl.program_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "参数模板不能变更所属程序")
    if body.name is not None and body.name != tpl.name:
        await _check_name_unique(
            session, user.id, tpl.program_key, body.name, exclude_id=tpl.id)
        tpl.name = body.name
    if body.params is not None:
        tpl.params = _validate_or_422(body.params)
        tpl.parameter_schema_version = SCHEMA_VERSION
    await session.commit()
    return tpl


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tpl = await _get_own(session, template_id, user.id)
    await session.delete(tpl)
    await session.commit()
