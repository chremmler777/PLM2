"""Revision intake review fixes (spec §17a): an index only ever rides on the
change its intake is linked to.

- superseded / re-triaged: the dead change lets go of the index (item link
  cleared, noted in its changelog), and a reopened change cannot release it;
- a cancelled / rejected change puts the index back into My Tasks and tells
  Development;
- rejecting the pending revision closes its intake for good;
- package confirm maps IntakeError to 409, preview reads a re-sent waiting
  index as "unchanged";
- intake and review notifications stay inside the part's organization;
- reset_1994_e1 --delete-others removes the intakes of deleted revisions.
"""
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeChangelog, ChangeImpactedItem, ChangeRequest
from app.models.entities import Organization, User
from app.models.notification import Notification
from app.models.part import Part, PartRevision
from app.models.revision_intake import RevisionIntake
from app.models.workflow import UserDepartment
from tests.conftest import ENGINEER_PASSWORD
from tests.test_revision_intake import API, _auth, _decide, _intake, _receive, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _tr(client, cid, **body):
    return await client.post(f"{API}/changes/{cid}/transition", json=body,
                             headers=await _auth(client, "admin"))


async def _items(s, part_id):
    return (await s.execute(select(ChangeImpactedItem.change_id, ChangeImpactedItem.resulting_revision_id)
                            .where(ChangeImpactedItem.part_id == part_id))).all()


async def _actions(s, cid):
    return [(c.action, c.action_description) for c in (await s.execute(
        select(ChangeChangelog).where(ChangeChangelog.change_id == cid))).scalars()]


async def _release(session_factory, cid, user_id):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await s.refresh(change, ["impacted_items"])
        await ChangeService.release(s, change, user_id)
        await s.commit()


# ----------------------------------------------------------------------
# P2-1 superseded / re-triaged index never rides on the dead change
# ----------------------------------------------------------------------
async def test_superseded_index_leaves_the_rejected_change_and_is_never_released(
        client, session_factory, world):
    from app.services.change_service import ChangeError
    from app.services.revision_intake_service import IntakeError, RevisionIntakeService
    first = (await _receive(client, world["part_id"], statement="official", customer_index="B")).json()
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    r = await _tr(client, cid, to_status="rejected", rejection_reason="customer withdrew")
    assert r.status_code == 200, r.text
    second = (await _receive(client, world["part_id"], statement="official", customer_index="C")).json()
    async with session_factory() as s:
        assert (await s.get(PartRevision, first["id"])).status == "archived"
        assert (await s.get(RevisionIntake, i["id"])).status == "superseded"
        # the dead change let go of the index, and says so
        assert await _items(s, world["part_id"]) == [(cid, None)]
        assert (await s.get(PartRevision, first["id"])).originating_change_id is None
        log = [d for a, d in await _actions(s, cid) if a == "intake_unlinked"]
        assert log and first["revision_name"] in log[0] and "superseded" in log[0]
        # reopened: nothing to release, the old index stays archived
        (await s.get(ChangeRequest, cid)).status = "scoping"
        await s.commit()
    await _release(session_factory, cid, world["users"]["dev"])
    async with session_factory() as s:
        part = await s.get(Part, world["part_id"])
        assert part.active_revision_id == world["e1"]
        # a link that survived (older data) is refused with a clear blocker
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        item.resulting_revision_id = first["id"]
        await s.commit()
    with pytest.raises(ChangeError) as e:
        await _release(session_factory, cid, world["users"]["dev"])
    assert str(e.value).startswith(
        f"Index {first['revision_name']} was superseded by {second['revision_name']}; re-link or remove")
    async with session_factory() as s:
        rev = await s.get(PartRevision, first["id"])
        change = await s.get(ChangeRequest, cid)
        with pytest.raises(IntakeError):
            await RevisionIntakeService.activate(s, rev, world["users"]["dev"], change=change)
        assert (await s.get(Part, world["part_id"])).active_revision_id == world["e1"]


async def test_retriaged_index_rides_on_one_change_only(client, session_factory, world):
    from app.services.change_service import ChangeError
    rev = (await _receive(client, world["part_id"], statement="official", customer_index="B")).json()
    i = await _intake(client, world["part_id"])
    a = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    r = await _tr(client, a, to_status="rejected", rejection_reason="no")
    assert r.status_code == 200, r.text
    r = await _decide(client, i["id"], "full_ecr", reason="again")
    assert r.status_code == 200, r.text
    b = r.json()["change_id"]
    async with session_factory() as s:
        rows = await _items(s, world["part_id"])
        assert sorted(rows) == sorted([(a, None), (b, rev["id"])])
        assert any(x == "intake_unlinked" and "triaged again" in d for x, d in await _actions(s, a))
        assert (await s.get(PartRevision, rev["id"])).originating_change_id == b
        # older data: the dead change still carries the link, and is reopened
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == a))).scalar_one()
        item.resulting_revision_id = rev["id"]
        (await s.get(ChangeRequest, a)).status = "scoping"
        b_number = (await s.get(ChangeRequest, b)).change_number
        await s.commit()
    with pytest.raises(ChangeError) as e:
        await _release(session_factory, a, world["users"]["dev"])
    assert f"was re-triaged to {b_number}; re-link or remove" in str(e.value)
    # the change it belongs to releases it
    await _release(session_factory, b, world["users"]["dev"])
    async with session_factory() as s:
        assert (await s.get(Part, world["part_id"])).active_revision_id == rev["id"]


# ----------------------------------------------------------------------
# P2-2 a dead change puts the index back into My Tasks, Development told
# ----------------------------------------------------------------------
async def test_cancelled_change_puts_index_back_to_triage_and_notifies(client, session_factory, world):
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "dev"))).json()
    assert i["id"] not in [x["id"] for x in my["triage"]]
    r = await _tr(client, cid, to_status="cancelled", cancellation_reason="customer dropped it")
    assert r.status_code == 200, r.text
    one = (await client.get(f"{API}/intakes/{i['id']}", headers=await _auth(client, "dev"))).json()
    assert one["needs_triage"] is True
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "dev"))).json()
    assert i["id"] in [x["id"] for x in my["triage"]]
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == world["users"]["dev"],
            Notification.subject_key.like(f"intake:{i['id']}:retriage%")))).scalars().all()
        assert len(notes) == 1 and "Triage again" in notes[0].title
        assert "cancelled" in notes[0].body
    # triaged again: gone from My Tasks
    r = await _decide(client, i["id"], "full_ecr", reason="new change")
    assert r.status_code == 200, r.text
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "dev"))).json()
    assert i["id"] not in [x["id"] for x in my["triage"]]


async def test_rejected_change_notifies_development(client, session_factory, world):
    await _receive(client, world["part_id"], statement="official")
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    r = await _tr(client, cid, to_status="rejected", rejection_reason="too expensive")
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.subject_key.like(f"intake:{i['id']}:retriage%")))).scalars().all()
        assert [n.user_id for n in notes] == [world["users"]["dev"]]
        assert "rejected" in notes[0].body


# ----------------------------------------------------------------------
# P3 rejecting the pending revision closes its intake
# ----------------------------------------------------------------------
async def test_rejecting_pending_revision_closes_its_intake(client, session_factory, world):
    from app.services.revision_intake_service import IntakeError, RevisionIntakeService
    rev = (await _receive(client, world["part_id"])).json()
    r = await client.post(f"{API}/parts/{world['part_id']}/revisions/{rev['id']}/reject",
                          json={}, headers=await _auth(client, "eng"))
    assert r.status_code == 200, r.text
    i = await _intake(client, world["part_id"])
    assert i["status"] == "rejected" and i["needs_triage"] is False and i["waiting"] is False
    assert i["revision_status"] == "rejected"
    my = (await client.get(f"{API}/intakes/my", headers=await _auth(client, "dev"))).json()
    assert my["triage"] == []
    r = await _decide(client, i["id"], "administrative", reason="x")
    assert r.status_code == 400 and "rejected" in r.json()["detail"]
    async with session_factory() as s:
        assert (await s.get(Part, world["part_id"])).active_revision_id == world["e1"]
        from app.models.part import RevisionChangelog
        acts = [c.action for c in (await s.execute(select(RevisionChangelog).where(
            RevisionChangelog.revision_id == rev["id"]))).scalars()]
        assert "intake_rejected" in acts
        with pytest.raises(IntakeError):
            await RevisionIntakeService.activate(s, await s.get(PartRevision, rev["id"]),
                                                 world["users"]["dev"])
    # a newer index is simply a new intake; the rejected one stays rejected
    r = await _receive(client, world["part_id"])
    assert r.status_code == 201, r.text
    async with session_factory() as s:
        assert (await s.get(RevisionIntake, i["id"])).status == "rejected"
        assert (await s.get(PartRevision, rev["id"])).status == "rejected"


async def test_rejecting_pending_revision_linked_to_live_change_is_refused(client, session_factory, world):
    rev = (await _receive(client, world["part_id"], statement="official")).json()
    i = await _intake(client, world["part_id"])
    (await _decide(client, i["id"], "full_ecr")).json()
    r = await client.post(f"{API}/parts/{world['part_id']}/revisions/{rev['id']}/reject",
                          json={}, headers=await _auth(client, "eng"))
    assert r.status_code == 400 and "linked to" in r.json()["detail"]
    async with session_factory() as s:
        assert (await s.get(RevisionIntake, i["id"])).status == "decided"


# ----------------------------------------------------------------------
# P3 customer package
# ----------------------------------------------------------------------
async def test_package_preview_resent_waiting_index_is_unchanged(client, world):
    h = await _auth(client, "eng")
    files = [("files", ("3CR807425B_cover.stp", b"ISO-10303-21;x", "model/step"))]
    pv = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package/preview",
                           headers=h, data={"statement": "official", "received_at": "2026-09-23"},
                           files=files)
    index = pv.json()["rows"][0]["customer_index"]
    assert index
    await _receive(client, world["part_id"], statement="official", customer_index=index)
    i = await _intake(client, world["part_id"])
    assert (await _decide(client, i["id"], "full_ecr")).status_code == 200
    # the waiting index is linked to a live change: the same file again is
    # "unchanged", no error
    pv = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package/preview",
                           headers=h, data={"statement": "official", "received_at": "2026-09-24"},
                           files=files)
    row = pv.json()["rows"][0]
    assert row["action"] == "unchanged" and row["error"] is None
    # a different index still cannot replace it
    pv = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package/preview",
                           headers=h, data={"statement": "official", "received_at": "2026-09-24",
                                            "package_index": "ZZ"},
                           files=[("files", ("3CR807425_cover.stp", b"x", "model/step"))])
    row = pv.json()["rows"][0]
    assert row["action"] == "error" and "linked to" in row["error"]


async def test_package_confirm_maps_intake_error_to_409(client, world, monkeypatch):
    from app.services.part_service import RevisionService
    from app.services.revision_intake_service import IntakeError

    async def boom(*a, **k):
        raise IntakeError("Index E2 is still pending and linked to CR-1")
    monkeypatch.setattr(RevisionService, "receive_customer_data", boom)
    h = await _auth(client, "eng")
    files = [("files", ("3CR807425B_cover.stp", b"ISO-10303-21;x", "model/step"))]
    rows = [{"filename": "3CR807425B_cover.stp", "part_id": world["part_id"],
             "customer_index": "B", "action": "new_major"}]
    r = await client.post(f"{API}/parts/{world['part_id']}/revisions/customer-package", headers=h,
                          data={"statement": "review", "received_at": "2026-09-23",
                                "rows": json.dumps(rows)}, files=files)
    assert r.status_code == 409 and "linked to" in r.json()["detail"]


# ----------------------------------------------------------------------
# P3 notifications stay inside the part's organization
# ----------------------------------------------------------------------
async def test_intake_and_review_notifications_only_in_the_parts_org(client, session_factory, world):
    async with session_factory() as s:
        other = Organization(name="Other Org", code="other-org", is_active=True)
        s.add(other)
        await s.flush()
        strangers = {}
        for key, dept in (("xdev", "Development"), ("xtool", "Tool Engineer")):
            u = User(organization_id=other.id, username=key, email=f"{key}@other.io",
                     full_name=key, role="engineer", is_active=True, mfa_enabled=False,
                     hashed_password=get_password_hash(ENGINEER_PASSWORD))
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=world["depts"][dept]))
            strangers[key] = u.id
        await s.commit()
    await _receive(client, world["part_id"])
    i = await _intake(client, world["part_id"])
    r = await _decide(client, i["id"], "engineering_review")
    assert r.status_code == 200, r.text
    cid = r.json()["change_id"]
    r = await client.post(f"{API}/changes/{cid}/impact/confirm", headers=await _auth(client, "dev"))
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        def q(kind):
            return select(Notification.user_id).where(Notification.kind == kind)
        intake_to = set((await s.execute(q("revision_intake"))).scalars().all())
        review_to = set((await s.execute(q("change_review"))).scalars().all())
    assert world["users"]["dev"] in intake_to and strangers["xdev"] not in intake_to
    assert world["users"]["tool"] in review_to and strangers["xtool"] not in review_to


# ----------------------------------------------------------------------
# P3 reset_1994_e1 --delete-others
# ----------------------------------------------------------------------
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reset_1994_e1.py"


def _script():
    spec = importlib.util.spec_from_file_location("reset_1994_e1", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_reset_script_deletes_intakes_of_deleted_revisions_first(client, session_factory, world):
    mod = _script()
    await _receive(client, world["part_id"], customer_index="B")
    await _receive(client, world["part_id"], customer_index="C")   # supersedes B
    async with session_factory() as s:
        rev_ids = list((await s.execute(select(PartRevision.id).where(
            PartRevision.part_id == world["part_id"]))).scalars().all())
        assert await mod.count_intakes(s, [world["part_id"]], rev_ids) == 2
        assert await mod.count_intakes(s, [], []) == 0
        # counting (the dry run) writes nothing
        assert len((await s.execute(select(RevisionIntake))).scalars().all()) == 2
        assert await mod.delete_intakes(s, [world["part_id"]], rev_ids) == 2
        await s.commit()
    async with session_factory() as s:
        assert (await s.execute(select(RevisionIntake))).scalars().all() == []


async def test_revisions_list_flags_the_pending_index(client, world):
    rev = (await _receive(client, world["part_id"])).json()
    rows = (await client.get(f"{API}/parts/{world['part_id']}/revisions",
                             headers=await _auth(client, "eng"))).json()
    assert {r["id"]: r["intake_pending"] for r in rows} == {world["e1"]: False, rev["id"]: True}


async def test_impact_tree_names_the_pending_index(client, world):
    rev = (await _receive(client, world["part_id"], statement="official", customer_index="005")).json()
    i = await _intake(client, world["part_id"])
    cid = (await _decide(client, i["id"], "full_ecr")).json()["change_id"]
    tree = (await client.get(f"{API}/changes/{cid}/impact-tree",
                             headers=await _auth(client, "admin"))).json()

    def find(nodes):
        for n in nodes:
            if n["part_id"] == world["part_id"]:
                return n
            hit = find(n["children"])
            if hit:
                return hit
    node = find(tree["tree"])
    assert node["resulting_revision_id"] == rev["id"]
    assert node["resulting_revision_label"] == f"{rev['revision_name']} · 005"
    assert node["resulting_revision_pending"] is True
