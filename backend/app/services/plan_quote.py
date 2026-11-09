"""Real time vs. Sales buffer, and bank builds as estimates (Christoph 2026-11-09).

Sales adds ONE buffer at the end of the plan, in weeks. Sales and PM see the
real time (the work, without that buffer) and the buffer separately; the
customer is told the timing including the buffer. The buffer is the plan's
buffer block that ends the plan (the template's "Safety buffer"); setting it
in weeks resizes that block, or adds one after the real work when there is
none.

A bank build is an estimate: it floats with the PO, and PM discusses the bank
build with the customer when the PO arrives. Its blocks carry estimate=True
and a note, and the offer never states their dates as fixed.
"""
import math
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import plan_engine as eng

BANK_BUILD_NOTE = ("Estimate - floats with the PO; PM discusses the bank build "
                   "when the PO arrives")
SALES_BUFFER_NAME = "Sales buffer"
MAX_BUFFER_WEEKS = 104


def _week_len(cal: eng.Calendar) -> int:
    return len(cal.workdays) if cal.working else 7


def _weeks(days: int, cal: eng.Calendar) -> float:
    """Days in the plan's unit as weeks, one decimal."""
    return round(days / _week_len(cal), 1) if days else 0.0


def _leaves(tasks: list) -> list:
    parents = {t.parent_id for t in tasks if t.parent_id}
    return [t for t in tasks if t.id not in parents and not t.is_idea]


def sales_buffer(tasks: list) -> Optional[object]:
    """The buffer block that ends the plan (latest end; ties: the longest)."""
    bufs = [t for t in _leaves(tasks) if t.kind == "buffer"]
    if not bufs:
        return None
    return max(bufs, key=lambda t: (t.end_date, int(t.duration_days or 0)))


def timing_summary(tasks: list, cal: eng.Calendar) -> dict:
    """{start, real_finish (exclusive), real_days, real_weeks, sales_buffer_*,
    total_days, total_weeks}: the real time is the committed work without
    the buffers and the milestones after them; total includes the buffer."""
    leaves = _leaves(tasks)
    work = [t for t in leaves if t.kind not in ("buffer", "milestone")]
    if not leaves:
        return {"start": None, "real_finish": None, "real_days": 0, "real_weeks": 0.0,
                "sales_buffer_task_id": None, "sales_buffer_days": 0,
                "sales_buffer_weeks": 0.0, "total_days": 0, "total_weeks": 0.0}
    start = min(t.start_date for t in leaves)
    total_end = max(t.end_date for t in leaves)
    real_end = max((t.end_date for t in work), default=total_end)
    real = cal.span(start, real_end)
    total = cal.span(start, total_end)
    buf = sales_buffer(tasks)
    return {
        "start": start, "real_finish": real_end,
        "real_days": real, "real_weeks": _weeks(real, cal),
        "sales_buffer_task_id": buf.id if buf is not None else None,
        "sales_buffer_days": max(0, total - real),
        "sales_buffer_weeks": _weeks(max(0, total - real), cal),
        "total_days": total, "total_weeks": _weeks(total, cal),
    }


async def set_sales_buffer(session: AsyncSession, change, plan: str,
                           weeks: float, user) -> None:
    """Resize the end buffer to `weeks` (0 allowed), or add it after the
    real work; the plan's automatic scheduling pushes what follows it."""
    from app.services.change_plan_service import ChangePlanService as S
    from app.services.change_service import ChangeError
    if weeks is None or weeks < 0 or weeks > MAX_BUFFER_WEEKS:
        raise ChangeError(f"The buffer is 0 to {MAX_BUFFER_WEEKS} weeks")
    await S._require_edit(session, change, plan, user, structural=False)
    tasks = await S.tasks(session, change, plan)
    cal = S.calendar(change, plan)
    days = int(math.ceil(weeks * _week_len(cal)))
    buf = sales_buffer(tasks)
    if buf is not None:
        await S.update_task(session, change, buf.id, {"duration_days": days}, user,
                            reason="Sales buffer set to "
                                   f"{weeks:g} week{'s' if weeks != 1 else ''}")
        return
    work = [t for t in _leaves(tasks) if t.kind not in ("buffer", "milestone")]
    if not work:
        raise ChangeError("The plan has no work yet to put a buffer after")
    last = max(work, key=lambda t: t.end_date)
    tail = [t for t in _leaves(tasks) if t.kind == "milestone"
            and t.start_date >= last.end_date]
    await S.apply_changes(session, change, plan, {
        "tasks_upsert": [{"id": "sales-buffer", "name": SALES_BUFFER_NAME,
                          "kind": "buffer", "lane": "Sales",
                          "start_date": last.end_date, "duration_days": days}],
        "links_upsert": [{"from_task_id": last.id, "to_task_id": "sales-buffer",
                          "type": "FS", "lag_days": 0}]
        + [{"from_task_id": "sales-buffer", "to_task_id": m.id, "type": "FS",
            "lag_days": 0} for m in tail],
    }, user, reason=f"Sales buffer of {weeks:g} weeks added")


def mark_estimates(out: dict) -> None:
    """PlanOut tasks: bank builds are estimates with the note."""
    for t in out.get("tasks", []):
        est = t.get("kind") == "bank_build"
        t["estimate"] = est
        t["estimate_note"] = BANK_BUILD_NOTE if est else None
