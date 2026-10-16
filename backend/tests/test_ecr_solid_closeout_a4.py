"""ECR-solid close-out, area 4 (commercial / offer / sign-offs).

A4-01 the price-drop baseline: the last accepted total, else the highest
version sent since (an unanswered lower version in between never resets
it); supplements against the highest supplement since the last accepted
version; a lower piece price effect is a drop too.
"""
import pytest
from sqlalchemy import select

from tests.test_offers import (  # noqa: F401  (offer_world is a fixture)
    _auth, _create, _url, offer_world,
)
from tests.test_ecr_solid_commercial import (  # noqa: F401  (fixtures)
    _YES, _answer, _no_timing, _raise_position, _supplement, _v2_with_discount,
    approved, quoted,
)

pytestmark = pytest.mark.asyncio


async def _send(client, cid, sales, oid, note):
    res = await client.post(_url(cid, f"/{oid}/send"), json={"change_note": note},
                            headers=sales)
    assert res.status_code == 200, res.text
    return res.json()


async def test_an_unanswered_lower_version_never_resets_the_baseline(client, quoted):
    """v1 1000, v2 900 (no answer), v3 950: accepting v3 is 50 below v1."""
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    await _v2_with_discount(client, cid, sales, 10)
    v3 = await _v2_with_discount(client, cid, sales, 5)
    assert v3["version"] == 3 and v3["totals"]["total_one_time"] == 950
    assert v3["price_drop"]["prev_version"] == 1     # the dialog asks, too
    # NEGATIVE: no reason, no automatic approval
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400, res.text
    assert "v3 at 950.00 is below v1 at 1000.00" in res.json()["detail"]


async def test_an_equal_step_down_after_a_lower_version_still_asks(client, quoted):
    """The audit case: v1, v2 lower (no answer), v3 at v2's total."""
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    v2 = await _v2_with_discount(client, cid, sales, 10)
    res = await client.post(_url(cid), headers=sales)
    v3 = res.json()
    res = await client.patch(_url(cid, f"/{v3['id']}"), json={"data": {
        "factors": v2["data"]["factors"],
        "free_fields": [{"label": "Delivery FCA Spartanburg", "value": "", "amount": 0}]}},
        headers=sales)
    assert res.status_code == 200, res.text
    await _send(client, cid, sales, v3["id"], "Delivery terms")
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400 and "below v1" in res.json()["detail"]


async def _with_piece_price(client, cid, sales, per_piece):
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 201, res.text
    o = res.json()
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"piece_price": {
        "enabled": True, "annual_volume": 10000,
        "rows": [{"label": "Insert", "delta_per_piece": per_piece}]}}}, headers=sales)
    assert res.status_code == 200, res.text
    return await _send(client, cid, sales, o["id"], f"Piece price {per_piece}")


async def test_a_lower_piece_price_effect_needs_the_ok(client, quoted, session_factory):
    from app.models.change import ChangeTransitionDeviation
    cid = quoted["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    await _with_piece_price(client, cid, sales, 0.10)       # 1000 / yr
    v3 = await _with_piece_price(client, cid, sales, 0.05)  # 500 / yr, same total
    assert v3["totals"]["total_one_time"] == 1000
    # NEGATIVE: the one-time total is the same, the recurring side is lower
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400, res.text
    assert "piece price effect to 500.00/yr (v2: 1000.00/yr)" in res.json()["detail"]
    res = await _answer(client, cid, sales, {
        **_YES, "price_drop_code": "volume",
        "price_drop_note": "Volume doubled per the buyer mail of 14 Oct"})
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_drop"))).scalar_one()
    assert dev.status == "pending"


async def test_a_higher_piece_price_needs_no_reason(client, quoted):
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    await _with_piece_price(client, cid, sales, 0.05)
    await _with_piece_price(client, cid, sales, 0.10)
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text


async def test_a_supplement_stepped_down_through_a_middle_one_asks(
        client, approved, session_factory):
    """S1 +500, S2 +100 (no answer), S3 +300: S3 is below S1."""
    cid, sales = approved["change_id"], approved["sales"]
    for amount, note in ((1500, "Rework higher"), (1100, "Rework lower"),
                         (1300, "Rework middle")):
        await _raise_position(session_factory, approved, amount)
        s = await _supplement(client, cid, sales)
        sent = await _send(client, cid, sales, s["id"], note)
    assert sent["totals"]["total_one_time"] == 300
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400, res.text
    assert f"below v{sent['version'] - 2}" in res.json()["detail"]


# ---------------------------------------------------------------------------
# A4-02 the version a signature must cover: never a declined supplement
# ---------------------------------------------------------------------------
async def _declined_supplement(client, approved, session_factory):
    cid, sales = approved["change_id"], approved["sales"]
    await _raise_position(session_factory, approved, 1300)
    s1 = await _supplement(client, cid, sales)
    await _send(client, cid, sales, s1["id"], "Rework higher")
    res = await _answer(client, cid, sales, {"response": "declined",
                                             "ref": "Mail 15 Oct, buyer refuses"})
    assert res.status_code == 200, res.text
    return cid, s1


async def test_a_declined_supplement_takes_no_signature(client, approved, session_factory):
    from app.models.change import ChangeChangelog, ChangeRequest, ChangeTransitionDeviation
    from app.services.change_service import ChangeService
    cid, s1 = await _declined_supplement(client, approved, session_factory)
    res = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "goodwill", "note": "Rework 300 EUR goodwill on program G45"},
        headers=approved["sales"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_open"))).scalars().first()
    if dev is not None and dev.status == "pending":
        r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev.id}/decide",
                              json={"decision": "approved"}, headers=approved["pm"])
        assert r.status_code == 200, r.text
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        sides, target = await ChangeService.signoff_sides_missing(s, ch)
        # NEGATIVE: the refused version is never the one to sign
        assert sides == [] and target.id == approved["offer_id"]
        assert await ChangeService.signoff_offer_refusal(s, ch) is None
        rows = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
    assert "signoff_withdrawn" not in rows
    for who in (approved["pm"], approved["q"]):
        tasks = (await client.get("/api/v1/changes/my-tasks", headers=who)).json()
        tasks = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
        assert not any(t["kind"] == "sign_off" and t["change_id"] == cid for t in tasks)
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=approved["pm"])).json()
    assert not {"pm_signoff", "quality_signoff"} & {i["key"] for i in ch["next_step"]["items"]}


async def test_signing_while_a_supplement_is_out_binds_the_accepted_version(
        client, approved, session_factory):
    """The sign button binds the version it must cover: with a supplement
    still out, the accepted offer (a later decline never orphans it)."""
    from app.models.change import ChangeRequest
    cid, sales = approved["change_id"], approved["sales"]
    await _raise_position(session_factory, approved, 1300)
    s1 = await _supplement(client, cid, sales)
    await _send(client, cid, sales, s1["id"], "Rework higher")
    r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"},
                          headers=approved["pm"])
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        assert ch.pm_signed_offer_id == approved["offer_id"]


# ---------------------------------------------------------------------------
# A4-03 a declined price has a row, an owner and a due
# ---------------------------------------------------------------------------
async def _rows(client, auth, cid, kind):
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    tasks = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
    return [t for t in tasks if t["kind"] == kind and t["change_id"] == cid]


async def test_a_declined_supplement_is_a_sales_row_until_absorbed(
        client, approved, session_factory):
    from app.models.change_offer import ChangeOffer
    from app.services.due_rules import add_wd
    cid, s1 = await _declined_supplement(client, approved, session_factory)
    rows = await _rows(client, approved["sales"], cid, "price_open")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["target_tab"] == "offer" and "absorb" in row["hint"]
    async with session_factory() as s:
        declined_at = (await s.get(ChangeOffer, s1["id"])).answered_at
    assert row["due_date"][:10] == add_wd(declined_at, 5).date().isoformat()
    # NEGATIVE: not a PM or Quality row (they decide the Absorb, not ask it)
    assert await _rows(client, approved["pm"], cid, "price_open") == []
    assert await _rows(client, approved["q"], cid, "price_open") == []
    res = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "goodwill", "note": "Rework 300 EUR goodwill on program G45"},
        headers=approved["sales"])
    assert res.status_code == 200, res.text
    # asked: the decider has the row now, Sales' is done
    assert await _rows(client, approved["sales"], cid, "price_open") == []


async def test_a_new_version_after_the_decline_replaces_the_row(
        client, approved, session_factory):
    cid, _ = await _declined_supplement(client, approved, session_factory)
    await _raise_position(session_factory, approved, 1200)
    s2 = await _supplement(client, cid, approved["sales"])
    await _send(client, cid, approved["sales"], s2["id"], "Rework lower")
    assert await _rows(client, approved["sales"], cid, "price_open") == []


# ---------------------------------------------------------------------------
# A4-04 an override covers the post-quote scope change only for its rule
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("guard_key,covered", [
    ("price_open", False),               # NEGATIVE: an Absorb
    ("timing_unconfirmed", False),       # NEGATIVE: another rule's OK
    ("scope_change_uncovered", True),
    (None, True),                        # legacy, before migration 118
])
async def test_only_a_scope_override_covers_the_scope_change(
        quoted, session_factory, guard_key, covered):
    from datetime import datetime, timedelta
    from app.models.change import ChangeRequest, ChangeTransitionDeviation
    from app.services.change_service import ChangeService
    from app.services.early_stage_service import EarlyStageService
    cid = quoted["change_id"]
    now = datetime.utcnow()
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        ch.scope_changed_after_quote = True
        ch.scope_changed_at = now - timedelta(hours=1)
        ch.scope_change_reason = "Insert added after the quote"
        ch.scope_change_department_ids = [quoted["depts"]["Tool Engineer"]]
        from app.models.change_offer import ChangeOffer
        (await s.get(ChangeOffer, quoted["offer_id"])).sent_at = now - timedelta(hours=2)
        s.add(ChangeTransitionDeviation(
            change_id=cid, to_status="approved", reason="Goodwill on the program G45",
            proposed_by=quoted["users"]["sales"], status="approved",
            decided_by=quoted["users"]["pm"], decided_at=now, guard_key=guard_key))
        await s.commit()
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        await ChangeService._load_deviations(s, ch)
        state = await EarlyStageService.scope_change_state(s, ch)
    assert state["covered"] is covered


# ---------------------------------------------------------------------------
# A4-05 a settled version never closes a price a later card opened
# ---------------------------------------------------------------------------
async def test_a_card_opened_while_a_supplement_is_out_keeps_the_price_open(
        client, approved, session_factory):
    from app.models.change import ChangeChangelog
    from tests.test_ecr_solid_commercial import _card
    cid, sales = approved["change_id"], approved["sales"]
    await _raise_position(session_factory, approved, 1300)
    s2 = await _supplement(client, cid, sales)
    await _send(client, cid, sales, s2["id"], "Rework higher")
    card = await _card(client, cid, sales)
    assert card["post_accept"] is True
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text
    # NEGATIVE: S2's yes does not price card B
    assert res.json()["price_open"] is True
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
    assert "price_kept_open" in rows


# ---------------------------------------------------------------------------
# A4-06 start at risk: no dead row for Quality's line writer; the go-ahead
# file is frozen
# ---------------------------------------------------------------------------
from tests.test_ecr_solid_commercial import (  # noqa: E402,F401  (fixtures)
    _mail, _sar, _tasks, quality_member, urgent,
)


async def test_the_quality_line_writer_gets_no_approve_row(client, urgent, session_factory):
    from app.models.workflow import Department, UserDepartment
    cid = urgent["change_id"]
    async with session_factory() as s:
        qid = (await s.execute(select(Department.id).where(
            Department.name == "Quality"))).scalar_one()
        s.add(UserDepartment(user_id=urgent["users"]["pm"], department_id=qid))
        await s.commit()
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    assert (await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start now, PO follows"},
                              headers=sales)).status_code == 200
    assert (await client.post(_sar(cid, "/quality"), json={
        "note": "No PPAP before SOP, first lot 100 % checked"}, headers=pm)).status_code == 200
    # NEGATIVE: approve() refuses Quality's line writer: no row for them
    assert (await client.post(_sar(cid, "/approve"), headers=pm)).status_code == 403
    assert not any(t["kind"] == "start_at_risk_approve" and t["change_id"] == cid
                   for t in await _tasks(client, pm))


async def test_the_go_ahead_file_cannot_be_removed(client, urgent, session_factory, tmp_path):
    from app.models.change import ChangeRequest
    from tests.conftest import login
    cid = urgent["change_id"]
    sales = await _auth(client, "sales")
    mail = await _mail(session_factory, urgent, "go-ahead.msg", None, tmp_path)
    r = await client.post(_sar(cid), json={"attachment_id": mail}, headers=sales)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).start_at_risk_attachment_id == mail
    # NEGATIVE: the uploader cannot remove the evidence the start stands on
    r = await client.delete(f"/api/v1/changes/{cid}/attachments/{mail}", headers=sales)
    assert r.status_code == 409 and "start at risk" in r.json()["detail"]
    admin = await login(client, "admin@test.io")
    r = await client.delete(f"/api/v1/changes/{cid}/attachments/{mail}", headers=admin)
    assert r.status_code in (204, 400), r.text      # the admin exit (or a baseline freeze)


# ---------------------------------------------------------------------------
# A4-07 Absorb: COMMERCIAL_V2 only; a note that names what is absorbed
# ---------------------------------------------------------------------------
async def test_absorb_needs_the_commercial_switch(client, approved, session_factory,
                                                   monkeypatch):
    from app.models.change import ChangeTransitionDeviation
    from app.services import cm_switches
    cid, s1 = await _declined_supplement(client, approved, session_factory)
    body = {"reason_code": "goodwill", "note": "Rework 300 EUR goodwill on program G45"}
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    res = await client.post(f"/api/v1/changes/{cid}/absorb", json=body,
                            headers=approved["sales"])
    assert res.status_code == 400 and "COMMERCIAL_V2" in res.json()["detail"]  # NEGATIVE
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", True)
    res = await client.post(f"/api/v1/changes/{cid}/absorb", json=body,
                            headers=approved["sales"])
    assert res.status_code == 200, res.text
    dev_id = res.json()["id"]
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    # NEGATIVE: never decided by the pre-C6 rule (any engineer)
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev_id}/decide",
                          json={"decision": "approved"}, headers=await _auth(client, "tool"))
    assert r.status_code == 403, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeTransitionDeviation, dev_id)).status == "pending"


@pytest.mark.parametrize("note", ["aaaaaaaaaaaaaaaaaaaaa", "checked checked checked"])
async def test_an_absorb_note_names_what_is_absorbed(client, approved, session_factory, note):
    cid, _ = await _declined_supplement(client, approved, session_factory)
    res = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "goodwill", "note": note}, headers=approved["sales"])
    assert res.status_code == 400, res.text           # NEGATIVE
    assert "says" in res.json()["detail"]


# ---------------------------------------------------------------------------
# A4-09 commercial words that match the rules (R37)
# ---------------------------------------------------------------------------
from tests.test_ecr_solid_gates import (  # noqa: E402,F401  (fixtures)
    _change as _gate_change, admin, depts, people,
)


async def test_an_internal_open_price_names_the_approver_not_pm(
        client, admin, seed, depts, people, session_factory):
    cid = await _gate_change(client, admin, seed, session_factory, "released",
                             customer=False, price_open=True)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "closed"}, headers=admin)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "internal approver" in detail and "never the raiser" in detail
    assert "Project Management or Management" not in detail   # NEGATIVE


def test_an_approved_change_is_past_the_start_at_risk_ask_whatever_its_priority():
    from types import SimpleNamespace
    from app.services.start_at_risk_service import refusal
    c = SimpleNamespace(customer_relevant=True, priority="normal", status="approved",
                        customer_response="pending", pm_signed_by=None,
                        quality_signed_by=None)
    why = refusal(c)
    assert "'approved'" in why and "urgent" not in why
    c.status, c.customer_response = "quoted", "accepted"
    assert refusal(c).startswith("The customer accepted")


async def test_the_older_index_warning_says_the_situation(client, quoted, session_factory, seed):
    """A part with no customer index on the change, the customer sent F."""
    from app.models.change import ChangeImpactedItem
    from app.models.part import Part, PartRevision
    cid = quoted["change_id"]
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="886.199", name="Cover",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        old = PartRevision(part_id=part.id, revision_name="1", phase="official",
                           source="customer", created_by=seed["admin_id"])
        s.add(old)
        await s.flush()
        s.add(PartRevision(part_id=part.id, revision_name="2", phase="official",
                           customer_index="F", source="customer",
                           created_by=seed["admin_id"]))
        part.active_revision_id = old.id
        s.add(ChangeImpactedItem(change_id=cid, part_id=part.id,
                                 created_by=quoted["users"]["sales"]))
        await s.commit()
    sales = await _auth(client, "sales")
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 201, res.text
    w = next((w for w in res.json()["warnings"] if w["code"] == "index_older"), None)
    assert w is not None, res.json()["warnings"]
    assert "886.199: the change carries no customer index yet; the customer already sent F" \
        in w["message"]
    assert "(no index)" not in w["message"]


async def test_a_supplement_never_repeats_an_index_sent_knowing_it(
        client, approved, session_factory, seed):
    from datetime import date as _d
    from app.models.change import ChangeImpactedItem
    from app.models.part import Part, PartRevision
    cid = approved["change_id"]
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="886.199", name="Cover",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        old = PartRevision(part_id=part.id, revision_name="1", phase="official",
                           customer_index="E", source="customer", created_by=seed["admin_id"])
        s.add(old)
        await s.flush()
        s.add(PartRevision(part_id=part.id, revision_name="2", phase="official",
                           customer_index="F", source="customer",
                           customer_received_at=_d(2026, 1, 5),   # before v1 went out
                           created_by=seed["admin_id"]))
        s.add(ChangeImpactedItem(change_id=cid, part_id=part.id,
                                 resulting_revision_id=old.id,
                                 created_by=approved["users"]["sales"]))
        await s.commit()
    s1 = await _supplement(client, cid, approved["sales"])
    # NEGATIVE: v1 went out knowing F; the supplement does not say it again
    assert "index_older" not in {w["code"] for w in s1["warnings"]}
