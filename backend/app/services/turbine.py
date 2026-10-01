"""风电机组业务规则：状态流转、字段校验与筛选口径都收在这里。

台账列表、厂房汇总卡片、清单导出共用 :meth:`TurbineService._query`，
保证三者读到的条数始终是同一批过滤结果。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "turbine"
REQUIRED_FIELDS = ["机组编号", "机组机型", "额定功率"]
STATUS_ORDER = ["待投运", "运行中", "故障停机", "已退役"]
ACTION_RULES = {"投运机组": "运行中", "登记停机": "故障停机", "办理退役": "已退役"}
NEGATIVE_ACTIONS = []

# 对外展示用的机组状态列，与内部流转用的 status 字段保持同值。
PRESENT_FIELDS = ["机组编号", "机组机型", "额定功率", "轮毂高度", "所属场站", "投运日期", "累计发电量", "机组状态"]


def parse_height(value: str | None) -> float | None:
    """把轮毂高度输入解析成数字；空值表示不限制，解析不了返回 None 交给上层说明。"""
    if value is None or not str(value).strip():
        return None
    return float(str(value).strip())


class TurbineService:
    def _query(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        height_min: float | None = None,
        height_max: float | None = None,
    ) -> list[dict[str, Any]]:
        """按同一份数据依次叠加条件：编号/机型模糊、状态、轮毂高度区间。"""
        rows = store.rows(MODULE)

        if keyword and keyword.strip():
            word = keyword.strip()
            rows = [
                row for row in rows
                if word in str(row.get("机组编号", "")) or word in str(row.get("机组机型", ""))
            ]

        if status and status.strip():
            wanted = status.strip()
            rows = [row for row in rows if str(row.get("机组状态") or row.get("status")) == wanted]

        # 高度无法解析成数字的记录不参与区间比较，避免脏数据混进区间结果。
        def height_of(row: dict[str, Any]) -> float | None:
            try:
                return float(row.get("轮毂高度"))
            except (TypeError, ValueError):
                return None

        if height_min is not None:
            rows = [row for row in rows if (h := height_of(row)) is not None and h >= height_min]
        if height_max is not None:
            rows = [row for row in rows if (h := height_of(row)) is not None and h <= height_max]

        return rows

    @staticmethod
    def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        """汇总口径直接取过滤后的整批记录，与台账 total 天然一致。"""
        return {
            "running": sum(1 for row in rows if str(row.get("机组状态") or row.get("status")) == "运行中"),
            "fault": sum(1 for row in rows if str(row.get("机组状态") or row.get("status")) == "故障停机"),
            "total": len(rows),
        }

    @staticmethod
    def _present(row: dict[str, Any]) -> dict[str, Any]:
        """补齐机组状态展示列，保证登记、动作流转后页面读到的状态不缺位。"""
        item = dict(row)
        item["机组状态"] = row.get("机组状态") or row.get("status")
        return item

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        height_min: float | None = None,
        height_max: float | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        rows = self._query(
            keyword=keyword, status=status, height_min=height_min, height_max=height_max
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [self._present(row) for row in rows[start:start + size]]
        return page_rows, total, self._summarize(rows)

    def export_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        height_min: float | None = None,
        height_max: float | None = None,
        limit: int = 10000,
    ) -> tuple[list[dict[str, Any]], int]:
        """导出与列表相同条件下的全量记录，避免导出与台账对不上账。"""
        rows = self._query(
            keyword=keyword, status=status, height_min=height_min, height_max=height_max
        )
        return [self._present(row) for row in rows[:limit]], len(rows)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in PRESENT_FIELDS if field in values})
        entry["status"] = STATUS_ORDER[0]
        entry["机组状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), []

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
        return self._present(entry), f"风电机组已{action}"
