"""Risk rows of the risk_assessment form, and the one-off copy from sep_risks."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.forms.compute import recompute
from app.models.forms import FormInstance, FormDefinition, FormEvent
from app.models.sep import SepRisk, SepGate

KEY = "risk_assessment"
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
