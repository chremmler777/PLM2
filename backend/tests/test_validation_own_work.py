"""P2-5 (audit 2026-10-29, Christoph 2026-11-02): every department Responsible
in the implementation that had implementation work confirms its own work in
validation:

- Toolshop costed work (implementing): its "Tool work done and checked";
- Process Engineer was R on a check workflow step of the change's revision
  (not waived): "Process / parameter sheets updated", and ONLY that (no
  "Part measured" it never costed);
- Quality's R step was waived (no-geometry): no item;
- the new items hold the release while open, are answered by their
  department, and a department refuses a check it does not owe;
- a change that had already finished gets no new own-work rows."""
import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.change_validation import ValidationCheck
from app.models.entities import User
from app.models.part import Part, PartRevision
from app.models.workflow import (
    Department, UserDepartment, WfInstance, WfInstanceTask, WfTemplate,
)
from app.services.validation_service import ValidationService
from tests.conftest import ENGINEER_PASSWORD, login
from tests.test_validation_checks import _state, _url, val  # noqa: F401 (fixture)

pytestmark = pytest.mark.asyncio


async def _with_r_departments(session_factory, seed, val):
    """Toolshop costs work; Process R on a live step, Quality R on a waived
    one, of an ECN instance on a revision the change originated."""
    async with session_factory() as s:
        ids = {}
        for name in ("Toolshop", "Process Engineer", "Quality"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d); await s.flush(); ids[name] = d.id
            email = f"{name.split()[0].lower()}@own.test"
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=name, role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u); await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=d.id))
        s.add(CostingPosition(
            change_id=val["change_id"], department_id=ids["Toolshop"],
            label="Inserts", kind="internal", pricing="estimate", hours=2.0,
            created_by=seed["admin_id"]))
        part = Part(project_id=seed["project_id"], part_number="886.300", name="Cover",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part); await s.flush()
        rev = PartRevision(part_id=part.id, revision_name="2", phase="review",
                           originating_change_id=val["change_id"],
                           created_by=seed["admin_id"])
        s.add(rev); await s.flush()
        t = WfTemplate(name="ECN Implementation (Article)", description="x", version=1,
                       is_active=True, created_by=seed["admin_id"])
        s.add(t); await s.flush()
        inst = WfInstance(template_id=t.id, part_revision_id=rev.id, status="active",
                          current_stage_order=3, started_by=seed["admin_id"])
        s.add(inst); await s.flush()
        for dept, status in (("Process Engineer", "approved"), ("Quality", "waived")):
            s.add(WfInstanceTask(instance_id=inst.id, stage_order=3,
                                 department_id=ids[dept], rasic_letter="R",
                                 status=status, is_actionable=True))
        await s.commit()
    return ids


async def test_r_departments_get_their_own_item(client, session_factory, seed, val):
    ids = await _with_r_departments(session_factory, seed, val)
    pm = await login(client, val["user"]["Project Manager"]["email"], ENGINEER_PASSWORD)
    st = await _state(client, pm, val)
    keys = {d["department_id"]: [c["check_key"] for c in d["checks"]]
            for d in st["departments"]}
    assert keys[ids["Toolshop"]] == ["toolshop_work"]
    assert keys[ids["Process Engineer"]] == ["parameter_sheets"]
    assert ids["Quality"] not in keys                    # waived step: no work
    # the open items hold the release in the departments' words
    async with session_factory() as s:
        change = await s.get(ChangeRequest, val["change_id"])
        _, outstanding = await ValidationService.release_parts(s, change)
    assert "Toolshop: Tool work done and checked" in outstanding
    assert "Process Engineer: Process / parameter sheets updated" in outstanding


async def test_own_item_answered_by_its_department_only(client, session_factory, seed, val):
    ids = await _with_r_departments(session_factory, seed, val)
    proc = await login(client, "process@own.test", ENGINEER_PASSWORD)
    # a check it does not owe is refused (R only: its own work, no "measured")
    res = await client.post(_url(val, "/checks"), headers=proc, json={
        "department_id": ids["Process Engineer"], "check_key": "measured",
        "status": "passed"})
    assert res.status_code == 400 and "not owed" in res.json()["detail"]
    res = await client.post(_url(val, "/checks"), headers=proc, json={
        "department_id": ids["Process Engineer"], "check_key": "parameter_sheets",
        "status": "passed", "note": "sheet 4711 rev 3 run on press 12"})
    assert res.status_code == 201, res.text
    # another department may not answer it
    shop = await login(client, "toolshop@own.test", ENGINEER_PASSWORD)
    res = await client.post(_url(val, "/checks"), headers=shop, json={
        "department_id": ids["Process Engineer"], "check_key": "parameter_sheets",
        "status": "failed", "note": "x"})
    assert res.status_code in (400, 403)
    # Quality (waived) owes nothing and is refused
    q = await login(client, "quality@own.test", ENGINEER_PASSWORD)
    res = await client.post(_url(val, "/checks"), headers=q, json={
        "department_id": ids["Quality"], "check_key": "inspection_plan",
        "status": "passed"})
    assert res.status_code == 400 and "not implementing" in res.json()["detail"]


async def test_finished_change_gets_no_new_own_work_rows(client, session_factory, seed, val):
    await _with_r_departments(session_factory, seed, val)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, val["change_id"])
        change.status = "released"
        await s.commit()
    pm = await login(client, val["user"]["Project Manager"]["email"], ENGINEER_PASSWORD)
    await _state(client, pm, val)
    async with session_factory() as s:
        keys = set((await s.execute(select(ValidationCheck.check_key).where(
            ValidationCheck.change_id == val["change_id"]))).scalars().all())
    assert not keys & {"toolshop_work", "parameter_sheets", "inspection_plan"}
