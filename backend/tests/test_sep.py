"""SEP Q-Gate module tests: activation, tri-state items with audit, strict
gate sequencing, dual sign-off with yellow-gate risk gating, lessons hook."""
import pytest


async def _add_form_risk(client, auth, project_id, gate_code, **row):
    """Add a row to the project's risk_assessment form (creating it if needed).

    Gate colour and sign-off read their risks from this form, not from sep_risks.
    Returns the saved instance so callers can patch the row afterwards."""
    res = await client.get(f"/api/v1/forms/projects/{project_id}", headers=auth)
    group = next(g for g in res.json() if g["key"] == "risk_assessment")
    if group["instances"]:
        inst = (await client.get(f"/api/v1/forms/instances/{group['instances'][0]['id']}", headers=auth)).json()
    else:
        inst = (await client.post(f"/api/v1/forms/projects/{project_id}/instances",
                                  json={"key": "risk_assessment"}, headers=auth)).json()
    data = inst["data"]
    data["risks"] = list(data.get("risks") or []) + [
        {"gate": gate_code, "risk": "r", "q": 0.1, "c": 0.1, "s": 0.1, "p": 0.5, "status": "open", **row}]
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _activate(client, auth, project_id):
    res = await client.post(f"/api/v1/sep/projects/{project_id}/activate", headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


async def _get_sep(client, auth, project_id):
    res = await client.get(f"/api/v1/sep/projects/{project_id}", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _clear_gate_items(client, auth, gate):
    """Mark every item in a gate not_applicable so the gate turns green."""
    for item in gate["items"]:
        res = await client.patch(
            f"/api/v1/sep/items/{item['id']}", json={"status": "not_applicable"}, headers=auth
        )
        assert res.status_code == 200, res.text


async def _close_gate(client, auth_a, auth_b, gate):
    res = await client.post(f"/api/v1/sep/gates/{gate['id']}/sign-off", json={"role": "pm"}, headers=auth_a)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/sep/gates/{gate['id']}/sign-off", json={"role": "quality"}, headers=auth_b)
    assert res.status_code == 200, res.text
    return res.json()


async def test_activation_copies_template(client, eng_auth, seed):
    data = await _activate(client, eng_auth, seed["project_id"])
    assert len(data["gates"]) == 7
    assert [g["code"] for g in data["gates"]] == [
        "K0/RG1", "K/RG2", "E/RG3", "D/RG4", "C/RG5", "B/RG6", "A/RG7"
    ]
    assert data["gates"][0]["status"] == "in_progress"
    assert all(g["status"] == "pending" for g in data["gates"][1:])

    full = await _get_sep(client, eng_auth, seed["project_id"])
    assert full["active"] is True
    assert full["rollup"]["total"]["total"] == 232
    assert full["gates"][0]["progress"]["total"] == 42
    # everything starts open -> yellow
    assert full["gates"][0]["color"] == "yellow"

    # double activation rejected
    res = await client.post(f"/api/v1/sep/projects/{seed['project_id']}/activate", headers=eng_auth)
    assert res.status_code == 409


async def test_item_update_and_audit(client, eng_auth, seed):
    await _activate(client, eng_auth, seed["project_id"])
    full = await _get_sep(client, eng_auth, seed["project_id"])
    item = full["gates"][0]["items"][0]

    res = await client.patch(
        f"/api/v1/sep/items/{item['id']}",
        json={"status": "done", "remark": "Checked with sales", "responsible_id": seed["engineer_id"]},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "done"
    assert body["completed_at"] is not None
    assert body["responsible_name"] == "Engineer"

    # reopening clears completion timestamp
    res = await client.patch(f"/api/v1/sep/items/{item['id']}", json={"status": "open"}, headers=eng_auth)
    assert res.json()["completed_at"] is None

    # invalid status rejected
    res = await client.patch(f"/api/v1/sep/items/{item['id']}", json={"status": "maybe"}, headers=eng_auth)
    assert res.status_code == 400

    res = await client.get(f"/api/v1/sep/items/{item['id']}/audits", headers=eng_auth)
    audits = res.json()
    fields = [a["field"] for a in audits]
    assert fields.count("status") == 2
    assert "remark" in fields and "responsible_id" in fields


async def test_strict_gate_sequencing_and_dual_sign_off(client, eng_auth, admin_auth, seed):
    await _activate(client, eng_auth, seed["project_id"])
    full = await _get_sep(client, eng_auth, seed["project_id"])
    gate1, gate2 = full["gates"][0], full["gates"][1]

    # pending gate cannot be signed
    res = await client.post(f"/api/v1/sep/gates/{gate2['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 409

    await _clear_gate_items(client, eng_auth, gate1)

    # PM signs; same user cannot also sign quality (4-eyes)
    res = await client.post(f"/api/v1/sep/gates/{gate1['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "in_progress"  # one signature is not enough
    res = await client.post(f"/api/v1/sep/gates/{gate1['id']}/sign-off", json={"role": "quality"}, headers=eng_auth)
    assert res.status_code == 409

    res = await client.post(f"/api/v1/sep/gates/{gate1['id']}/sign-off", json={"role": "quality"}, headers=admin_auth)
    assert res.status_code == 200
    closed = res.json()
    assert closed["status"] == "closed"
    assert closed["color"] == "green"

    # items are locked after close
    res = await client.patch(
        f"/api/v1/sep/items/{gate1['items'][0]['id']}", json={"status": "open"}, headers=eng_auth
    )
    assert res.status_code == 409

    # next gate opened automatically
    full = await _get_sep(client, eng_auth, seed["project_id"])
    assert full["gates"][1]["status"] == "in_progress"


async def test_yellow_gate_requires_complete_action_plan(client, eng_auth, admin_auth, seed, seed_forms):
    await _activate(client, eng_auth, seed["project_id"])
    full = await _get_sep(client, eng_auth, seed["project_id"])
    gate1 = full["gates"][0]

    # leave one item open -> yellow gate, sign-off blocked without risk entry
    for item in gate1["items"][1:]:
        await client.patch(f"/api/v1/sep/items/{item['id']}", json={"status": "not_applicable"}, headers=eng_auth)
    res = await client.post(f"/api/v1/sep/gates/{gate1['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 409
    assert "risk" in res.json()["detail"].lower()

    # risk row without countermeasure still blocks
    inst = await _add_form_risk(client, eng_auth, seed["project_id"], "K0/RG1",
                                risk="Supplier samples late", q=0.2, c=0, s=0.4, p=0.5)
    assert inst["data"]["risks"][0]["priority"] == "low"  # (0.2+0+0.4)*0.5 = 0.3
    res = await client.post(f"/api/v1/sep/gates/{gate1['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 409
    assert "countermeasure" in res.json()["detail"]

    # action plan due date beyond 14 days blocks
    data = inst["data"]
    data["risks"][0].update({"countermeasure": "Expedite via air freight", "due": "2030-01-01",
                             "responsible": seed["engineer_id"]})
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/sep/gates/{gate1['id']}/sign-off", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 409
    assert "14" in res.json()["detail"]

    # complete plan within 14 days -> sign-off passes, dual signature closes
    from datetime import date, timedelta
    data["risks"][0]["due"] = (date.today() + timedelta(days=7)).isoformat()
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    assert res.status_code == 200, res.text
    closed = await _close_gate(client, eng_auth, admin_auth, gate1)
    assert closed["status"] == "closed"


async def test_risk_priority_thresholds(client, eng_auth, seed, seed_forms):
    await _activate(client, eng_auth, seed["project_id"])
    full = await _get_sep(client, eng_auth, seed["project_id"])
    gate1 = full["gates"][0]

    # the legacy sep_risks endpoint still scores rows...
    res = await client.post(
        f"/api/v1/sep/gates/{gate1['id']}/risks",
        json={"effect": "Tooling capacity conflict", "q_impact": 1.0, "c_impact": 1.0,
              "s_impact": 1.0, "probability": 0.9},
        headers=eng_auth,
    )
    risk = res.json()
    assert risk["rkz"] == 2.7
    assert risk["priority"] == "very_high"

    # ...but no longer colours the gate: only the risk assessment form does
    full = await _get_sep(client, eng_auth, seed["project_id"])
    assert full["gates"][0]["color"] == "yellow"
    assert full["gates"][0]["open_risks"] == 0

    inst = await _add_form_risk(client, eng_auth, seed["project_id"], "K0/RG1",
                                risk="Tooling capacity conflict", q=1.0, c=1.0, s=1.0, p=0.9)
    assert inst["data"]["risks"][0]["rkz"] == pytest.approx(2.7)
    assert inst["data"]["risks"][0]["priority"] == "very_high"

    # live high risk turns the gate red
    full = await _get_sep(client, eng_auth, seed["project_id"])
    assert full["gates"][0]["color"] == "red"
    assert full["gates"][0]["open_risks"] == 1

    # finished risk no longer colors the gate
    data = inst["data"]
    data["risks"][0]["status"] = "finished"
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    assert res.status_code == 200, res.text
    full = await _get_sep(client, eng_auth, seed["project_id"])
    assert full["gates"][0]["color"] == "yellow"
    assert full["gates"][0]["open_risks"] == 0


async def test_my_items_queue(client, eng_auth, admin_auth, seed):
    await _activate(client, admin_auth, seed["project_id"])
    full = await _get_sep(client, admin_auth, seed["project_id"])
    item = full["gates"][0]["items"][5]
    await client.patch(
        f"/api/v1/sep/items/{item['id']}", json={"responsible_id": seed["engineer_id"]}, headers=admin_auth
    )

    res = await client.get("/api/v1/sep/my-items", headers=eng_auth)
    mine = res.json()
    assert len(mine) == 1
    assert mine[0]["id"] == item["id"]
    assert mine[0]["gate_code"] == "K0/RG1"
    assert mine[0]["project_name"] == "Project"

    # done items leave the queue
    await client.patch(f"/api/v1/sep/items/{item['id']}", json={"status": "done"}, headers=eng_auth)
    res = await client.get("/api/v1/sep/my-items", headers=eng_auth)
    assert res.json() == []


async def test_overview_and_rollup(client, eng_auth, seed):
    await _activate(client, eng_auth, seed["project_id"])
    res = await client.get("/api/v1/sep/overview", headers=eng_auth)
    overview = res.json()
    assert len(overview) == 1
    assert overview[0]["current_gate"] == "K0/RG1"
    assert overview[0]["total"]["total"] == 232
    assert len(overview[0]["gates"]) == 7

    res = await client.get(f"/api/v1/sep/projects/{seed['project_id']}/rollup", headers=eng_auth)
    rollup = res.json()
    assert rollup["total"]["open"] == 232
    assert rollup["gates"][0]["progress"]["pct"] == 0


async def test_lesson_reference_completes_sep_items(client, eng_auth, seed):
    await _activate(client, eng_auth, seed["project_id"])
    full = await _get_sep(client, eng_auth, seed["project_id"])
    lessons_items = [i for i in full["gates"][0]["items"] if i["lessons_link"]]
    assert len(lessons_items) == 2  # K0 items 10 and 16

    res = await client.post(
        "/api/v1/lessons",
        json={"title": "Late tooling release", "description": "Tooling kickoff was 3 weeks late.",
              "category": "tooling", "lesson_type": "problem", "severity": "high"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    lesson_id = res.json()["id"]

    res = await client.post(
        f"/api/v1/lessons/{lesson_id}/references",
        json={"project_id": seed["project_id"], "note": "Reviewed during K0"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    assert res.json()["sep_items_completed"] == 2

    full = await _get_sep(client, eng_auth, seed["project_id"])
    done = [i for i in full["gates"][0]["items"] if i["lessons_link"]]
    assert all(i["status"] == "done" for i in done)
    assert all("Lesson reuse recorded" in (i["remark"] or "") for i in done)
