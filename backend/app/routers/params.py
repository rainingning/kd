"""程序目录与参数输入模式查询。"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_current_user
from ..models import User
from ..param_schema import get_schema
from ..services.programs import DCR_3D, get_program, list_programs

router = APIRouter(prefix="/api", tags=["params"])


@router.get("/programs")
async def programs(_: User = Depends(get_current_user)) -> dict:
    return {
        "items": [
            {
                "key": spec.key,
                "name": spec.display_name,
                "executable": spec.executable,
                "parameter_mode": spec.parameter_mode,
                "source_choices": [
                    {
                        "source_type": choice.source_type,
                        "value": choice.stdin_choice,
                        "filename": choice.filename,
                        "label": choice.label,
                    }
                    for choice in spec.source_choices
                ],
            }
            for spec in list_programs()
        ]
    }


@router.get("/param-schema")
async def param_schema(
    program_key: str = Query(default=DCR_3D),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        spec = get_program(program_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if spec.parameter_mode == "structured":
        return {**get_schema(), "program_key": program_key, "parameter_mode": "structured"}
    return {
        "program_key": program_key,
        "parameter_mode": "upload",
        "fields": [],
        "source_choices": [
            {
                "source_type": choice.source_type,
                "value": choice.stdin_choice,
                "filename": choice.filename,
                "label": choice.label,
            }
            for choice in spec.source_choices
        ],
    }
