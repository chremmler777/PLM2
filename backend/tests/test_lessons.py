"""Lessons learned module tests - capture, link-later, lifecycle, actions, comments."""


async def _create_lesson(client, auth, **overrides):
    payload = {
        "title": "Late tooling release",
        "description": "Tooling kickoff was 3 weeks late because supplier quotes stalled.",
        "category": "tooling",
        "lesson_type": "problem",
        "severity": "high",
    }
    payload.update(overrides)
    res = await client.post("/api/v1/lessons", json=payload, headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


async def test_create_unlinked_then_link_later(client, eng_auth, seed):
    # Capture without a PLM project — the user's real-world workaround
    lesson = await _create_lesson(
        client, eng_auth, project_ref="Toccoa Ramp-up"
    )
    assert lesson["project_id"] is None
    assert lesson["project_ref"] == "Toccoa Ramp-up"
    assert lesson["status"] == "draft"
    assert lesson["allowed_transitions"] == ["submitted"]

    # Shows up in the unlinked filter
    res = await client.get("/api/v1/lessons?unlinked=true", headers=eng_auth)
    assert [l["id"] for l in res.json()] == [lesson["id"]]

    # Link afterwards to a real project
    res = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"project_id": seed["project_id"]},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    assert res.json()["project_id"] == seed["project_id"]
    assert res.json()["project_name"] == "Project"

    res = await client.get("/api/v1/lessons?unlinked=true", headers=eng_auth)
    assert res.json() == []


async def test_create_with_bad_project_404(client, eng_auth, seed):
    res = await client.post(
        "/api/v1/lessons",
        json={"title": "Bad link", "description": "points nowhere", "project_id": 9999},
        headers=eng_auth,
    )
    assert res.status_code == 404


async def test_invalid_enum_rejected(client, eng_auth, seed):
    res = await client.post(
        "/api/v1/lessons",
        json={"title": "Bad category", "description": "x" * 10, "category": "nonsense"},
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_lifecycle_and_close_guard(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, eng_auth, project_id=seed["project_id"])
    lid = lesson["id"]

    # Illegal jump draft -> approved
    res = await client.post(
        f"/api/v1/lessons/{lid}/transition", json={"status": "approved"}, headers=eng_auth
    )
    assert res.status_code == 400

    # Approval without an owner is blocked (accountability gate)
    for s in ("submitted", "in_review"):
        res = await client.post(
            f"/api/v1/lessons/{lid}/transition", json={"status": s}, headers=admin_auth
        )
        assert res.status_code == 200, res.text
    res = await client.post(
        f"/api/v1/lessons/{lid}/transition", json={"status": "approved"}, headers=admin_auth
    )
    assert res.status_code == 409
    assert "owner" in res.json()["detail"].lower()

    # Assign an owner, then approve -> implemented
    res = await client.patch(
        f"/api/v1/lessons/{lid}", json={"owner_id": seed["engineer_id"]}, headers=admin_auth
    )
    assert res.status_code == 200, res.text
    for s in ("approved", "implemented"):
        res = await client.post(
            f"/api/v1/lessons/{lid}/transition", json={"status": s}, headers=admin_auth
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == s
        if s == "approved":
            assert res.json()["approved_at"] is not None

    # Add an open action — closing must now be blocked
    res = await client.post(
        f"/api/v1/lessons/{lid}/actions",
        json={"description": "Update supplier quoting checklist", "assignee_id": seed["engineer_id"]},
        headers=admin_auth,
    )
    assert res.status_code == 201, res.text
    action_id = res.json()["id"]

    res = await client.post(
        f"/api/v1/lessons/{lid}/transition", json={"status": "closed"}, headers=admin_auth
    )
    assert res.status_code == 409

    # Complete the action, then closing works
    res = await client.patch(
        f"/api/v1/lessons/actions/{action_id}", json={"status": "done"}, headers=eng_auth
    )
    assert res.json()["status"] == "done"
    assert res.json()["completed_at"] is not None

    # Closing without effectiveness verification is blocked
    res = await client.post(
        f"/api/v1/lessons/{lid}/transition", json={"status": "closed"}, headers=admin_auth
    )
    assert res.status_code == 409
    assert "effectiveness" in res.json()["detail"].lower()

    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "closed", "effectiveness_verified": True,
              "effectiveness_note": "Checklist used on next sourcing round, no delay"},
        headers=admin_auth,
    )
    assert res.status_code == 200, res.text
    assert res.json()["closed_at"] is not None
    assert res.json()["effectiveness_note"] is not None

    # Closed lessons are read-only
    res = await client.patch(f"/api/v1/lessons/{lid}", json={"title": "new title"}, headers=eng_auth)
    assert res.status_code == 409

    # Transitions left a system-comment audit trail
    res = await client.get(f"/api/v1/lessons/{lid}", headers=eng_auth)
    detail = res.json()
    system_comments = [c for c in detail["comments"] if c["is_system"]]
    assert len(system_comments) == 5  # submitted, in_review, approved, implemented, closed
    assert "draft → submitted" in system_comments[0]["body"]


async def test_rejected_back_to_draft(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]
    for s in ("submitted", "in_review", "rejected", "draft"):
        res = await client.post(
            f"/api/v1/lessons/{lid}/transition", json={"status": s}, headers=eng_auth
        )
        assert res.status_code == 200, res.text


async def test_comments_and_detail(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    res = await client.post(
        f"/api/v1/lessons/{lesson['id']}/comments",
        json={"body": "We saw the same thing on the Atlanta line."},
        headers=eng_auth,
    )
    assert res.status_code == 201
    assert res.json()["user_name"] == "Engineer"
    assert res.json()["is_system"] is False

    res = await client.get(f"/api/v1/lessons/{lesson['id']}", headers=eng_auth)
    detail = res.json()
    assert detail["created_by_name"] == "Engineer"
    assert len(detail["comments"]) == 1


async def test_filters_and_search(client, eng_auth, seed):
    await _create_lesson(client, eng_auth, title="Weld fixture misalignment",
                         category="manufacturing", severity="critical", tags="welding,fixture")
    await _create_lesson(client, eng_auth, title="Great supplier onboarding",
                         category="supplier", lesson_type="success", severity="low")

    res = await client.get("/api/v1/lessons?category=manufacturing", headers=eng_auth)
    assert [l["title"] for l in res.json()] == ["Weld fixture misalignment"]

    res = await client.get("/api/v1/lessons?lesson_type=success", headers=eng_auth)
    assert [l["title"] for l in res.json()] == ["Great supplier onboarding"]

    res = await client.get("/api/v1/lessons?q=welding", headers=eng_auth)
    assert [l["title"] for l in res.json()] == ["Weld fixture misalignment"]


async def test_stats(client, eng_auth, seed):
    l1 = await _create_lesson(client, eng_auth, project_ref="Not in PLM yet")
    await _create_lesson(client, eng_auth, project_id=seed["project_id"], category="quality")
    await client.post(
        f"/api/v1/lessons/{l1['id']}/actions",
        json={"description": "Overdue action", "due_date": "2026-01-01T00:00:00"},
        headers=eng_auth,
    )

    res = await client.get("/api/v1/lessons/stats", headers=eng_auth)
    stats = res.json()
    assert stats["total"] == 2
    assert stats["unlinked"] == 1
    assert stats["open_actions"] == 1
    assert stats["overdue_actions"] == 1
    assert stats["by_status"]["draft"] == 2
    assert stats["by_category"] == {"tooling": 1, "quality": 1}


async def test_my_actions_queue(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, admin_auth)
    await client.post(
        f"/api/v1/lessons/{lesson['id']}/actions",
        json={"description": "Engineer's job", "assignee_id": seed["engineer_id"],
              "due_date": "2026-01-01T00:00:00"},
        headers=admin_auth,
    )
    await client.post(
        f"/api/v1/lessons/{lesson['id']}/actions",
        json={"description": "Someone else's job", "assignee_id": seed["admin_id"]},
        headers=admin_auth,
    )

    res = await client.get("/api/v1/lessons/my-actions", headers=eng_auth)
    assert res.status_code == 200, res.text
    mine = res.json()
    assert len(mine) == 1
    assert mine[0]["description"] == "Engineer's job"
    assert mine[0]["lesson_title"] == lesson["title"]
    assert mine[0]["overdue"] is True

    # Completed actions drop off the queue
    await client.patch(
        f"/api/v1/lessons/actions/{mine[0]['id']}", json={"status": "done"}, headers=eng_auth
    )
    res = await client.get("/api/v1/lessons/my-actions", headers=eng_auth)
    assert res.json() == []


async def test_references_and_kpis(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]
    await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "submitted"}, headers=eng_auth)

    # Reference the lesson for the project; duplicate is rejected
    res = await client.post(
        f"/api/v1/lessons/{lid}/references",
        json={"project_id": seed["project_id"], "note": "Reviewed at kickoff"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/lessons/{lid}/references",
        json={"project_id": seed["project_id"]},
        headers=eng_auth,
    )
    assert res.status_code == 409

    res = await client.get(
        f"/api/v1/lessons/projects/{seed['project_id']}/references", headers=eng_auth
    )
    refs = res.json()
    assert len(refs) == 1
    assert refs[0]["lesson_title"] == lesson["title"]
    assert refs[0]["note"] == "Reviewed at kickoff"

    res = await client.get("/api/v1/lessons/kpis", headers=eng_auth)
    kpis = res.json()
    assert kpis["total_lessons"] == 1
    assert kpis["references_total"] == 1
    assert kpis["reuse_rate"] == 1.0  # 1 referenced / 1 non-draft
    assert kpis["in_review_queue"] == 1
    assert kpis["by_category"]["tooling"] == 1
    assert kpis["by_severity"]["high"] == 1


async def test_overdue_reminders_dedupe(client, eng_auth, admin_auth, seed, session_factory):
    from app.services.lesson_reminder_service import send_overdue_action_reminders

    lesson = await _create_lesson(client, admin_auth)
    await client.post(
        f"/api/v1/lessons/{lesson['id']}/actions",
        json={"description": "Overdue thing", "assignee_id": seed["engineer_id"],
              "due_date": "2026-01-01T00:00:00"},
        headers=admin_auth,
    )

    async with session_factory() as s:
        assert await send_overdue_action_reminders(s) == 1
    async with session_factory() as s:
        assert await send_overdue_action_reminders(s) == 0  # within 24h window

    res = await client.get("/api/v1/notifications", headers=eng_auth)
    overdue_notes = [n for n in res.json() if "Overdue lesson action" in n["title"]]
    assert len(overdue_notes) == 1


async def test_assignable_users_not_admin_gated(client, eng_auth, seed):
    res = await client.get("/api/v1/lessons/assignable-users", headers=eng_auth)
    assert res.status_code == 200, res.text
    names = [u["name"] for u in res.json()]
    assert "Admin" in names and "Engineer" in names
    assert "Ghost" not in names  # inactive users excluded


async def test_owner_assignment_notifies(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, admin_auth, owner_id=seed["engineer_id"])
    assert lesson["owner_id"] == seed["engineer_id"]

    res = await client.get("/api/v1/notifications", headers=eng_auth)
    assert res.status_code == 200, res.text
    titles = [n["title"] for n in res.json()]
    assert any("You own a new lesson" in t for t in titles)
