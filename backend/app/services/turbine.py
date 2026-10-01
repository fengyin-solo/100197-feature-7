"""风电机组业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "turbine"
REQUIRED_FIELDS = ["机组编号", "机组机型", "额定功率"]
STATUS_ORDER = ["待投运", "运行中", "故障停机", "已退役"]
ACTION_RULES = {"投运机组": "运行中", "登记停机": "故障停机", "办理退役": "已退役"}
NEGATIVE_ACTIONS = []


def _hub_height(value: Any) -> float | None:
    """把轮毂高度解析成数字；登记成文本（如“110米”）时提取其中的数值。"""
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


class TurbineService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        hub_min: float | None = None,
        hub_max: float | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        """在同一份机组数据上叠加全部条件，返回当前页、过滤后总数与过滤后汇总。"""
        rows = store.rows(MODULE)
        needle = (keyword or "").strip().lower()
        if needle:
            rows = [
                row for row in rows
                if needle in str(row.get("机组编号", "")).lower()
                or needle in str(row.get("机组机型", "")).lower()
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if hub_min is not None or hub_max is not None:
            rows = [
                row for row in rows
                if (height := _hub_height(row.get("轮毂高度"))) is not None
                and (hub_min is None or height >= hub_min)
                and (hub_max is None or height <= hub_max)
            ]
        total = len(rows)
        summary = {
            "在运机组": sum(1 for row in rows if row.get("status") == "运行中"),
            "故障停机台数": sum(1 for row in rows if row.get("status") == "故障停机"),
            "待投运台数": sum(1 for row in rows if row.get("status") == "待投运"),
        }
        start = max(page - 1, 0) * size
        return rows[start:start + size], total, summary

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["机组状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"风电机组 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于风电机组可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["机组状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"风电机组已{action}"
