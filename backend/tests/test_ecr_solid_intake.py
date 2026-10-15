"""ECR-solid §1 intake (switch SCOPING_V2): live-change check, minimal C11
(a newer index is never refused, it supersedes inside the change), "what
changed" at triage, C9 (full_ecr hands over: customer files, Sales owner,
notice) and the follow-ups on an impacted item (rechecks for every routed
department that had submitted, the lead's and Sales' questions, the
customer-driven flip of an internal change).
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.change import (
    ChangeAssessment, ChangeAttachment, ChangeChangelog, ChangeImpactedItem, ChangeRequest,
)
from app.models.notification import Notification
from app.models.part import PartRevision, RevisionFile
from app.models.revision_intake import ChangeRecheck, RevisionIntake
from app.models.workflow import ProjectResponsible
from tests.test_revision_intake import (  # noqa: F401  (fixture)
    API, _auth, _decide, _intake, _receive, world,
)

pytestmark = pytest.mark.asyncio

WHAT = {"what_changed": ["geometry", "material"], "what_changed_ref": "Compare report CR-118"}


async def _decide_v2(client, intake_id, route, key="dev", **extra):
    return await _decide(client, intake_id, route, key, **{**WHAT, **extra})


async def _team(session_factory, world):
    """The project's Sales contact (ri-sales)."""
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=world["seed"]["project_id"],
                                 department_id=world["depts"]["Sales"],
                                 user_id=world["users"]["sales"]))
        await s.commit()


async def _change_carrying(session_factory, world, status, *, customer=True,
                           submitted=("Tool Engineer",), routed=("Tool Engineer",
                                                                 "Packaging Engineer"),
                           finalized=(), deadline=True):
    """A change in `status` carrying the part on its active index, with the
    routed departments' assessments (some submitted, some finalized)."""
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=world["seed"]["project_id"], title=f"Live {status}",
            change_type="physical_part", raised_by=world["seed"]["admin_id"],
            customer_relevant=customer)
        change.status = status
        change.lead_id = world["seed"]["admin_id"]
        if deadline and customer:
            change.required_by_date = datetime(2026, 12, 1, 12)
        s.add(ChangeImpactedItem(change_id=change.id, part_id=world["part_id"],
                                 is_lead=True, eng_level_before="E1",
                                 created_by=world["seed"]["admin_id"]))
        for name in routed:
            did = world["depts"][name]
            done = name in submitted
            s.add(ChangeAssessment(
                change_id=change.id, department_id=did, rasic_letter="R",
                verdict="feasible" if done else "pending",
                status="submitted" if done else "active",
                submitted_at=datetime.utcnow() if done else None,
                details=('{"costing_finalized_at": "%s", "costing_finalized_by": 1}'
                         % datetime.utcnow().isoformat()) if name in finalized else None))
        await s.commit()
        return change.id


async def _followups(client, cid, key="admin"):
    r = await client.get(f"{API}/changes/{cid}/index-followups",
                         headers=await _auth(client, key))
    assert r.status_code == 200, r.text
    return r.json()


async def _tasks(client, key, kind, cid):
    r = await client.get(f"{API}/changes/my-tasks", headers=await _auth(client, key))
    assert r.status_code == 200, r.text
    return [t for t in r.json() if t["kind"] == kind and t["change_id"] == cid]


# ----------------------------------------------------------------------
# What changed
# ----------------------------------------------------------------------
async def test_what_changed_is_required_and_needs_evidence(client, world):
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "engineering_review", what_changed=[])
    assert r.status_code == 400 and "What changed" in r.json()["detail"]
    r = await _decide(client, i["id"], "engineering_review",
                      what_changed=["geometry"], what_changed_ref="ok")
    assert r.status_code == 400 and "says nothing" in r.json()["detail"]
    r = await _decide(client, i["id"], "engineering_review", what_changed=["none"])
    assert r.status_code == 400 and "No visible change" in r.json()["detail"]
    r = await _decide(client, i["id"], "engineering_review",
                      what_changed=["none", "geometry"], no_change_reason="title block")
    assert r.status_code == 400
    r = await _decide(client, i["id"], "engineering_review", what_changed=["none"],
                      no_change_reason="Title block only, same geometry")
    assert r.status_code == 200, r.text
    assert r.json()["what_changed"] == ["none"]


async def test_administrative_needs_no_what_changed(client, world):
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "administrative", reason="Re-upload, no change")
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------
# Live change check
# ----------------------------------------------------------------------
async def test_a_live_change_is_suggested_and_full_ecr_needs_a_reason_pick(
        client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "in_assessment")
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    assert i["suggested_route"] == "attach_ecr"
    assert i["live_change"]["id"] == cid and i["live_change"]["status"] == "in_assessment"
    # negative: full_ecr anyway without the reason pick (a free text is not it)
    r = await _decide_v2(client, i["id"], "full_ecr", reason="I want my own")
    assert r.status_code == 400 and "already carries" in r.json()["detail"]
    r = await _decide_v2(client, i["id"], "full_ecr", live_change_reason="separate_topic")
    assert r.status_code == 200, r.text
    new_id = r.json()["change_id"]
    async with session_factory() as s:
        new, live = await s.get(ChangeRequest, new_id), await s.get(ChangeRequest, cid)
        assert new.related_change_id == cid and live.related_change_id == new_id


async def test_attach_to_the_live_change_needs_no_reason(client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "scoping", routed=())
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide_v2(client, i["id"], "attach_ecr", change_id=cid)
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------
# Minimal C11: a newer index is never refused; it supersedes in the change
# ----------------------------------------------------------------------
async def test_newer_index_supersedes_inside_the_change(client, session_factory, world):
    await _team(session_factory, world)
    first = (await _receive(client, world["part_id"], statement="official",
                            customer_index="C")).json()
    i = await _intake(client, world["part_id"])
    cid = (await _decide_v2(client, i["id"], "full_ecr")).json()["change_id"]
    # the newer index is received (it used to be refused while C was linked)
    r = await _receive(client, world["part_id"], statement="official", customer_index="D")
    assert r.status_code == 201, r.text
    second = r.json()
    d = await _intake(client, world["part_id"])
    assert d["revision_id"] == second["id"]
    assert d["suggested_route"] == "attach_ecr" and d["live_change"]["id"] == cid
    r = await _decide_v2(client, d["id"], "attach_ecr", change_id=cid)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.resulting_revision_id == second["id"]
        old = await s.get(PartRevision, first["id"])
        assert old.status == "archived"
        old_intake = await s.get(RevisionIntake, i["id"])
        assert old_intake.status == "superseded" and old_intake.superseded_by_id == d["id"]
        kinds = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
        assert "intake_replaced" in kinds
    # the change is captured: no rechecks, but the follow-up is recorded
    f = await _followups(client, cid)
    assert f[0]["from_revision"] == first["revision_name"]
    assert f[0]["to_revision"] == second["revision_name"] and f[0]["rechecks"] == []


async def test_switch_off_still_refuses_the_newer_index(
        client, session_factory, world, monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    assert (await _decide(client, i["id"], "full_ecr")).status_code == 200
    r = await _receive(client, world["part_id"], statement="official")
    assert r.status_code == 409 and "linked to" in r.json()["detail"]


async def test_spawned_internal_minor_is_replaced_in_implementation(
        client, session_factory, world):
    """C11: the internal minor the change spawned at implementation gives way
    to the customer's newer index (check workflow cancelled, archived)."""
    cid = await _change_carrying(session_factory, world, "in_implementation",
                                 routed=())
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["impacted_items"])
        await ChangeService.spawn_ecn_revisions(s, change, world["users"]["dev"])
        await s.commit()
        minor_id = change.impacted_items[0].resulting_revision_id
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    r = await _decide_v2(client, i["id"], "attach_ecr", change_id=cid)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.resulting_revision_id == i["revision_id"]
        assert (await s.get(PartRevision, minor_id)).status == "archived"


# ----------------------------------------------------------------------
# C9: full_ecr hands over
# ----------------------------------------------------------------------
async def test_full_ecr_links_files_names_sales_and_tells_them(
        client, session_factory, world):
    await _team(session_factory, world)
    rev = (await _receive(client, world["part_id"], statement="official")).json()
    async with session_factory() as s:
        s.add(RevisionFile(revision_id=rev["id"], filename="drawing D.pdf",
                           file_path="/tmp/ecr-solid-drawing-d.pdf", file_type="drawing",
                           file_size=10, mime_type="application/pdf", file_hash="1" * 64,
                           uploaded_by=world["seed"]["admin_id"]))
        await s.commit()
    i = await _intake(client, world["part_id"])
    r = await _decide_v2(client, i["id"], "full_ecr")
    assert r.status_code == 200, r.text
    cid = r.json()["change_id"]
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.sales_owner_id == world["users"]["sales"]
        atts = (await s.execute(select(ChangeAttachment).where(
            ChangeAttachment.change_id == cid))).scalars().all()
        assert [(a.kind, a.filename, a.stored_path) for a in atts] == [
            ("customer_file", "drawing D.pdf", "/tmp/ecr-solid-drawing-d.pdf")]
        missing = await ChangeService.kickoff_missing(s, change)
        assert "at least one attachment" not in missing and "quote deadline" in missing
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == world["users"]["sales"],
            Notification.title.like("New customer index%")))).scalars().all()
        assert len(notes) == 1
    # deleting the linked file from the change never removes the revision's file
    async with session_factory() as s:
        att = (await s.execute(select(ChangeAttachment).where(
            ChangeAttachment.change_id == cid))).scalar_one()
        change = await s.get(ChangeRequest, cid)
        assert await ChangeService.delete_attachment(s, change, att, 1) is None


# ----------------------------------------------------------------------
# Follow-ups on an impacted item
# ----------------------------------------------------------------------
async def _attach_new_index(client, world, cid, **what):
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    body = {**WHAT, **what}
    r = await _decide(client, i["id"], "attach_ecr", change_id=cid, **body)
    assert r.status_code == 200, r.text
    return i


async def test_rechecks_go_to_the_departments_that_submitted(
        client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "in_assessment",
                                 finalized=("Tool Engineer",))
    i = await _attach_new_index(client, world, cid)
    f = (await _followups(client, cid))[0]
    assert f["from_revision"] == "E1"
    assert [r["department_name"] for r in f["rechecks"]] == ["Tool Engineer"]
    rid = f["rechecks"][0]["id"]
    assert f["rechecks"][0]["areas"] == ["geometry", "material"]
    assert f["lead_open"] is True and f["deadline_open"] is True
    # the Tool Engineer sees the task; Packaging (not submitted) has none
    assert len(await _tasks(client, "tool", "assessment_recheck", cid)) == 1
    assert await _tasks(client, "pack", "assessment_recheck", cid) == []
    url = f"{API}/changes/{cid}/rechecks/{rid}/answer"
    good = [{"area": "geometry", "effect": True, "what": "Rib 2 mm higher: slider",
             "evidence": "Compare report CR-118 p.3"},
            {"area": "material", "effect": False, "ref": "Checklist row M-4"}]
    # negatives: another department; an area left out; 'no effect' without a ref
    r = await client.post(url, json={"answers": good}, headers=await _auth(client, "pack"))
    assert r.status_code == 403
    r = await client.post(url, json={"answers": good[:1]}, headers=await _auth(client, "tool"))
    assert r.status_code == 400 and "every changed area" in r.json()["detail"]
    r = await client.post(url, json={"answers": [good[0], {"area": "material",
                                                            "effect": False, "ref": "ok"}]},
                          headers=await _auth(client, "tool"))
    assert r.status_code == 400
    r = await client.post(url, json={"answers": good}, headers=await _auth(client, "tool"))
    assert r.status_code == 200, r.text
    rc = r.json()[0]["rechecks"][0]
    assert rc["status"] == "answered" and rc["effect"] is True
    assert await _tasks(client, "tool", "assessment_recheck", cid) == []
    # effect before the quote: the finalized costing reopened
    from app.services import early_costing
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["assessments"])
        assert not early_costing.is_finalized(change, world["depts"]["Tool Engineer"])
    # answered once
    r = await client.post(url, json={"answers": good}, headers=await _auth(client, "tool"))
    assert r.status_code == 400


async def test_no_visible_change_makes_no_rechecks(client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "in_assessment")
    await _attach_new_index(client, world, cid, what_changed=["none"],
                            what_changed_ref=None,
                            no_change_reason="Title block only, same geometry")
    f = (await _followups(client, cid))[0]
    assert f["rechecks"] == [] and f["lead_open"] is True


async def test_an_effect_after_the_quote_is_a_scope_change(client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "quoted")
    await _attach_new_index(client, world, cid, what_changed=["tolerance"])
    rid = (await _followups(client, cid))[0]["rechecks"][0]["id"]
    r = await client.post(f"{API}/changes/{cid}/rechecks/{rid}/answer", json={
        "answers": [{"area": "tolerance", "effect": True, "what": "Tighter flatness 0.2",
                     "evidence": "Drawing D zone C4"}]}, headers=await _auth(client, "tool"))
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.scope_changed_after_quote is True
        assert world["depts"]["Tool Engineer"] in change.scope_change_department_ids
    assert len(await _tasks(client, "tool", "costing_update", cid)) == 1


async def test_the_lead_answers_whether_the_index_adds_parts(client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "in_assessment")
    i = await _attach_new_index(client, world, cid)
    rows = await _tasks(client, "admin", "index_decision", cid)
    assert len(rows) == 1
    url = f"{API}/changes/{cid}/index-followups/{i['id']}/scope"
    # negatives: not the run team; yes without naming what
    assert (await client.post(url, json={"answer": "no"},
                              headers=await _auth(client, "tool"))).status_code == 403
    assert (await client.post(url, json={"answer": "yes"},
                              headers=await _auth(client, "admin"))).status_code == 400
    r = await client.post(url, json={"answer": "no"}, headers=await _auth(client, "admin"))
    assert r.status_code == 200, r.text
    assert r.json()[0]["lead_open"] is False
    assert await _tasks(client, "admin", "index_decision", cid) == []


async def test_c5_lists_open_rechecks_and_the_new_index_task(client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "costing")
    await _attach_new_index(client, world, cid)
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["assessments"])
        text = await ChangeService.costing_not_finalized_text(s, change)
    assert "Recheck on the new index: Tool Engineer" in text
    assert "New-index task" in text


async def test_sales_answers_whether_the_deadline_holds(client, session_factory, world):
    cid = await _change_carrying(session_factory, world, "in_assessment")
    i = await _attach_new_index(client, world, cid)
    assert len(await _tasks(client, "sales", "index_deadline", cid)) == 1
    url = f"{API}/changes/{cid}/index-followups/{i['id']}/deadline"
    # negatives: not Sales; holds without evidence; new date without a date
    assert (await client.post(url, json={"answer": "holds", "ref": "Mail 2026-10-15"},
                              headers=await _auth(client, "tool"))).status_code == 403
    assert (await client.post(url, json={"answer": "holds", "ref": "tbd"},
                              headers=await _auth(client, "sales"))).status_code == 400
    assert (await client.post(url, json={"answer": "new_date", "ref": "Mail 2026-10-15"},
                              headers=await _auth(client, "sales"))).status_code == 400
    # not asked yet: Assumed, confirm by a date; the task stays as a confirm
    r = await client.post(url, json={"answer": "not_asked"},
                          headers=await _auth(client, "sales"))
    assert r.status_code == 200, r.text
    assert r.json()[0]["deadline_open"] is True
    rows = await _tasks(client, "sales", "index_deadline_confirm", cid)
    assert len(rows) == 1 and rows[0]["due_date"]
    r = await client.post(url, json={"answer": "new_date", "ref": "Mail from buyer 10-16",
                                     "new_date": "2026-12-20T12:00:00"},
                          headers=await _auth(client, "sales"))
    assert r.status_code == 200, r.text
    assert r.json()[0]["deadline_open"] is False
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).required_by_date == datetime(2026, 12, 20, 12)


async def test_attach_to_an_internal_change_asks_customer_driven(
        client, session_factory, world):
    await _team(session_factory, world)
    cid = await _change_carrying(session_factory, world, "scoping", customer=False,
                                 routed=())
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    r = await _decide_v2(client, i["id"], "attach_ecr", change_id=cid)
    assert r.status_code == 400 and "customer-driven" in r.json()["detail"]
    r = await _decide_v2(client, i["id"], "attach_ecr", change_id=cid, customer_driven=True)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.customer_relevant is True and change.customer_flip_at is not None
        assert change.sales_owner_id == world["users"]["sales"]


# ----------------------------------------------------------------------
# L4 review: handed over, effect in quoting, every live change, the lead's row
# ----------------------------------------------------------------------
async def test_full_ecr_is_handed_over_to_scoping_and_sales_sets_the_deadline(
        client, session_factory, world):
    """C9: the new change goes to scoping (the incomplete capture logged,
    not overridden) so the lead scopes while Sales sets the quote deadline."""
    await _team(session_factory, world)
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    r = await _decide_v2(client, i["id"], "full_ecr")
    assert r.status_code == 200, r.text
    cid = r.json()["change_id"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.status == "scoping" and change.required_by_date is None
        logged = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "handover_logged"))).scalars().all()
        assert len(logged) == 1 and "quote deadline" in logged[0].action_description
    rows = await _tasks(client, "sales", "set_quote_deadline", cid)
    assert len(rows) == 1


async def test_an_effect_while_quoting_reopens_costing(client, session_factory, world):
    """Before the offer is sent (quoting) an effect reopens the department's
    costing: the change steps back to costing, no scope change."""
    cid = await _change_carrying(session_factory, world, "quoting",
                                 routed=("Tool Engineer",), finalized=("Tool Engineer",))
    await _attach_new_index(client, world, cid, what_changed=["tolerance"])
    rid = (await _followups(client, cid))[0]["rechecks"][0]["id"]
    r = await client.post(f"{API}/changes/{cid}/rechecks/{rid}/answer", json={
        "answers": [{"area": "tolerance", "effect": True, "what": "Tighter flatness 0.2",
                     "evidence": "Drawing D zone C4"}]}, headers=await _auth(client, "tool"))
    assert r.status_code == 200, r.text
    from app.services import early_costing
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["assessments"])
        assert change.status == "costing"
        assert not change.scope_changed_after_quote
        assert not early_costing.is_finalized(change, world["depts"]["Tool Engineer"])


async def test_every_live_change_on_the_part_is_named_and_its_lead_told(
        client, session_factory, world):
    older = await _change_carrying(session_factory, world, "quoted", routed=())
    newer = await _change_carrying(session_factory, world, "costing", routed=())
    async with session_factory() as s:
        (await s.get(ChangeRequest, older)).lead_id = world["users"]["pack"]
        await s.commit()
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    assert i["live_change"]["id"] == newer
    assert [c["id"] for c in i["other_live_changes"]] == [older]
    r = await _decide_v2(client, i["id"], "attach_ecr", change_id=newer)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == world["users"]["pack"],
            Notification.kind == "index_other_change"))).scalars().all()
    assert len(notes) == 1 and "check" in notes[0].title


async def test_lead_question_on_an_index_attached_in_scoping_starts_at_proceed(
        client, session_factory, world):
    """Attached during scoping, the lead's question is owed from the entry
    into assessment: not overdue at birth, and it names the new index."""
    from datetime import timedelta
    cid = await _change_carrying(session_factory, world, "scoping", routed=())
    i = await _attach_new_index(client, world, cid)
    async with session_factory() as s:
        intake = await s.get(RevisionIntake, i["id"])
        intake.decided_at = datetime.utcnow() - timedelta(days=20)
        change = await s.get(ChangeRequest, cid)
        change.status = "in_assessment"
        s.add(ChangeChangelog(change_id=cid, action="status_changed", field_name="status",
                              old_value='"scoping"', new_value='"in_assessment"',
                              action_description="scoping -> in_assessment",
                              performed_by=world["seed"]["admin_id"],
                              performed_at=datetime.utcnow()))
        await s.commit()
    rows = await _tasks(client, "admin", "index_decision", cid)
    assert len(rows) == 1 and rows[0]["overdue"] is False
    assert "->" in rows[0]["reason"] and "index" not in rows[0]["reason"].split("->")[1]
