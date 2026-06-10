"""Project milestone (timing gate) tests."""


async def test_milestone_lifecycle(client, eng_auth, seed):
    pid = seed["project_id"]

    # Create two gates: one overdue, one future
    res = await client.post(
        f"/api/v1/timing/projects/{pid}/milestones",
        json={"name": "Design Freeze", "due_date": "2026-01-15T00:00:00"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    overdue_id = res.json()["id"]
    assert res.json()["overdue"] is True

    res = await client.post(
        f"/api/v1/timing/projects/{pid}/milestones",
        json={"name": "SOP", "due_date": "2030-06-01T00:00:00"},
        headers=eng_auth,
    )
    assert res.json()["overdue"] is False

    # Listed in due-date order
    res = await client.get(f"/api/v1/timing/projects/{pid}/milestones", headers=eng_auth)
    assert [m["name"] for m in res.json()] == ["Design Freeze", "SOP"]

    # Completing clears the overdue flag
    res = await client.patch(
        f"/api/v1/timing/milestones/{overdue_id}", json={"status": "done"}, headers=eng_auth
    )
    assert res.json()["status"] == "done"
    assert res.json()["overdue"] is False
    assert res.json()["completed_at"] is not None

    # Dashboard shows only open milestones (overdue/upcoming)
    res = await client.get("/api/v1/dashboard", headers=eng_auth)
    names = [m["name"] for m in res.json()["milestones"]]
    assert "Design Freeze" not in names  # done

    # Delete
    res = await client.delete(f"/api/v1/timing/milestones/{overdue_id}", headers=eng_auth)
    assert res.status_code == 200
    res = await client.get(f"/api/v1/timing/projects/{pid}/milestones", headers=eng_auth)
    assert len(res.json()) == 1


async def test_dashboard_shows_overdue_milestone(client, eng_auth, seed):
    pid = seed["project_id"]
    await client.post(
        f"/api/v1/timing/projects/{pid}/milestones",
        json={"name": "PPAP Submission", "due_date": "2026-02-01T00:00:00"},
        headers=eng_auth,
    )
    res = await client.get("/api/v1/dashboard", headers=eng_auth)
    milestone = next(m for m in res.json()["milestones"] if m["name"] == "PPAP Submission")
    assert milestone["overdue"] is True
    assert milestone["project_name"] == "Project"


async def test_invalid_milestone_status_rejected(client, eng_auth, seed):
    res = await client.post(
        f"/api/v1/timing/projects/{seed['project_id']}/milestones",
        json={"name": "Gate X", "due_date": "2030-01-01T00:00:00"},
        headers=eng_auth,
    )
    mid = res.json()["id"]
    res = await client.patch(
        f"/api/v1/timing/milestones/{mid}", json={"status": "maybe"}, headers=eng_auth
    )
    assert res.status_code == 400
