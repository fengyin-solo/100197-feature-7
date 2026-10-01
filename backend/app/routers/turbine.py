"""风电机组接口：维护风电机组，覆盖投运机组、登记停机、办理退役等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.turbine import STATUS_ORDER, TurbineService, parse_height

router = APIRouter(prefix="/api/turbine", tags=["风电机组"])

service = TurbineService()

LIST_FIELDS = ["机组编号", "机组机型", "额定功率", "轮毂高度", "所属场站", "投运日期", "累计发电量", "机组状态"]
STATUSES = STATUS_ORDER


def _resolve_filters(
    keyword: str | None,
    status: str | None,
    height_min: str | None,
    height_max: str | None,
) -> tuple[str | None, str | None, float | None, float | None]:
    """把查询参数解析成服务层条件；条件本身有误时给出说明而不是返回空表。"""
    if status is not None:
        status = status.strip() or None
        if status is not None and status not in STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"机组状态「{status}」不在可选范围内，可选：{'、'.join(STATUSES)}",
            )

    minimum = maximum = None
    try:
        minimum = parse_height(height_min)
        maximum = parse_height(height_max)
    except (TypeError, ValueError):
        bad = height_min if minimum is None and height_min else height_max
        raise HTTPException(
            status_code=400,
            detail=f"轮毂高度「{bad}」不是数字，请填写以米为单位的数值，例如 90",
        ) from None

    if minimum is not None and minimum < 0:
        raise HTTPException(status_code=400, detail="轮毂高度下限不能为负数")
    if maximum is not None and maximum < 0:
        raise HTTPException(status_code=400, detail="轮毂高度上限不能为负数")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"轮毂高度区间互相矛盾：下限 {minimum:g} 米高于上限 {maximum:g} 米，请调整后再查询",
        )

    keyword = keyword.strip() if keyword and keyword.strip() else None
    return keyword, status, minimum, maximum


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按机组编号或机组机型模糊检索"),
    status: str | None = Query(default=None, description="待投运、运行中、故障停机、已退役"),
    height_min: str | None = Query(default=None, description="轮毂高度下限，单位米"),
    height_max: str | None = Query(default=None, description="轮毂高度上限，单位米"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """编号/机型、状态、轮毂高度区间同时生效；没有匹配数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    page = max(page, 1)
    size = max(size, 1)
    keyword, status, minimum, maximum = _resolve_filters(keyword, status, height_min, height_max)
    items, total, summary = service.list_entries(
        keyword=keyword,
        status=status,
        height_min=minimum,
        height_max=maximum,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size, summary=summary)


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按机组编号或机组机型模糊检索"),
    status: str | None = Query(default=None, description="待投运、运行中、故障停机、已退役"),
    height_min: str | None = Query(default=None, description="轮毂高度下限，单位米"),
    height_max: str | None = Query(default=None, description="轮毂高度上限，单位米"),
) -> dict[str, Any]:
    """导出风电机组清单：返回与台账当前过滤条件一致的全量数据。"""
    keyword, status, minimum, maximum = _resolve_filters(keyword, status, height_min, height_max)
    items, total = service.export_entries(
        keyword=keyword, status=status, height_min=minimum, height_max=maximum
    )
    return {"module": "turbine", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条风电机组明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"风电机组 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条风电机组，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="风电机组已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条风电机组执行投运机组、登记停机、办理退役；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
