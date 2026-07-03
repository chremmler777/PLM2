"""Seeded change-management workflow templates (spec: workflow definitions,
2026-07-02). Idempotent by template name / mapping key: existing templates and
mappings are never overwritten, so designer edits survive restarts.

Department names must match the names seeded in app.main.seed_test_data;
_get_or_create_department covers fresh test databases.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRoutingStandard, CHANGE_TYPES
from app.models.entities import User
from app.models.workflow import (
    CheckWorkflowStandard, Department, WfStage, WfStep, WfStepRasic, WfTemplate,
    CHECK_WF_ITEM_CATEGORIES,
)

# RASIC data copied from the spec tables (Template 1 / Template 2).
# Step tuple: (step_name, rasic list[(department, letter)], flags dict)

ECM_BEWERTUNG = {
    "name": "ECM Bewertung",
    "description": "Change-level assessment routing (captured -> approved), D1 matrix",
    "stages": [
        ("Machbarkeit & Bewertung", [
            ("Fachbereichsbewertung", [
                ("Sales", "R"), ("R&D", "R"), ("Tool design", "R"), ("IE", "R"),
                ("Quality", "R"), ("Logistics", "R"), ("Production", "R"),
                ("Purchasing", "R"), ("Production control", "R"),
                ("Project Manager", "A"), ("Planner/Scheduler", "I"),
            ], {}),
        ]),
        ("Summierung & Budget", [
            ("Kostenzusammenfassung prüfen & Budget freigeben", [
                ("Project Manager", "R"), ("Sales", "A"),
                ("R&D", "C"), ("Tool design", "C"),
                ("IE", "I"), ("Quality", "I"), ("Logistics", "I"),
                ("Production", "I"), ("Purchasing", "I"), ("Production control", "I"),
            ], {}),
        ]),
        ("Kundenaktivitäten", [
            ("Angebot an Kunde / Kundenantwort erfassen", [
                ("Sales", "R"), ("Project Manager", "A"),
                ("Quality", "I"), ("R&D", "I"),
            ], {}),
        ]),
    ],
}


def _ecn_umsetzung(name: str, konstruktion_r: str) -> dict:
    return {
        "name": name,
        "description": "Check workflow per impacted ECN revision (kickoff -> ready-to-go)",
        "stages": [
            ("Konstruktion", [
                ("3D-Daten aktualisieren", [
                    (konstruktion_r, "R"), ("R&D", "A"), ("Project Manager", "I"),
                ], {"requires_cad_evidence": True}),
                ("Zeichnungen & Doku aktualisieren", [
                    (konstruktion_r, "R"), ("R&D", "A"), ("Quality", "S"),
                ], {}),
            ]),
            ("Design-Check", [
                ("Konstruktionsprüfung", [
                    ("R&D", "R"), ("Quality", "A"), ("IE", "C"),
                ], {"four_eyes": True}),
            ]),
            ("Industrialisierung", [
                ("Werkzeugänderung umsetzen", [
                    ("Production", "R"), ("Tool design", "A"), ("Production control", "I"),
                ], {}),
                ("Prozess/Arbeitspläne anpassen", [
                    ("IE", "R"), ("Project Manager", "A"), ("Production", "C"),
                ], {}),
                ("Prüfplan / PPAP-Bedarf klären", [
                    ("Quality", "R"), ("Project Manager", "A"), ("Sales", "C"),
                ], {}),
                ("Stammdaten & Logistik aktualisieren", [
                    ("Logistics", "R"), ("Project Manager", "A"),
                    ("Purchasing", "C"), ("Production control", "I"),
                ], {}),
            ]),
            ("Ready to go", [
                ("Bemusterung / Trial", [
                    ("Quality", "R"), ("Project Manager", "A"), ("Production", "S"),
                ], {}),
                ("Finale Freigabe", [
                    ("Project Manager", "R"), ("Quality", "A"),
                    ("Sales", "I"), ("Logistics", "I"), ("Production control", "I"),
                ], {}),
            ]),
        ],
    }


ECN_UMSETZUNG_WERKZEUG = _ecn_umsetzung("ECN Umsetzung (Werkzeug)", "Tool design")
ECN_UMSETZUNG_ARTIKEL = _ecn_umsetzung("ECN Umsetzung (Artikel)", "R&D")

CHECK_WF_CATEGORY_TEMPLATE = {
    "article": "ECN Umsetzung (Artikel)",
    "tool": "ECN Umsetzung (Werkzeug)",
    "assembly_equipment": "ECN Umsetzung (Werkzeug)",
    "eoat": "ECN Umsetzung (Werkzeug)",
    "gauge": "ECN Umsetzung (Werkzeug)",
}


async def _get_or_create_department(session: AsyncSession, name: str) -> Department:
    dept = (await session.execute(
        select(Department).where(Department.name == name))).scalar_one_or_none()
    if dept is None:
        dept = Department(name=name, flow_type="action", is_active=True)
        session.add(dept)
        await session.flush()
    return dept


async def _seed_user_id(session: AsyncSession) -> int:
    uid = (await session.execute(
        select(User.id).where(User.role == "admin").order_by(User.id).limit(1)
    )).scalar_one_or_none()
    if uid is None:
        uid = (await session.execute(
            select(User.id).order_by(User.id).limit(1))).scalar_one()
    return uid


async def _seed_template(session: AsyncSession, spec: dict) -> WfTemplate:
    existing = (await session.execute(
        select(WfTemplate).where(WfTemplate.name == spec["name"]))).scalars().first()
    if existing is not None:
        return existing
    tmpl = WfTemplate(
        name=spec["name"], description=spec["description"], version=1,
        is_active=True, created_by=await _seed_user_id(session),
    )
    session.add(tmpl)
    await session.flush()
    for stage_order, (stage_name, steps) in enumerate(spec["stages"], start=1):
        stage = WfStage(template_id=tmpl.id, stage_order=stage_order, name=stage_name)
        session.add(stage)
        await session.flush()
        for pos, (step_name, rasic, flags) in enumerate(steps, start=1):
            step = WfStep(
                stage_id=stage.id, step_name=step_name, position_in_stage=pos,
                requires_cad_evidence=flags.get("requires_cad_evidence", False),
                four_eyes=flags.get("four_eyes", False),
            )
            session.add(step)
            await session.flush()
            for dept_name, letter in rasic:
                dept = await _get_or_create_department(session, dept_name)
                session.add(WfStepRasic(
                    step_id=step.id, department_id=dept.id, rasic_letter=letter))
    await session.flush()
    return tmpl


async def seed_check_standards(session: AsyncSession) -> None:
    templates = {}
    for spec in (ECN_UMSETZUNG_WERKZEUG, ECN_UMSETZUNG_ARTIKEL):
        templates[spec["name"]] = await _seed_template(session, spec)
    uid = await _seed_user_id(session)
    for category in CHECK_WF_ITEM_CATEGORIES:
        existing = (await session.execute(
            select(CheckWorkflowStandard).where(
                CheckWorkflowStandard.item_category == category)
        )).scalar_one_or_none()
        if existing is None:
            tmpl = templates[CHECK_WF_CATEGORY_TEMPLATE[category]]
            session.add(CheckWorkflowStandard(
                item_category=category, template_id=tmpl.id,
                template_version=tmpl.version, updated_by=uid,
                updated_at=datetime.utcnow(),
            ))
    await session.flush()


async def seed_assessment_standard(session: AsyncSession) -> None:
    tmpl = await _seed_template(session, ECM_BEWERTUNG)
    uid = await _seed_user_id(session)
    for change_type in CHANGE_TYPES:
        existing = (await session.execute(
            select(ChangeRoutingStandard).where(
                ChangeRoutingStandard.change_type == change_type)
        )).scalar_one_or_none()
        if existing is None:
            session.add(ChangeRoutingStandard(
                change_type=change_type, template_id=tmpl.id,
                template_version=tmpl.version, updated_by=uid,
                updated_at=datetime.utcnow(),
            ))
    await session.flush()


async def seed_change_workflows(session: AsyncSession) -> None:
    await seed_assessment_standard(session)
    await seed_check_standards(session)


# Dev-only department memberships (spec: Phase E Task 17). Grants the two
# well-known dev accounts real department membership so My Tasks and the
# complete_task membership guard have someone to work with out of the box.
# Create-if-absent per (user, department) pair: never removes memberships an
# admin has since set up by hand, and safe to call on every startup.
DEV_MEMBERSHIPS = {
    "test@example.com": ["R&D"],
    "admin@example.com": None,  # None = every active department
}


async def seed_dev_department_memberships(session: AsyncSession) -> None:
    from app.models.workflow import UserDepartment

    all_dept_ids = [d for (d,) in (await session.execute(
        select(Department.id).where(Department.is_active == True)  # noqa: E712
    )).all()]

    for email, dept_names in DEV_MEMBERSHIPS.items():
        user = (await session.execute(
            select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            continue
        if dept_names is None:
            target_ids = set(all_dept_ids)
        else:
            target_ids = set()
            for name in dept_names:
                dept = (await session.execute(
                    select(Department).where(Department.name == name)
                )).scalar_one_or_none()
                if dept is not None:
                    target_ids.add(dept.id)

        existing_ids = {uid for (uid,) in (await session.execute(
            select(UserDepartment.department_id).where(
                UserDepartment.user_id == user.id))).all()}
        for dept_id in target_ids - existing_ids:
            session.add(UserDepartment(user_id=user.id, department_id=dept_id))
    await session.flush()


async def repair_inflight_check_workflows(session: AsyncSession) -> int:
    """One-time self-heal: ensure check-WF instances exist for ECN revisions of
    changes already past kickoff (deployed mid-flight before Phase B).
    Idempotent — _ensure_check_workflow no-ops when an instance exists or the
    category is unmapped. Returns the number of items examined."""
    from sqlalchemy.orm import selectinload
    from app.models.change import ChangeRequest
    from app.services.change_service import ChangeService  # local import: avoids cycle

    changes = (await session.execute(
        select(ChangeRequest)
        .where(ChangeRequest.status.in_(("in_implementation", "in_validation")))
        .options(selectinload(ChangeRequest.impacted_items))
    )).scalars().all()
    examined = 0
    for change in changes:
        user_id = change.lead_id or change.raised_by
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                continue
            examined += 1
            await ChangeService._ensure_check_workflow(session, change, item, user_id)
    await session.flush()
    return examined
