"""ECR-solid C7 / §10 (RELEASE_V2): release checklist rows are answered by
their department; PM, the lead or an admin only for a department nobody in
the change's organization belongs to (no dead end). The customer's approval
is a reference to a document, not a tick. The ERP row reads the routing
time from the measured cycle time."""
import pytest

from app.models.change import ChangeRequest
from app.models.change_validation import ValidationCheck
from app.services import cm_switches
from tests.test_release_checklist import _auth, _check, _state, rel_world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_negative_pm_does_not_tick_an_owned_row(client, rel_world, admin_auth):
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    for auth in (pm, admin_auth):
        res = await _check(client, auth, cid, "index_updated", "done")
        assert res.status_code == 403, res.text
    st = await _state(client, pm, cid)
    rows = {c["key"]: c for c in st["checks"]}
    assert rows["index_updated"]["can_answer"] is False
    # a department nobody belongs to (Packaging Engineer is not seeded,
    # Scheduling has no member): PM answers, so nothing is stuck
    assert rows["packaging_updated"]["can_answer"] is True
    assert rows["erp_updated"]["can_answer"] is True
    res = await _check(client, pm, cid, "erp_updated", "done", "routing 4711 rev 3")
    assert res.status_code == 200, res.text
    dev = await _auth(client, "dev")
    res = await _check(client, dev, cid, "index_updated", "done")
    assert res.status_code == 200, res.text
    assert {c["key"]: c for c in res.json()["checks"]}["index_updated"]["status"] == "done"


async def test_customer_approval_needs_a_reference(client, rel_world):
    cid = rel_world["change_id"]
    apqp = await _auth(client, "apqp")
    for note in (None, "ok", "done"):
        res = await _check(client, apqp, cid, "customer_approval", "done", note)
        assert res.status_code == 400, res.text
        assert "customer's approval" in res.json()["detail"]
    res = await _check(client, apqp, cid, "customer_approval", "done",
                       "PSW 886.197-D signed 2026-10-12")
    assert res.status_code == 200, res.text
    row = {c["key"]: c for c in res.json()["checks"]}["customer_approval"]
    assert row["needs_ref"] is True and row["note"].startswith("PSW 886.197-D")


async def test_erp_row_reads_the_measured_routing_time(client, rel_world, session_factory):
    cid = rel_world["change_id"]
    async with session_factory() as s:
        s.add(ValidationCheck(change_id=cid, check_key="cycle_time", status="passed",
                              department_id=rel_world["depts"]["Tool Engineer"],
                              value=41.1))
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    erp = {c["key"]: c for c in st["checks"]}["erp_updated"]
    assert erp["hint"] == "Routing time from validation: 41.1 s"


async def test_switch_off_pm_ticks_any_row_and_no_reference(client, rel_world, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    assert (await _check(client, pm, cid, "index_updated", "done")).status_code == 200
    assert (await _check(client, pm, cid, "customer_approval", "done")).status_code == 200


# --- review loop 1: an admin is no member, an inactive department neither --

async def _add_member(session_factory, user_id, dept_id):
    from app.models.workflow import UserDepartment
    async with session_factory() as s:
        s.add(UserDepartment(user_id=user_id, department_id=dept_id))
        await s.commit()


async def test_admin_only_department_falls_back_to_pm(
        client, rel_world, session_factory, seed):
    """An admin belongs to every department in a small plant: counting the
    admin left Scheduling's ERP row with no button for PM and nobody's task."""
    cid = rel_world["change_id"]
    await _add_member(session_factory, seed["admin_id"], rel_world["depts"]["Scheduling"])
    pm = await _auth(client, "pm")
    rows = {c["key"]: c for c in (await _state(client, pm, cid))["checks"]}
    assert rows["erp_updated"]["can_answer"] is True
    assert rows["erp_updated"]["run_team_answers"] is True
    assert rows["index_updated"]["run_team_answers"] is False
    # PM has the task, named as the run team's (not Scheduling's backup)
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
    sched = [t for t in tasks if t["kind"] == "release_check" and t["change_id"] == cid
             and t["department_id"] == rel_world["depts"]["Scheduling"]]
    assert len(sched) == 1 and "no member here" in sched[0]["hint"]
    assert sched[0]["role"] == "main"
    actions = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                headers=pm)).json()["actions"]
    assert any(a["kind"] == "release_check"
               and a["department_id"] == rel_world["depts"]["Scheduling"]
               for a in actions)
    # an owned row stays the department's; PM gets no task for it
    assert not any(t["kind"] == "release_check" and t["change_id"] == cid
                   and t["department_id"] == rel_world["depts"]["Development"]
                   for t in tasks)
    res = await _check(client, pm, cid, "erp_updated", "done", "routing 4711 rev 3")
    assert res.status_code == 200, res.text


async def test_refusal_names_the_owner_not_pm(client, rel_world):
    pm = await _auth(client, "pm")
    res = await _check(client, pm, rel_world["change_id"], "index_updated", "done")
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert detail.startswith("Development answers this item")
    assert "only while Development has no member here" in detail


async def test_inactive_owner_department_falls_back_to_pm(
        client, rel_world, session_factory):
    from app.models.workflow import Department
    async with session_factory() as s:
        (await s.get(Department, rel_world["depts"]["APQP"])).is_active = False
        await s.commit()
    pm = await _auth(client, "pm")
    rows = {c["key"]: c for c in (await _state(client, pm, rel_world["change_id"]))["checks"]}
    assert rows["customer_approval"]["can_answer"] is True
    assert rows["customer_approval"]["run_team_answers"] is True


async def test_customer_approval_na_needs_the_customers_waiver(
        client, rel_world, session_factory):
    cid = rel_world["change_id"]
    apqp = await _auth(client, "apqp")
    for note in ("x", "ok", "n/a"):
        res = await _check(client, apqp, cid, "customer_approval", "na", note)
        assert res.status_code == 400, (note, res.text)
        assert "customer waived" in res.json()["detail"]
    res = await _check(client, apqp, cid, "customer_approval", "na",
                       "customer mail 2026-10-12 PPAP waived")
    assert res.status_code == 200, res.text
    assert {c["key"]: c for c in res.json()["checks"]}["customer_approval"][
        "na_needs_ref"] is True
    # an internal change has no customer to waive anything: a note is enough
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).customer_relevant = False
        await s.commit()
    res = await _check(client, apqp, cid, "customer_approval", "na", "internal")
    assert res.status_code == 200, res.text


async def test_switch_off_na_needs_only_a_note(client, rel_world, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    apqp = await _auth(client, "apqp")
    res = await _check(client, apqp, rel_world["change_id"], "customer_approval", "na", "x")
    assert res.status_code == 200, res.text


# --- click-through R38 (R4): rows whose words promise evidence demand it ----

@pytest.mark.parametrize("key,who,ref", [
    ("parts_measured", "apqp", "measurement report MR-2026-118"),
    ("customer_informed", "pm", "mail to Brose 2026-10-20: SOP KW 45"),
    ("erp_updated", "pm", "routing 4711 rev 3, BOM 886.197-D"),
])
async def test_evidence_rows_refuse_a_bare_done(client, rel_world, key, who, ref):
    cid = rel_world["change_id"]
    auth = await _auth(client, who)
    for note in (None, "ok", "done"):
        res = await _check(client, auth, cid, key, "done", note)
        assert res.status_code == 400, (key, note, res.text)
        assert "e.g." in res.json()["detail"]
    st = await _state(client, auth, cid)
    row = {c["key"]: c for c in st["checks"]}[key]
    assert row["needs_ref"] is True and row["ref_prompt"]
    res = await _check(client, auth, cid, key, "done", ref)
    assert res.status_code == 200, res.text


async def test_cm_row_takes_the_value_or_the_spc_report(client, rel_world):
    cid = rel_world["change_id"]
    apqp = await _auth(client, "apqp")
    res = await _check(client, apqp, cid, "process_stable_apqp", "done")
    assert res.status_code == 400 and "SPC" in res.json()["detail"]
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", "SPC report 2026-55")
    assert res.status_code == 200, res.text
    res = await _check(client, apqp, cid, "process_stable_apqp", "open")
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", value=1.85)
    assert res.status_code == 200, res.text


async def test_drawing_row_refuses_done_while_the_revision_has_no_files(
        client, rel_world, part, session_factory, seed):
    from app.models.change import ChangeImpactedItem
    from app.models.part import RevisionFile
    cid = rel_world["change_id"]
    async with session_factory() as s:
        s.add(ChangeImpactedItem(change_id=cid, part_id=part["part_id"],
                                 resulting_revision_id=part["revision_id"],
                                 created_by=seed["admin_id"]))
        await s.commit()
    dev = await _auth(client, "dev")
    row = {c["key"]: c for c in (await _state(client, dev, cid))["checks"]}["drawing_released"]
    assert "no drawing or 3D file" in (row["done_refusal"] or "")
    res = await _check(client, dev, cid, "drawing_released", "done")
    assert res.status_code == 400 and "no drawing or 3D file" in res.json()["detail"]
    async with session_factory() as s:
        s.add(RevisionFile(revision_id=part["revision_id"], filename="d.pdf",
                           file_path="/tmp/d.pdf", file_type="drawing", file_size=1,
                           mime_type="application/pdf", file_hash="0" * 64,
                           uploaded_by=seed["admin_id"]))
        await s.commit()
    res = await _check(client, dev, cid, "drawing_released", "done")
    assert res.status_code == 200, res.text


async def test_switch_off_takes_the_bare_evidence_rows(client, rel_world, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    for key in ("parts_measured", "erp_updated", "customer_informed", "process_stable_apqp"):
        assert (await _check(client, pm, cid, key, "done")).status_code == 200, key
