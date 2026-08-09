"""参数 Schema 查询（T3.1）：前端据此动态渲染参数表单。"""
from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..models import User
from ..param_schema import get_schema

router = APIRouter(prefix="/api", tags=["params"])


@router.get("/param-schema")
async def param_schema(_: User = Depends(get_current_user)) -> dict:
    return get_schema()
