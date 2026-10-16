"""ECR-solid §10 (lane L7, switch RELEASE_V2): a FAIL raises its issue and
Quality's Fix task (who fixes, retest date); the check's own department
retests; a concession runs in parallel (customer: the Sales owner asks,
Quality decides on the filed mail for a quantity or until a date;
internal: "not for shipment", Quality decides at once). The status line
names the failure, the fix and the concession; an urgent FAIL reaches
Management at once; a weight delta reaches Sales only on a FAIL or > 2 %.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeRequest
from app.models.change_validation_issue import ValidationIssue
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from app.services import cm_switches
from tests.conftest import ENGINEER_PASSWORD, login
from tests.test_validation_checks import _auth, _state, _url, val  # noqa: F401

pytestmark = pytest.mark.asyncio

SPEC = {"lower_limit": 495.0, "upper_limit": 515.0,
        "spec_source": "drawing 886.197 D, weight 505 g +/-10"}
REF = "scale WG-0042, report MR-2026-118"


@pytest.fixture
async def fix(val, session_factory):
    """val plus Quality, Process Engineer and Management members; the Sales
    user is the Sales owner."""
    async with session_factory() as s:
        org = (await s.get(User, val["user"]["Tool Engineer"]["id"])).organization_id
        for name in ("Quality", "Process Engineer", "Management"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            val["dept"][name] = d.id
            email = f"{name.split()[0].lower()}@fix.test"
            u = User(organization_id=org, username=email.split("@")[0], email=email,
                     full_name=name, role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=d.id))
            val["user"][name] = {"id": u.id, "email": email}
        c = await s.get(ChangeRequest, val["change_id"])
        c.sales_owner_id = val["user"]["Sales"]["id"]
        c.customer_relevant = True
        await s.commit()
    return val


async def _who(client, fix, name):
    return await login(client, fix["user"][name]["email"], ENGINEER_PASSWORD)


async def _fail_weight(client, fix, hi=518.0):
    tool = await _auth(client, fix, "Tool Engineer")
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 509.0, "max_value": hi,
                        "measuring_ref": REF, **SPEC}})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "failed"


def _iurl(fix, suffix=""):
    return f"/api/v1/changes/{fix['change_id']}/validation/issues{suffix}"


async def _issue(client, fix):
    issues = (await client.get(_iurl(fix), headers=await _who(client, fix, "Quality"))).json()
    assert len(issues) == 1, issues
    return issues[0]


async def _kinds(client, auth, change_id):
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    return {t["kind"]: t for t in tasks if t["change_id"] == change_id}


async def test_a_fail_raises_its_issue_and_quality_owns_the_fix_task(client, fix):
    await _fail_weight(client, fix)
    issue = await _issue(client, fix)
    assert issue["ref"] == "VI-1" and issue["check_key"] == "weight"
    assert "518" in issue["description"] and "495-515" in issue["description"]
    quality = await _who(client, fix, "Quality")
    tasks = await _kinds(client, quality, fix["change_id"])
    assert "validation_issue_fix" in tasks
    assert tasks["validation_issue_fix"]["due_date"] is not None
    # the 8D steps stay on the card: no root-cause task for the department,
    # no route task for Project Management
    tool = await _auth(client, fix, "Tool Engineer")
    assert "validation_issue_root_cause" not in await _kinds(client, tool, fix["change_id"])
    pm = await _auth(client, fix, "Project Manager")
    assert "validation_issue_route" not in await _kinds(client, pm, fix["change_id"])
    # a second failure of the same check (a retest) raises no second issue
    tool_retest = await _auth(client, fix, "Tool Engineer")
    res = await client.post(_url(fix, "/checks"), headers=tool_retest, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 509.0, "max_value": 519.0,
                        "measuring_ref": REF, "what_changed_kind": "method",
                        "what_changed_ref": "second scale WG-0043 to confirm"}})
    assert res.status_code == 201, res.text
    issues = (await client.get(_iurl(fix), headers=quality)).json()
    assert len(issues) == 1


async def test_negative_only_quality_picks_the_fix(client, fix, admin_auth):
    await _fail_weight(client, fix)
    issue = await _issue(client, fix)
    body = {"owner": "process_parameters",
            "retest_due": (date.today() + timedelta(days=3)).isoformat()}
    for name in ("Tool Engineer", "Project Manager"):
        res = await client.post(_iurl(fix, f"/{issue['id']}/fix"),
                                headers=await _auth(client, fix, name), json=body)
        assert res.status_code == 403, res.text
    res = await client.post(_iurl(fix, f"/{issue['id']}/fix"), headers=admin_auth, json=body)
    assert res.status_code == 403, res.text
    quality = await _who(client, fix, "Quality")
    past = {**body, "retest_due": (date.today() - timedelta(days=1)).isoformat()}
    res = await client.post(_iurl(fix, f"/{issue['id']}/fix"), headers=quality, json=past)
    assert res.status_code == 400 and "past" in res.json()["detail"]
    res = await client.post(_iurl(fix, f"/{issue['id']}/fix"), headers=quality,
                            json={**body, "owner": "tool_at_supplier"})
    assert res.status_code == 400 and "supplier" in res.json()["detail"]
    res = await client.post(_iurl(fix, f"/{issue['id']}/fix"), headers=quality,
                            json={**body, "owner": "luck"})
    assert res.status_code == 400


async def test_fix_owner_works_the_check_department_retests_and_it_closes(client, fix):
    await _fail_weight(client, fix)
    issue = await _issue(client, fix)
    quality = await _who(client, fix, "Quality")
    due = date.today() + timedelta(days=3)
    res = await client.post(_iurl(fix, f"/{issue['id']}/fix"), headers=quality, json={
        "owner": "process_parameters", "retest_due": due.isoformat()})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["fix_department_name"] == "Process Engineer"
    assert out["retest_due"] == due.isoformat()
    # the Fix task is done; Process works the fix; the Tool Engineer retests
    assert "validation_issue_fix" not in await _kinds(client, quality, fix["change_id"])
    process = await _who(client, fix, "Process Engineer")
    work = (await _kinds(client, process, fix["change_id"]))["validation_issue_fix_work"]
    assert "retest" in work["label"]
    tool = await _auth(client, fix, "Tool Engineer")
    retest = (await _kinds(client, tool, fix["change_id"]))["validation_issue_recheck"]
    assert retest["label"].startswith("Retest for VI-1 by")
    st = await _state(client, tool, fix)
    assert st["release_line"].startswith("Not releasable: Part weight validated 518 g vs 495-515")
    assert "fix: Process Engineer, retest" in st["release_line"]
    assert st["release_line"].endswith("concession: none")
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 503.0, "max_value": 509.0,
                        "measuring_ref": REF, "what_changed_kind": "parameter",
                        "what_changed_ref": "holding pressure -5 bar, PS-114 rev C"}})
    assert res.status_code == 201 and res.json()["status"] == "passed", res.text
    assert (await client.get(_iurl(fix, f"/{issue['id']}"), headers=quality)).json()["status"] == "closed"
    assert (await _state(client, tool, fix))["release_line"] is None


async def test_customer_concession_sales_asks_quality_decides(client, fix, session_factory):
    await _fail_weight(client, fix)
    issue = await _issue(client, fix)
    iid = issue["id"]
    quality = await _who(client, fix, "Quality")
    sales = await _auth(client, fix, "Sales")
    # NEGATIVE: Sales (or the department) cannot request it: Quality's
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=sales,
                            json={"note": "customer may accept 518 g"})
    assert res.status_code == 403
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                            json={"note": "ask for 518 g max, 500 parts"})
    assert res.status_code == 200, res.text
    assert res.json()["route"] == "customer_concession"
    async with session_factory() as s:
        n = (await s.execute(select(Notification).where(
            Notification.user_id == fix["user"]["Sales"]["id"],
            Notification.subject_key == f"vi:{iid}:concession"))).scalars().all()
        assert len(n) == 1
    assert "validation_issue_customer" in await _kinds(client, sales, fix["change_id"])
    st = await _state(client, quality, fix)
    assert "concession: waiting for customer (Sales owner, asked" in st["release_line"]
    # NEGATIVE: Quality cannot decide before the customer's mail is filed
    res = await client.post(_iurl(fix, f"/{iid}/customer"), headers=quality, json={
        "decision": "accept_deviation", "note": "customer ok",
        "concession_until": (date.today() + timedelta(days=60)).isoformat()})
    assert res.status_code == 400 and "mail" in res.json()["detail"]
    up = await client.post(
        f"/api/v1/changes/{fix['change_id']}/attachments", headers=sales,
        files={"file": ("mail.eml", b"From: customer", "message/rfc822")},
        data={"kind": "customer_email", "validation_issue_id": str(iid)})
    assert up.status_code in (200, 201), up.text
    assert "concession: Quality decides" in (await _state(client, quality, fix))["release_line"]
    # NEGATIVE: Sales cannot give the yes; Quality must bound it
    res = await client.post(_iurl(fix, f"/{iid}/customer"), headers=sales, json={
        "decision": "accept_deviation", "note": "customer ok"})
    assert res.status_code == 403
    res = await client.post(_iurl(fix, f"/{iid}/customer"), headers=quality, json={
        "decision": "accept_deviation", "note": "customer mail 2026-10-15"})
    assert res.status_code == 400 and "quantity" in res.json()["detail"]
    until = date.today() + timedelta(days=60)
    res = await client.post(_iurl(fix, f"/{iid}/customer"), headers=quality, json={
        "decision": "accept_deviation", "note": "customer mail 2026-10-15",
        "concession_until": until.isoformat()})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "accepted"
    st = await _state(client, quality, fix)
    assert st["release_line"] is None
    assert st["active_concessions"][0]["text"] == (
        f"Accepted under concession VI-1 until {until.isoformat()}")


async def test_internal_concession_is_not_for_shipment_and_quality_decides(
        client, fix, session_factory):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        c.customer_relevant = False
        await s.commit()
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    quality = await _who(client, fix, "Quality")
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                            json={"note": "trial parts", "quantity": 200})
    assert res.status_code == 400 and "not for shipment" in res.json()["detail"]
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                            json={"note": "trial parts", "not_for_shipment": True})
    assert res.status_code == 400 and "quantity" in res.json()["detail"]
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                            json={"note": "trial parts for the line test",
                                  "not_for_shipment": True, "quantity": 200})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "accepted"
    st = await _state(client, quality, fix)
    assert st["active_concessions"][0]["text"] == (
        "Accepted under concession VI-1 for 200 parts (not for shipment)")


async def test_urgent_fail_reaches_management_at_once(client, fix, session_factory):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        c.priority = "critical"
        await s.commit()
    await _fail_weight(client, fix)
    async with session_factory() as s:
        rows = (await s.execute(select(Notification).where(
            Notification.kind == "validation_urgent_fail"))).scalars().all()
    assert [r.user_id for r in rows] == [fix["user"]["Management"]["id"]]
    assert rows[0].body.startswith("Not releasable: Part weight validated 518 g")


async def test_negative_a_non_urgent_fail_tells_management_nothing(
        client, fix, session_factory):
    await _fail_weight(client, fix)
    async with session_factory() as s:
        assert not (await s.execute(select(Notification).where(
            Notification.kind == "validation_urgent_fail"))).scalars().all()
        sales = (await s.execute(select(Notification).where(
            Notification.kind == "validation_weight_failed"))).scalars().all()
    assert [n.user_id for n in sales] == [fix["user"]["Sales"]["id"]]


async def test_weight_delta_reaches_sales_only_above_two_percent(client, fix):
    tool = await _auth(client, fix, "Tool Engineer")
    # estimate 500 g; 506 g = +1.2 %: no Sales task
    spec = {"lower_limit": 490.0, "upper_limit": 520.0,
            "spec_source": "drawing 886.197 D, weight 505 g +/-15"}
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 504.0, "max_value": 508.0,
                        "measuring_ref": REF, **spec}})
    assert res.json()["status"] == "passed"
    assert (await _state(client, tool, fix))["weight_quote_update_open"] is False
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 512.0, "max_value": 518.0,
                        "measuring_ref": REF}})
    assert res.json()["status"] == "passed"     # 515 g = +3 %
    assert (await _state(client, tool, fix))["weight_quote_update_open"] is True


async def test_concession_reminder_ten_working_days_before_expiry_once(
        client, fix, session_factory):
    from app.services.validation_issue_service import ValidationIssueService
    async with session_factory() as s:
        s.add(ValidationIssue(
            change_id=fix["change_id"], number=7, title="weight", created_by=1,
            description="518 g", route="customer_concession", status="accepted",
            customer_decision="accept_deviation",
            concession_until=date.today() + timedelta(days=5)))
        s.add(ValidationIssue(
            change_id=fix["change_id"], number=8, title="later", created_by=1,
            description="x", route="customer_concession", status="accepted",
            customer_decision="accept_deviation",
            concession_until=date.today() + timedelta(days=60)))
        await s.commit()
    async with session_factory() as s:
        assert await ValidationIssueService.remind_expiring_concessions(s) == 1
        await s.commit()
    async with session_factory() as s:
        assert await ValidationIssueService.remind_expiring_concessions(s) == 0
        rows = (await s.execute(select(Notification).where(
            Notification.kind == "concession_expiring"))).scalars().all()
    assert {r.user_id for r in rows} == {fix["user"]["Quality"]["id"],
                                         (await _lead(session_factory, fix))}


async def _lead(session_factory, fix):
    async with session_factory() as s:
        return (await s.get(ChangeRequest, fix["change_id"])).lead_id


async def test_switch_off_raises_no_issue(client, fix, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    tool = await _auth(client, fix, "Tool Engineer")
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "status": "failed", "value": 540.0})
    assert res.status_code == 201
    quality = await _who(client, fix, "Quality")
    assert (await client.get(_iurl(fix), headers=quality)).json() == []


# --- review loop 1: the Fix pick and the concession run in parallel --------

async def test_concession_first_keeps_the_fix_task_and_the_fix_closes_it(client, fix):
    """§10 'Request concession runs in parallel': asked first, the Fix pick
    stays Quality's task; the fix and the retest close the issue."""
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    quality = await _who(client, fix, "Quality")
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                            json={"note": "ask for 518 g max, 500 parts"})
    assert res.status_code == 200, res.text
    card = (await client.get(_iurl(fix, f"/{iid}"), headers=quality)).json()
    assert "fix" in card["next_acts"] and card["primary_act"] == "fix"
    tasks = await _kinds(client, quality, fix["change_id"])
    assert "validation_issue_fix" in tasks
    assert tasks["validation_issue_fix"]["role"] == "main"
    due = date.today() + timedelta(days=3)
    res = await client.post(_iurl(fix, f"/{iid}/fix"), headers=quality, json={
        "owner": "process_parameters", "retest_due": due.isoformat()})
    assert res.status_code == 200, res.text
    card = (await client.get(_iurl(fix, f"/{iid}"), headers=quality)).json()
    # picked: a quiet re-pick stays, the Fix task is done
    assert "fix" not in card["next_acts"] and "refix" in card["next_acts"]
    assert card["primary_act"] != "refix"
    assert "validation_issue_fix" not in await _kinds(client, quality, fix["change_id"])
    process = await _who(client, fix, "Process Engineer")
    assert "validation_issue_fix_work" in await _kinds(client, process, fix["change_id"])
    tool = await _auth(client, fix, "Tool Engineer")
    assert "validation_issue_recheck" in await _kinds(client, tool, fix["change_id"])
    st = await _state(client, tool, fix)
    assert "fix: Process Engineer, retest" in st["release_line"]
    assert "concession: waiting for customer" in st["release_line"]
    # a new retest date: the re-pick
    later = due + timedelta(days=2)
    res = await client.post(_iurl(fix, f"/{iid}/fix"), headers=quality, json={
        "owner": "process_parameters", "retest_due": later.isoformat()})
    assert res.status_code == 200 and res.json()["retest_due"] == later.isoformat()
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 503.0, "max_value": 509.0,
                        "measuring_ref": REF, "what_changed_kind": "parameter",
                        "what_changed_ref": "holding pressure -5 bar, PS-114 rev C"}})
    assert res.status_code == 201 and res.json()["status"] == "passed", res.text
    assert (await client.get(_iurl(fix, f"/{iid}"), headers=quality)).json()["status"] == "closed"


async def test_concession_tasks_say_who_owes_what_and_are_due_soon(client, fix):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    quality = await _who(client, fix, "Quality")
    sales = await _auth(client, fix, "Sales")
    assert (await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                              json={"note": "ask for 518 g max"})).status_code == 200
    task = (await _kinds(client, sales, fix["change_id"]))["validation_issue_customer"]
    assert task["label"] == "Ask the customer about the concession for VI-1 and file the mail"
    due = datetime.fromisoformat(task["due_date"]).date()
    assert due <= date.today() + timedelta(days=7)
    # Quality owes nothing on the concession until the mail is filed
    assert "validation_issue_customer" not in await _kinds(client, quality, fix["change_id"])
    up = await client.post(
        f"/api/v1/changes/{fix['change_id']}/attachments", headers=sales,
        files={"file": ("mail.eml", b"From: customer", "message/rfc822")},
        data={"kind": "customer_email", "validation_issue_id": str(iid)})
    assert up.status_code in (200, 201), up.text
    # the mail is filed: Sales is done, Quality decides (its own task)
    assert "validation_issue_customer" not in await _kinds(client, sales, fix["change_id"])
    task = (await _kinds(client, quality, fix["change_id"]))["validation_issue_customer"]
    assert task["label"] == "Decide concession VI-1: for a quantity or until a date"
    assert task["role"] == "main" and task["needs_you"] is True
    assert datetime.fromisoformat(task["due_date"]).date() <= date.today() + timedelta(days=7)


async def test_negative_an_inactive_department_does_not_fix(client, fix, session_factory):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    async with session_factory() as s:
        old = Department(name="Old Tooling", flow_type="action", is_active=False)
        s.add(old)
        await s.commit()
        old_id = old.id
    quality = await _who(client, fix, "Quality")
    res = await client.post(_iurl(fix, f"/{iid}/fix"), headers=quality, json={
        "owner": "other", "department_id": old_id,
        "retest_due": (date.today() + timedelta(days=3)).isoformat()})
    assert res.status_code == 400 and "active" in res.json()["detail"]


async def test_fix_department_without_members_hands_the_work_to_the_lead(
        client, fix, session_factory):
    """Process Engineer's only member left: the fix work reaches the lead
    (no silent hole), and the status line says so."""
    pm_id = fix["user"]["Project Manager"]["id"]
    async with session_factory() as s:
        (await s.get(User, fix["user"]["Process Engineer"]["id"])).is_active = False
        (await s.get(ChangeRequest, fix["change_id"])).lead_id = pm_id
        await s.commit()
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    quality = await _who(client, fix, "Quality")
    res = await client.post(_iurl(fix, f"/{iid}/fix"), headers=quality, json={
        "owner": "process_parameters",
        "retest_due": (date.today() + timedelta(days=3)).isoformat()})
    assert res.status_code == 200, res.text
    pm = await _auth(client, fix, "Project Manager")
    work = (await _kinds(client, pm, fix["change_id"]))["validation_issue_fix_work"]
    assert "Process Engineer has no member here: you coordinate" in work["label"]
    st = await _state(client, pm, fix)
    assert "fix: Process Engineer (no member here: the lead coordinates)" in st["release_line"]
