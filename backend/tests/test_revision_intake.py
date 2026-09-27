"""Revision intake (spec 2026-09-25 §17 / §17a): every new customer index is
captured and triaged by Development.

The gate (a new major is pending: in_review, active pointer unchanged), the
bypass for import scripts, the suggested route, the four routes (full_ecr,
attach_ecr, engineering_review, administrative), the shared activation on
release, the engineering review (answers, auto release, escalation), the
superseding rule, promote side effects at activation, the package batch,
the display fallbacks, My Tasks and the rights.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeChangelog, ChangeImpactedItem, ChangeRequest
from app.models.entities import User
from app.models.part import Part, PartRelation, PartRevision, RevisionFile
from app.models.revision_intake import ChangeReviewAnswer, RevisionIntake
from app.models.workflow import Department, UserDepartment
from app.services.part_service import PartService, RevisionService
from tests.conftest import ENGINEER_PASSWORD, login

pytestmark = pytest.mark.asyncio

API = "/api/v1"
ACTS = "X-Acts-As-Department"


@pytest.fixture
async def world(session_factory, seed):
    """Departments with one member each, an article with an active E1 and a
    tool producing it."""
    async with session_factory() as s:
        depts = {}
        for name in ("Development", "Tool Engineer", "Packaging Engineer", "APQP",
                     "Manufacturing Engineer", "Sales", "Project Manager"):
            d = Department(name=name, flow_type="action", is_active=True,
                           can_start_change=(name == "Sales"))
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in (("dev", "Development"), ("tool", "Tool Engineer"),
                          ("pack", "Packaging Engineer"), ("sales", "Sales")):
            u = User(organization_id=seed["org_id"], username=f"ri-{key}",
                     email=f"ri-{key}@test.io", full_name=f"RI {key}", role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = u.id
        admin = seed["admin_id"]
        art = await PartService.create_part(
            s, project_id=seed["project_id"], part_number="20-1994-001", name="Cover",
            part_type="internal_mfg", created_by=admin)
        art.customer_part_number = "3CR.807.425"
        tool = await PartService.create_part(
            s, project_id=seed["project_id"], part_number="199401", name="Cover tool",
            part_type="internal_mfg", created_by=admin, item_category="tool")
        await s.flush()
        s.add(PartRelation(from_part_id=tool.id, to_part_id=art.id,
                           relation_type="produces", created_by=admin))
        # an import script: no intake source, active at once
        e1 = await RevisionService.receive_customer_data(
            s, art.id, "review", date(2026, 9, 1), customer_index="A", created_by=admin)
        await s.commit()
        return {"depts": depts, "users": users, "part_id": art.id, "tool_id": tool.id,
                "e1": e1.id, "seed": seed}


async def _auth(client, key):
    if key == "admin":
        return await login(client, "admin@test.io")
    if key == "eng":
        return await login(client, "eng@test.io", ENGINEER_PASSWORD)
    return await login(client, f"ri-{key}@test.io", ENGINEER_PASSWORD)


async def _receive(client, pid, key="eng", **body):
    payload = {"statement": "review", "received_at": "2026-09-20", **body}
    return await client.post(f"{API}/parts/{pid}/revisions/customer-data",
                             json=payload, headers=await _auth(client, key))


async def _intake(client, pid, key="dev"):
    r = await client.get(f"{API}/intakes", params={"part_id": pid},
                         headers=await _auth(client, key))
    assert r.status_code == 200, r.text
    return r.json()["intakes"][0]


async def _decide(client, intake_id, route, key="dev", **extra):
    return await client.post(f"{API}/intakes/{intake_id}/decide",
                             json={"route": route, **extra}, headers=await _auth(client, key))


async def _part(session_factory, pid):
    async with session_factory() as s:
        return await s.get(Part, pid)


# ----------------------------------------------------------------------
# The gate
# ----------------------------------------------------------------------
async def test_new_index_is_pending_and_active_pointer_unchanged(client, session_factory, world):
    r = await _receive(client, world["part_id"], customer_index="B")
    assert r.status_code == 201, r.text
    rev = r.json()
    assert rev["revision_name"] == "E2" and rev["status"] == "in_review"
    assert (await _part(session_factory, world["part_id"])).active_revision_id == world["e1"]
    i = await _intake(client, world["part_id"])
    assert i["status"] == "pending" and i["source"] == "customer_data"
    assert i["revision_name"] == "E2" and i["active_revision_name"] == "E1"
    assert i["suggested_route"] == "engineering_review" and i["needs_triage"]
    # the bom tree still shows E1
    tree = (await client.get(f"{API}/parts/{world['part_id']}/bom-tree",
                             headers=await _auth(client, "eng"))).json()
    assert tree["revision_name"] == "E1"
    # project structure flags the pending revision
    st = (await client.get(f"{API}/parts/project/{world['seed']['project_id']}/structure",
                           headers=await _auth(client, "eng")))
    if st.status_code == 200:
        art = next(a for a in st.json()["articles"] if a["part_id"] == world["part_id"])
        assert art["intake_pending"] is True
        assert [x["intake_pending"] for x in art["revisions"]] == [False, True]


async def test_upload_source_is_recorded(client, world):
    r = await _receive(client, world["part_id"], source="upload")
    assert r.status_code == 201, r.text
    assert (await _intake(client, world["part_id"]))["source"] == "upload"


async def test_scripts_bypass_the_gate(session_factory, world):
    async with session_factory() as s:
        rev = await RevisionService.receive_customer_data(
            s, world["part_id"], "review", date(2026, 9, 21), created_by=world["seed"]["admin_id"])
        await s.commit()
        part = await s.get(Part, world["part_id"])
        assert part.active_revision_id == rev.id and rev.status == "approved"
        assert (await s.execute(select(RevisionIntake))).scalars().first() is None


async def test_suggested_routes(client, session_factory, world, seed):
    # official data -> full ECR
    r = await _receive(client, world["part_id"], statement="official")
    assert (await _intake(client, world["part_id"]))["suggested_route"] == "full_ecr"
    # first data on an rfq part -> administrative
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number="NEW-1",
                                          name="New", part_type="internal_mfg",
                                          created_by=seed["admin_id"])
        await s.commit()
        new_id = p.id
    assert (await _receive(client, new_id)).status_code == 201
    assert (await _intake(client, new_id))["suggested_route"] == "administrative"
    # a series part -> full ECR even for review data
    async with session_factory() as s:
        p = await s.get(Part, new_id)
        p.lifecycle_phase = "series"
        await s.commit()
    from app.services.revision_intake_service import suggest_route
    assert suggest_route("review", "series", True) == "full_ecr"
    assert suggest_route("review", "nominated", True) == "engineering_review"
    assert suggest_route("review", "rfq", False) == "administrative"
    assert suggest_route("official", "rfq", False) == "administrative"


# ----------------------------------------------------------------------
# Rights
# ----------------------------------------------------------------------
async def test_only_development_or_admin_decides(client, world):
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"], key="eng")
    assert i["can_decide"] is False
    r = await _decide(client, i["id"], "administrative", key="eng", reason="title block")
    assert r.status_code == 403, r.text
    r = await _decide(client, i["id"], "administrative", key="tool", reason="title block")
    assert r.status_code == 403
    # admin acting as Tool Engineer is Tool Engineer here
    admin_as_tool = {**await _auth(client, "admin"), ACTS: str(world["depts"]["Tool Engineer"])}
    r = await client.post(f"{API}/intakes/{i['id']}/decide", headers=admin_as_tool,
                          json={"route": "administrative", "reason": "title block"})
    assert r.status_code == 403
    admin_as_dev = {**await _auth(client, "admin"), ACTS: str(world["depts"]["Development"])}
    r = await client.post(f"{API}/intakes/{i['id']}/decide", headers=admin_as_dev,
                          json={"route": "administrative", "reason": "title block"})
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------
# administrative
# ----------------------------------------------------------------------
async def test_administrative_needs_reason_and_activates(client, session_factory, world):
    rev = (await _receive(client, world["part_id"])).json()
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "administrative")
    assert r.status_code == 400 and "reason" in r.json()["detail"].lower()
    r = await _decide(client, i["id"], "administrative", reason="Title block only")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "decided" and out["route"] == "administrative"
    assert out["activated_at"] is not None and out["waiting"] is False
    async with session_factory() as s:
        part = await s.get(Part, world["part_id"])
        new = await s.get(PartRevision, rev["id"])
        assert part.active_revision_id == rev["id"]
        assert new.status == "approved" and new.supersedes_revision_id == world["e1"]
    # a decided intake is not decided again
    assert (await _decide(client, i["id"], "administrative", reason="again")).status_code == 400


async def test_other_route_than_suggested_needs_reason(client, world):
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "full_ecr")
    assert r.status_code == 400 and "suggested" in r.json()["detail"]


# ----------------------------------------------------------------------
# full_ecr, release activation
# ----------------------------------------------------------------------
async def test_full_ecr_links_pending_revision_and_release_activates(client, session_factory, world):
    rev = (await _receive(client, world["part_id"], statement="official", customer_index="C")).json()
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "full_ecr")
    assert r.status_code == 200, r.text
    out = r.json()
    cid = out["change_id"]
    assert out["change_number"] and out["change_status"] == "captured"
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.origin == "customer" and change.customer_relevant
        assert "index 1" in change.description
        items = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalars().all()
        assert [(it.part_id, it.is_lead, it.resulting_revision_id) for it in items] == [
            (world["part_id"], True, rev["id"])]
        assert (await s.get(Part, world["part_id"])).active_revision_id == world["e1"]
    # the change list knows it came from an intake
    rows = (await client.get(f"{API}/changes", headers=await _auth(client, "admin"))).json()
    assert next(c for c in rows if c["id"] == cid)["from_intake"] is True
    # a newer index cannot supersede an index linked to a live change
    r = await _receive(client, world["part_id"], statement="official")
    assert r.status_code == 409 and "linked to" in r.json()["detail"]
    # the change's release activates exactly the linked revision
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["impacted_items"])
        await ChangeService.release(s, change, world["users"]["dev"])
        await s.commit()
    async with session_factory() as s:
        part = await s.get(Part, world["part_id"])
        new = await s.get(PartRevision, rev["id"])
        intake = await s.get(RevisionIntake, i["id"])
        assert part.active_revision_id == rev["id"] and new.status == "approved"
        assert new.supersedes_revision_id == world["e1"] and intake.activated_at is not None


async def test_spawn_skips_the_pending_customer_major(client, session_factory, world):
    rev = (await _receive(client, world["part_id"], statement="official")).json()
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["impacted_items"])
        await ChangeService.spawn_ecn_revisions(s, change, world["users"]["dev"])
        await s.commit()
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.resulting_revision_id == rev["id"]          # no ECN minor spawned


async def test_release_checklist_hints_from_linked_revisions(client, session_factory, world):
    rev = (await _receive(client, world["part_id"], statement="official")).json()
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    async with session_factory() as s:
        s.add(RevisionFile(revision_id=rev["id"], filename="d.pdf", file_path="/tmp/d.pdf",
                           file_type="drawing", file_size=1, mime_type="application/pdf",
                           file_hash="0" * 64, uploaded_by=world["seed"]["admin_id"]))
        await s.commit()
    from app.services.release_service import ReleaseService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["impacted_items"])
        hints = await ReleaseService.revision_hints(s, change)
    assert hints["index_updated"] == "20-1994-001 index 1 activated on release"
    assert hints["drawing_released"] == "20-1994-001 1: drawing on file"


# ----------------------------------------------------------------------
# attach_ecr
# ----------------------------------------------------------------------
async def test_attach_to_open_change_and_refuse_past_implementation(client, session_factory, world):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=world["seed"]["project_id"], title="Open change",
            change_type="physical_part", raised_by=world["seed"]["admin_id"],
            customer_relevant=True)
        closed = await ChangeService.create_change(
            s, project_id=world["seed"]["project_id"], title="Validating",
            change_type="physical_part", raised_by=world["seed"]["admin_id"],
            customer_relevant=True)
        closed.status = "in_validation"
        await s.commit()
        cid, vid = change.id, closed.id
    rev = (await _receive(client, world["part_id"])).json()
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "attach_ecr", reason="rides on the open change")
    assert r.status_code == 400 and "Choose" in r.json()["detail"]
    r = await _decide(client, i["id"], "attach_ecr", reason="x", change_id=vid)
    assert r.status_code == 400 and "in_validation" in r.json()["detail"]
    r = await _decide(client, i["id"], "attach_ecr", reason="rides on it", change_id=cid)
    assert r.status_code == 200, r.text
    assert r.json()["change_id"] == cid
    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.part_id == world["part_id"] and item.resulting_revision_id == rev["id"]
        assert item.eng_level_before == "E1"


async def _open_change(session_factory, world, status, *, confirmed=False):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=world["seed"]["project_id"], title=f"Open {status}",
            change_type="physical_part", raised_by=world["seed"]["admin_id"],
            customer_relevant=True)
        change.status = status
        if confirmed:
            change.impact_confirmed_at = datetime.utcnow()
            change.impact_confirmed_by = world["users"]["dev"]
        await s.commit()
        return change.id


async def test_attach_in_scoping_clears_the_impact_confirmation(
        client, session_factory, world):
    """Review 760bb129 finding 4: a part the intake adds to a locked set is
    an impacted-set edit: Development's confirmation is cleared, as for any
    other edit, so the set is confirmed again before assessment."""
    cid = await _open_change(session_factory, world, "scoping", confirmed=True)
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "attach_ecr", reason="rides on it", change_id=cid)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.impact_confirmed_at is None and change.impact_confirmed_by is None
        kinds = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
        assert "impact_confirmation_reset" in kinds


async def test_attach_after_the_quote_flags_the_scope_change(
        client, session_factory, world):
    """After the quote the part the intake adds changes the scope the offer
    covered: flagged like any post-quote edit, the intake's reason on it."""
    cid = await _open_change(session_factory, world, "quoted", confirmed=True)
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "attach_ecr", reason="customer sent index B",
                      change_id=cid)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.scope_changed_after_quote is True
        assert change.scope_change_reason == "customer sent index B"
        assert change.impact_confirmed_at is None
        kinds = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
        assert "scope_changed_after_quote" in kinds


async def test_attach_in_implementation_keeps_the_set_frozen(
        client, session_factory, world):
    """From implementation on the impacted set is frozen: the intake cannot
    add a part to it (start a full ECR), and nothing is written."""
    cid = await _open_change(session_factory, world, "in_implementation")
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "attach_ecr", reason="x", change_id=cid)
    assert r.status_code == 400, r.text
    assert "frozen" in r.json()["detail"] and "full ECR" in r.json()["detail"]
    async with session_factory() as s:
        items = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalars().all()
        assert items == []


# ----------------------------------------------------------------------
# engineering_review
# ----------------------------------------------------------------------
async def _review(client, session_factory, world):
    rev = (await _receive(client, world["part_id"])).json()
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "engineering_review")
    assert r.status_code == 200, r.text
    return r.json()["change_id"], rev, i


async def test_engineering_review_all_no_impact_activates_and_closes(client, session_factory, world):
    cid, rev, i = await _review(client, session_factory, world)
    change = (await client.get(f"{API}/changes/{cid}", headers=await _auth(client, "dev"))).json()
    assert change["origin"] == "engineering_review" and change["status"] == "scoping"
    assert change["from_intake"] is True
    # no review before the impact lock
    st = (await client.get(f"{API}/changes/{cid}/review", headers=await _auth(client, "dev"))).json()
    assert st["answers"] == [] and st["impact_locked"] is False
    # the review never goes to assessment
    r = await client.post(f"{API}/changes/{cid}/transition", headers=await _auth(client, "admin"),
                          json={"to_status": "in_assessment"})
    assert r.status_code == 400 and "escalate" in r.json()["detail"]
    r = await client.post(f"{API}/changes/{cid}/impact/confirm", headers=await _auth(client, "dev"))
    assert r.status_code == 200, r.text
    st = (await client.get(f"{API}/changes/{cid}/review", headers=await _auth(client, "dev"))).json()
    names = [a["department_name"] for a in st["answers"]]
    assert names == ["Development", "Tool Engineer", "Packaging Engineer"]
    tool_row = next(a for a in st["answers"] if a["department_name"] == "Tool Engineer")
    assert [o["number"] for o in tool_row["objects"]] == ["199401"]
    # rights: only the asked department's members answer
    r = await client.post(f"{API}/changes/{cid}/review/answers", headers=await _auth(client, "pack"),
                          json={"department_id": world["depts"]["Tool Engineer"], "answer": "no_impact"})
    assert r.status_code == 403
    # "impact" needs a note
    r = await client.post(f"{API}/changes/{cid}/review/answers", headers=await _auth(client, "tool"),
                          json={"department_id": world["depts"]["Tool Engineer"], "answer": "impact"})
    assert r.status_code == 400
    for key, dept in (("dev", "Development"), ("tool", "Tool Engineer")):
        r = await client.post(f"{API}/changes/{cid}/review/answers", headers=await _auth(client, key),
                              json={"department_id": world["depts"][dept], "answer": "no_impact"})
        assert r.status_code == 200, r.text
    assert (await _part(session_factory, world["part_id"])).active_revision_id == world["e1"]
    # my tasks: Packaging still owes its answer
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "pack"))).json()
    assert [x["change_id"] for x in my["review"]] == [cid]
    r = await client.post(f"{API}/changes/{cid}/review/answers", headers=await _auth(client, "pack"),
                          json={"department_id": world["depts"]["Packaging Engineer"],
                                "answer": "no_impact", "note": "same box"})
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.status == "closed" and change.released_at is not None
        part = await s.get(Part, world["part_id"])
        assert part.active_revision_id == rev["id"]
        assert (await s.get(RevisionIntake, i["id"])).activated_at is not None
        actions = [c.action for c in (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid))).scalars()]
        assert "review_released" in actions


async def test_engineering_review_impact_escalates_to_full_ecr(client, session_factory, world):
    cid, rev, i = await _review(client, session_factory, world)
    await client.post(f"{API}/changes/{cid}/impact/confirm", headers=await _auth(client, "dev"))
    r = await client.post(f"{API}/changes/{cid}/review/answers", headers=await _auth(client, "tool"),
                          json={"department_id": world["depts"]["Tool Engineer"], "answer": "impact",
                                "note": "insert change in the tool"})
    assert r.status_code == 200, r.text
    acts = (await client.get(f"{API}/changes/{cid}/my-actions", headers=await _auth(client, "dev"))).json()
    kinds = [a["kind"] for a in acts["actions"]] if isinstance(acts, dict) else [a["kind"] for a in acts]
    assert "review_escalate" in kinds
    r = await client.post(f"{API}/changes/{cid}/review/escalate", headers=await _auth(client, "tool"), json={})
    assert r.status_code == 403
    r = await client.post(f"{API}/changes/{cid}/review/escalate", headers=await _auth(client, "dev"), json={})
    assert r.status_code == 200, r.text
    assert r.json()["escalated"] is True and len(r.json()["answers"]) == 3
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.origin == "customer" and change.customer_relevant and change.status == "scoping"
        assert (await s.get(RevisionIntake, i["id"])).escalated_at is not None
        assert (await s.get(Part, world["part_id"])).active_revision_id == world["e1"]
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid, ChangeChangelog.action == "review_escalated"))).scalar_one()
        assert "insert change in the tool" in log.action_description


async def test_escalation_without_impact_needs_a_note(client, session_factory, world):
    cid, _, _ = await _review(client, session_factory, world)
    r = await client.post(f"{API}/changes/{cid}/review/escalate", headers=await _auth(client, "dev"), json={})
    assert r.status_code == 400
    r = await client.post(f"{API}/changes/{cid}/review/escalate", headers=await _auth(client, "dev"),
                          json={"note": "customer asked for a quote"})
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------
# superseding, re-triage
# ----------------------------------------------------------------------
async def test_newer_index_supersedes_pending_one(client, session_factory, world):
    first = (await _receive(client, world["part_id"], customer_index="B")).json()
    second = (await _receive(client, world["part_id"], customer_index="C")).json()
    assert second["revision_name"] == "E3"
    async with session_factory() as s:
        rows = (await s.execute(select(RevisionIntake).order_by(RevisionIntake.id))).scalars().all()
        assert [r.status for r in rows] == ["superseded", "pending"]
        assert rows[0].superseded_by_id == rows[1].id
        assert (await s.get(PartRevision, first["id"])).status == "archived"
    i = await _intake(client, world["part_id"])   # newest first
    assert i["revision_name"] == "E3"
    old = (await client.get(f"{API}/intakes/{i['id'] - 1}", headers=await _auth(client, "dev"))).json()
    assert old["status"] == "superseded" and old["needs_triage"] is False


async def test_cancelled_link_allows_supersede_and_retriage(client, session_factory, world):
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).status = "cancelled"
        await s.commit()
    again = (await client.get(f"{API}/intakes/{i['id']}", headers=await _auth(client, "dev"))).json()
    assert again["needs_triage"] is True and again["can_decide"] is True
    r = await _decide(client, i["id"], "administrative", reason="customer withdrew the change")
    assert r.status_code == 200, r.text
    assert r.json()["activated_at"] is not None


# ----------------------------------------------------------------------
# promote
# ----------------------------------------------------------------------
async def test_promote_side_effects_wait_for_activation(client, session_factory, world):
    h = await _auth(client, "eng")
    p1 = (await client.post(f"{API}/parts/{world['part_id']}/revisions/proposals", headers=h,
                            json={"parent_revision_id": world["e1"]})).json()
    p2 = (await client.post(f"{API}/parts/{world['part_id']}/revisions/proposals", headers=h,
                            json={"parent_revision_id": world["e1"]})).json()
    r = await client.post(f"{API}/parts/{world['part_id']}/revisions/{p1['id']}/promote", headers=h,
                          json={"statement": "review", "received_at": "2026-09-22"})
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(PartRevision, p1["id"])).status == "draft"
        assert (await s.get(PartRevision, p2["id"])).status == "draft"
    i = await _intake(client, world["part_id"])
    assert i["source"] == "promote"
    r = await _decide(client, i["id"], "administrative", reason="customer adopted E1.1 as is")
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(PartRevision, p1["id"])).status == "approved"
        assert (await s.get(PartRevision, p2["id"])).status == "rejected"


# ----------------------------------------------------------------------
# package, my tasks, lists
# ----------------------------------------------------------------------
async def test_package_creates_grouped_pending_intakes(client, session_factory, world):
    h = await _auth(client, "eng")
    files = [("files", ("3CR807425B_cover.stp", b"ISO-10303-21;x", "model/step"))]
    pv = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package/preview",
                           headers=h, data={"statement": "review", "received_at": "2026-09-23"},
                           files=files)
    assert pv.status_code == 200, pv.text
    row = pv.json()["rows"][0]
    assert row["action"] == "new_major" and row["current_revision"] == "E1"
    rows = [{"filename": row["filename"], "part_id": row["part_id"],
             "customer_index": row["customer_index"], "action": "new_major"}]
    import json
    r = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package", headers=h,
                          data={"statement": "review", "received_at": "2026-09-23",
                                "rows": json.dumps(rows)}, files=files)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["pending_count"] == 1 and out["created"][0]["pending"] is True
    i = await _intake(client, world["part_id"])
    assert i["source"] == "package" and i["batch_id"] == out["batch_id"] and i["file_count"] == 1
    # the preview now compares against the pending major
    pv = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package/preview",
                           headers=h, data={"statement": "review", "received_at": "2026-09-24"},
                           files=[("files", ("3CR807425B_cover.stp", b"x", "model/step"))])
    row = pv.json()["rows"][0]
    assert row["current_revision"] == "E2" and row["current_pending"] is True
    assert row["action"] == "unchanged"
    # Development sees it in My Tasks, others do not
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "dev"))).json()
    assert [x["id"] for x in my["triage"]] == [i["id"]]
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "tool"))).json()
    assert my["triage"] == []


async def test_list_filters(client, world):
    await _receive(client, world["part_id"])
    h = await _auth(client, "dev")
    r = await client.get(f"{API}/intakes", params={"project_id": world["seed"]["project_id"],
                                                    "status": "pending"}, headers=h)
    assert r.status_code == 200 and len(r.json()["intakes"]) == 1 and r.json()["can_triage"]
    r = await client.get(f"{API}/intakes", params={"status": "decided"}, headers=h)
    assert r.json()["intakes"] == []
    assert (await client.get(f"{API}/intakes/99999", headers=h)).status_code == 404
