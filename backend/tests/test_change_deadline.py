"""Task 9: Sales-settable required-by deadline — audited set + computed
on_track/at_risk/overdue state (change-scoped and ECN-scoped instances)."""
import pytest
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.change import ChangeRequest, ChangeChangelog
from app.models.entities import AuditLog
from app.models.workflow import WfInstance, WfTemplate, WfStage
from app.services.change_service import ChangeService


async def _mk_change(session, seed, **over):
    chg = ChangeRequest(
        change_number=over.pop("change_number", "C-DL-001"),
        title=over.pop("title", "Deadline test"),
        reason="y", change_type="physical_part",
        project_id=seed["project_id"], raised_by=seed["admin_id"],
        lead_id=over.pop("lead_id", seed["admin_id"]),
        **over,
    )
    session.add(chg)
    await session.flush()
    return chg


async def _mk_template_with_stages(session, n_stages):
    t = WfTemplate(name="Deadline Test Template", created_by=1)
    session.add(t)
    await session.flush()
    for i in range(1, n_stages + 1):
        session.add(WfStage(template_id=t.id, stage_order=i, name=f"Stage {i}"))
    await session.flush()
    return t


@pytest.mark.asyncio
async def test_patch_sets_required_by_and_audits(client, eng_auth, seed, session_factory):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Deadline PATCH", "reason": "r",
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]

    due = (datetime.utcnow() + timedelta(days=30)).isoformat()
    res = await client.patch(f"/api/v1/changes/{cid}", json={
        "required_by_date": due, "required_by_reason": "customer commitment",
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["required_by_date"] is not None
    assert body["required_by_reason"] == "customer commitment"

    res = await client.get(f"/api/v1/changes/{cid}/changelog", headers=eng_auth)
    assert res.status_code == 200, res.text
    entries = res.json()
    deadline_entries = [e for e in entries if e["action"] == "deadline_set"]
    assert len(deadline_entries) == 1

    # ChangelogResponse doesn't expose field_name/old/new — check the ORM row
    # directly for the audited-set detail (old->new, field name).
    async with session_factory() as session:
        rows = (await session.execute(
            select(ChangeChangelog).where(
                ChangeChangelog.change_id == cid,
                ChangeChangelog.action == "deadline_set",
            ))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.field_name == "required_by_date"
        assert row.old_value is None
        assert row.new_value is not None
        assert row.notes == "customer commitment"
        assert row.performed_by == seed["engineer_id"]


@pytest.mark.asyncio
async def test_patch_accepts_tz_aware_z_suffix_stored_naive(
        client, eng_auth, seed, session_factory):
    """Frontend sends required_by_date as tz-aware ISO-8601 with a "Z"
    suffix. On Postgres the column is TIMESTAMP WITHOUT TIME ZONE, and
    asyncpg 500s on a tz-aware value. The schema layer must normalize it
    to naive UTC before it reaches the DB layer."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Deadline Z-suffix", "reason": "r",
    }, headers=eng_auth)
    cid = res.json()["id"]

    res = await client.patch(f"/api/v1/changes/{cid}", json={
        "required_by_date": "2026-08-01T09:30:00Z",
    }, headers=eng_auth)
    assert res.status_code == 200, res.text

    async with session_factory() as session:
        chg = (await session.execute(
            select(ChangeRequest).where(ChangeRequest.id == cid)
        )).scalar_one()
        assert chg.required_by_date.tzinfo is None
        assert chg.required_by_date.hour == 9
        assert chg.required_by_date.minute == 30


@pytest.mark.asyncio
async def test_deadline_set_writes_audit_log(client, eng_auth, seed, session_factory):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Deadline Audit", "reason": "r",
    }, headers=eng_auth)
    cid = res.json()["id"]
    due = (datetime.utcnow() + timedelta(days=10)).isoformat()
    await client.patch(f"/api/v1/changes/{cid}", json={"required_by_date": due}, headers=eng_auth)

    async with session_factory() as session:
        rows = (await session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "change",
                AuditLog.entity_id == cid,
                AuditLog.action == "deadline_set",
            ))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_deadline_state_none_without_date(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, change_number="C-DL-002")
        state = await ChangeService.deadline_state(session, chg)
        assert state is None


@pytest.mark.asyncio
async def test_deadline_state_overdue(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, change_number="C-DL-003",
                               customer_relevant=True)
        chg.required_by_date = datetime.utcnow() - timedelta(days=1)
        await session.flush()
        state = await ChangeService.deadline_state(session, chg)
        assert state == "overdue"


@pytest.mark.asyncio
async def test_deadline_state_at_risk(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, change_number="C-DL-004",
                               customer_relevant=True)
        chg.required_by_date = datetime.utcnow() + timedelta(days=2)
        await session.flush()
        template = await _mk_template_with_stages(session, 5)
        # 3 remaining stages incl. current (order 3 of 5): needed = 3*7=21d > 2d left
        inst = WfInstance(template_id=template.id, change_id=chg.id, status="active",
                          current_stage_order=3, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        state = await ChangeService.deadline_state(session, chg)
        assert state == "at_risk"


@pytest.mark.asyncio
async def test_deadline_state_on_track(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, change_number="C-DL-005",
                               customer_relevant=True)
        chg.required_by_date = datetime.utcnow() + timedelta(days=60)
        await session.flush()
        template = await _mk_template_with_stages(session, 5)
        inst = WfInstance(template_id=template.id, change_id=chg.id, status="active",
                          current_stage_order=3, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        state = await ChangeService.deadline_state(session, chg)
        assert state == "on_track"


@pytest.mark.asyncio
async def test_deadline_state_none_for_terminal_change(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, change_number="C-DL-006",
                               status="released", required_by_date=datetime.utcnow() - timedelta(days=1))
        state = await ChangeService.deadline_state(session, chg)
        assert state is None


@pytest.mark.asyncio
async def test_lead_escalations_contains_deadline_row(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, change_number="C-DL-007",
                               lead_id=seed["admin_id"], customer_relevant=True,
                               required_by_date=datetime.utcnow() - timedelta(days=3))
        await session.flush()
        rows = await ChangeService.lead_escalations(session, seed["admin_id"])
        deadline_rows = [r for r in rows if r["kind"] == "deadline" and r["change_id"] == chg.id]
        assert len(deadline_rows) == 1
        row = deadline_rows[0]
        assert row["state"] == "overdue"
        assert row["change_number"] == "C-DL-007"
        assert row["required_by_date"] is not None


@pytest.mark.asyncio
async def test_get_and_list_expose_deadline_fields(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Deadline Expose", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    await client.patch(f"/api/v1/changes/{cid}", json={
        "required_by_date": due, "required_by_reason": "note",
    }, headers=eng_auth)

    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["required_by_date"] is not None
    assert body["required_by_reason"] == "note"
    assert body["deadline_state"] == "on_track"

    res = await client.get(f"/api/v1/changes?project_id={seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    listed = next(c for c in res.json() if c["id"] == cid)
    assert listed["required_by_date"] is not None
    assert listed["deadline_state"] == "on_track"


@pytest.mark.asyncio
async def test_patch_clears_deadline_with_explicit_null(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Deadline Clear", "reason": "r",
    }, headers=eng_auth)
    cid = res.json()["id"]
    due = (datetime.utcnow() + timedelta(days=20)).isoformat()
    await client.patch(f"/api/v1/changes/{cid}", json={"required_by_date": due}, headers=eng_auth)

    res = await client.patch(f"/api/v1/changes/{cid}", json={"required_by_date": None}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["required_by_date"] is None

    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["deadline_state"] is None


@pytest.mark.asyncio
async def test_patch_response_recomputes_deadline_state(client, admin_auth, seed):
    # create a change (mirror this file's existing creation helper)
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "deadline", "change_type": "physical_part",
        "customer_relevant": True,
    }, headers=admin_auth)
    change_id = res.json()["id"]
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    res = await client.patch(f"/api/v1/changes/{change_id}",
                             json={"required_by_date": future,
                                   "required_by_reason": "customer SOP"},
                             headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["deadline_state"] == "on_track"   # was null before the fix


@pytest.mark.asyncio
async def test_patch_date_only_keeps_reason(client, admin_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "deadline2", "change_type": "physical_part",
    }, headers=admin_auth)
    change_id = res.json()["id"]
    d1 = (datetime.utcnow() + timedelta(days=10)).isoformat()
    d2 = (datetime.utcnow() + timedelta(days=20)).isoformat()
    await client.patch(f"/api/v1/changes/{change_id}",
                       json={"required_by_date": d1, "required_by_reason": "SOP"},
                       headers=admin_auth)
    res = await client.patch(f"/api/v1/changes/{change_id}",
                             json={"required_by_date": d2}, headers=admin_auth)
    assert res.json()["required_by_reason"] == "SOP"    # was nulled before the fix


@pytest.mark.asyncio
async def test_active_deadline_and_quoted_on_time(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-P1", customer_relevant=True,
            required_by_date=datetime.utcnow() + timedelta(days=10))
        # quote deadline drives the pre-quoted phase
        assert chg.active_deadline == "quote"
        assert chg.quoted_on_time is None
        # quoting on time freezes the fact and retires the quote deadline
        chg.quoted_at = datetime.utcnow()
        assert chg.active_deadline is None
        assert chg.quoted_on_time is True
        # a late quote reads as late
        chg.quoted_at = chg.required_by_date + timedelta(days=3)
        assert chg.quoted_on_time is False
        # once a release deadline exists it takes over
        chg.release_due_date = datetime.utcnow() + timedelta(days=40)
        assert chg.active_deadline == "release"
        # terminal statuses have no active deadline
        chg.status = "released"
        assert chg.active_deadline is None


@pytest.mark.asyncio
async def test_internal_change_has_no_quote_deadline(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-P2", customer_relevant=False,
            required_by_date=datetime.utcnow() + timedelta(days=10))
        assert chg.active_deadline is None
        chg.release_due_date = datetime.utcnow() + timedelta(days=30)
        assert chg.active_deadline == "release"


@pytest.mark.asyncio
async def test_transition_to_quoted_stamps_quoted_at(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-Q1", status="costing",
            customer_relevant=True, quoted_price=100.0,
            required_by_date=datetime.utcnow() + timedelta(days=10))
        # _guard's gate-wiring check iterates change.gates; the raw insert
        # above never touched it, so force a load before transitioning
        # (same async lazy-load pitfall as impacted_items above).
        await session.refresh(chg, ["gates"])
        await ChangeService.transition(session, chg, "quoted", seed["admin_id"])
        assert chg.status == "quoted"
        assert chg.quoted_at is not None


@pytest.mark.asyncio
async def test_deadline_state_follows_active_deadline(session_factory, seed):
    async with session_factory() as session:
        # overdue quote deadline while pre-quoted
        chg = await _mk_change(
            session, seed, change_number="C-DL-S1", status="costing",
            customer_relevant=True,
            required_by_date=datetime.utcnow() - timedelta(days=1))
        assert await ChangeService.deadline_state(session, chg) == "overdue"
        # quoted: quote deadline retired, nothing active -> None
        chg.quoted_at = datetime.utcnow()
        chg.status = "quoted"
        assert await ChangeService.deadline_state(session, chg) is None
        # release deadline takes over after acceptance/approval
        chg.status = "approved"
        chg.release_due_date = datetime.utcnow() - timedelta(days=2)
        assert await ChangeService.deadline_state(session, chg) == "overdue"
        chg.release_due_date = datetime.utcnow() + timedelta(days=60)
        assert await ChangeService.deadline_state(session, chg) == "on_track"


@pytest.mark.asyncio
async def test_internal_change_deadline_state_none_before_release_due(
        session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(
            session, seed, change_number="C-DL-S2", status="costing",
            customer_relevant=False,
            required_by_date=datetime.utcnow() - timedelta(days=5))
        assert await ChangeService.deadline_state(session, chg) is None


@pytest.mark.asyncio
async def test_in_assessment_gate_skips_deadline_for_internal(session_factory, seed):
    # The gate helper is ChangeService._guard(session, change, to_status) ->
    # str | None (reason string when blocked). The deadline gate sits behind
    # the item/lead gates, so give both changes an impacted item; _mk_change
    # already sets a lead. seed has no part, so create one (pattern from
    # tests/test_notifications.py:122).
    from app.models.change import ChangeImpactedItem
    from app.models.part import Part
    async with session_factory() as session:
        part = Part(project_id=seed["project_id"], part_number="P-DL-1",
                    name="P-DL-1", part_type="internal_mfg",
                    item_category="article", created_by=seed["admin_id"])
        session.add(part)
        await session.flush()
        chg = await _mk_change(
            session, seed, change_number="C-DL-G1", status="scoping",
            customer_relevant=False)
        session.add(ChangeImpactedItem(
            change_id=chg.id, part_id=part.id, is_lead=True,
            created_by=seed["admin_id"]))
        await session.flush()
        await session.refresh(chg, ["impacted_items"])
        blocker = await ChangeService._guard(session, chg, "in_assessment")
        # internal change without a deadline: the deadline gate must not fire
        assert blocker is None or "deadline" not in blocker.lower()

        cust = await _mk_change(
            session, seed, change_number="C-DL-G2", status="scoping",
            customer_relevant=True)
        session.add(ChangeImpactedItem(
            change_id=cust.id, part_id=part.id, is_lead=True,
            created_by=seed["admin_id"]))
        await session.flush()
        await session.refresh(cust, ["impacted_items"])
        blocker = await ChangeService._guard(session, cust, "in_assessment")
        # customer-relevant without a quote deadline still blocks
        assert blocker is not None and "deadline" in blocker.lower()


@pytest.mark.asyncio
async def test_acceptance_requires_release_deadline(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Accept needs date", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]

    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "accepted"}, headers=eng_auth)
    assert res.status_code == 400
    assert "release deadline" in res.json()["detail"].lower()

    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due,
        "release_due_reason": "customer PO timing",
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["customer_response"] == "accepted"
    assert body["release_due_date"] is not None
    assert body["release_due_reason"] == "customer PO timing"
    assert body["active_deadline"] == "release"


@pytest.mark.asyncio
async def test_decline_does_not_require_release_deadline(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Decline no date", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "declined"}, headers=eng_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_acceptance_release_deadline_audited(client, eng_auth, seed, session_factory):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Audit release DL", "reason": "r",
        "customer_relevant": True,
    }, headers=eng_auth)
    cid = res.json()["id"]
    due = (datetime.utcnow() + timedelta(days=45)).isoformat()
    await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due,
    }, headers=eng_auth)
    async with session_factory() as session:
        rows = (await session.execute(
            select(ChangeChangelog).where(
                ChangeChangelog.change_id == cid,
                ChangeChangelog.action == "release_deadline_set",
            ))).scalars().all()
        assert len(rows) == 1
        assert rows[0].field_name == "release_due_date"
        assert rows[0].old_value is None
        assert rows[0].new_value is not None
