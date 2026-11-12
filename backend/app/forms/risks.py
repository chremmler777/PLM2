"""Risk rows of the risk_assessment form, and the one-off copy from sep_risks."""
from __future__ import annotations

import copy
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.forms.compute import recompute
from app.models.forms import FormInstance, FormDefinition, FormEvent
from app.models.sep import SepRisk, SepGate

logger = logging.getLogger(__name__)

KEY = "risk_assessment"
LOP_KEY = "lop_key"
MIGRATED_MARK = "migrated_from_sep_risk"


async def _newest_instance(db: AsyncSession, project_id: int) -> FormInstance | None:
    return (await db.execute(
        select(FormInstance).join(FormDefinition).options(selectinload(FormInstance.definition))
        .where(FormInstance.project_id == project_id, FormDefinition.key == KEY)
        .order_by(FormInstance.id.desc()).limit(1))).scalar_one_or_none()


async def risk_rows_by_gate(db: AsyncSession, project_id: int) -> dict[str, list[dict]]:
    """Rows of the project's newest risk_assessment instance, grouped by gate code."""
    inst = await _newest_instance(db, project_id)
    out: dict[str, list[dict]] = {}
    if not inst:
        return out
    for row in (inst.data or {}).get("risks") or []:
        out.setdefault(row.get("gate") or "", []).append(row)
    return out


async def _save_rows(db: AsyncSession, inst: FormInstance, rows: list[dict], user) -> None:
    """Save changed risk rows through the forms service like a normal save
    (validation, recompute, `saved` event with the diff). A submitted form
    keeps its status. Raises FormError when the stored data does not validate."""
    from app.forms.service import load_instance, save_instance
    from app.models import User
    if user is None:
        user = await db.get(User, inst.updated_by or inst.created_by)
    inst = await load_instance(db, inst.id)             # with its events
    data = copy.deepcopy(inst.data or {})
    data["risks"] = rows
    await save_instance(db, inst, data, user, allow_submitted=True)


async def ensure_risk_keys(db: AsyncSession, project_id: int, user=None) -> int:
    """Give every risk row without a `lop_key` one (uuid4 hex) and save the
    newest instance; other row data is untouched. Returns how many were added.
    The key is how a LOP line finds its row again, whatever its position."""
    from app.forms.service import FormError
    inst = await _newest_instance(db, project_id)
    if not inst:
        return 0
    rows = copy.deepcopy((inst.data or {}).get("risks") or [])
    added = 0
    for row in rows:
        if not row.get(LOP_KEY):
            row[LOP_KEY] = uuid.uuid4().hex
            added += 1
    if not added:
        return 0
    try:
        await _save_rows(db, inst, rows, user)
    except FormError as e:
        logger.warning("risk keys not saved for project %s: %s", project_id, e.detail)
        return 0
    return added


async def risk_rows_by_key(db: AsyncSession, project_id: int) -> dict[str, dict] | None:
    """Rows of the newest instance by `lop_key`; None when there is no instance."""
    inst = await _newest_instance(db, project_id)
    if not inst:
        return None
    return {r[LOP_KEY]: r for r in (inst.data or {}).get("risks") or [] if r.get(LOP_KEY)}


async def set_risk_row_status(db: AsyncSession, project_id: int, lop_key: str,
                              status: str, user) -> bool:
    """Set one row's status (finished / started) in the newest instance.
    False when the row is gone or already has that status. FormError passes up."""
    inst = await _newest_instance(db, project_id)
    if not inst:
        return False
    rows = copy.deepcopy((inst.data or {}).get("risks") or [])
    row = next((r for r in rows if r.get(LOP_KEY) == lop_key), None)
    if row is None or row.get("status") == status:
        return False
    row["status"] = status
    await _save_rows(db, inst, rows, user)
    return True


async def copy_sep_risks_to_forms(db: AsyncSession) -> int:
    """Create a risk_assessment instance per SEP project and append sep_risks rows not yet copied."""
    from app.forms.loader import latest_definition
    from app.models import Project
    definition = await latest_definition(db, KEY)
    if not definition:
        return 0
    copied = 0
    project_ids = [p for (p,) in (await db.execute(select(SepGate.project_id).distinct())).all()]
    for pid in project_ids:
        risks = (await db.execute(select(SepRisk, SepGate).join(SepGate, SepRisk.gate_id == SepGate.id)
                                  .where(SepRisk.project_id == pid).order_by(SepRisk.id))).all()
        inst = await _newest_instance(db, pid)
        if not inst and not risks:
            continue
        if not inst:
            actor = risks[0][0].created_by
            project = await db.get(Project, pid)
            inst = FormInstance(project_id=pid, definition_id=definition.id, status="draft",
                                data={"header": {"project_no": project.code, "project_title": project.name}, "risks": []},
                                owner_id=actor, created_by=actor, updated_by=actor)
            db.add(inst)
            inst.events.append(FormEvent(user_id=actor, event="created"))
            await db.flush()
        data = dict(inst.data or {})
        rows = list(data.get("risks") or [])
        seen = {r.get(MIGRATED_MARK) for r in rows}
        for risk, gate in risks:
            if risk.id in seen:
                continue
            rows.append({
                MIGRATED_MARK: risk.id, "gate": gate.code, "risk": risk.effect, "impact": "",
                "q": risk.q_impact, "c": risk.c_impact, "s": risk.s_impact, "p": risk.probability,
                "countermeasure": risk.countermeasure, "responsible": risk.responsible_id,
                "due": risk.due_date.date().isoformat() if risk.due_date else None, "status": risk.status,
            })
            copied += 1
        data["risks"] = rows
        inst.data = recompute(definition.body, data)
    await db.flush()
    return copied
