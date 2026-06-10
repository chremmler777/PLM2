"""Lessons learned strict-lifecycle tests.

in_review -accept-> in_work -owner sends-> verification -verified-> closed
    `-reject-> rejected           ^---- send back with feedback ----'
"""
import io


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


async def _to_in_work(client, auth, lesson_id, owner_id, target="2030-01-01T00:00:00"):
    """Satisfy the accept gates and move a lesson to in_work. Returns the action id."""
    await client.patch(
        f"/api/v1/lessons/{lesson_id}",
        json={"owner_id": owner_id, "target_date": target},
        headers=auth,
    )
    res = await client.post(
        f"/api/v1/lessons/{lesson_id}/actions",
        json={"description": "Update supplier quoting checklist"},
        headers=auth,
    )
    assert res.status_code == 201, res.text
    action_id = res.json()["id"]
    res = await client.post(
        f"/api/v1/lessons/{lesson_id}/transition", json={"status": "in_work"}, headers=auth
    )
    assert res.status_code == 200, res.text
    return action_id


# ---------------------------------------------------------------- lifecycle


async def test_create_lands_in_review(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth, project_ref="Toccoa Ramp-up")
    assert lesson["status"] == "in_review"
    assert sorted(lesson["allowed_transitions"]) == ["in_work", "rejected"]
    assert lesson["project_id"] is None

    # unlinked filter + link afterwards still work
    res = await client.get("/api/v1/lessons?unlinked=true", headers=eng_auth)
    assert [l["id"] for l in res.json()] == [lesson["id"]]
    res = await client.patch(
        f"/api/v1/lessons/{lesson['id']}", json={"project_id": seed["project_id"]}, headers=eng_auth
    )
    assert res.status_code == 200, res.text
    assert res.json()["project_name"] == "Project"


async def test_accept_gates(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]

    # Nothing defined: all three gates reported
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "in_work"}, headers=eng_auth)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "responsible owner" in detail and "target date" in detail and "action" in detail

    # Owner only — still blocked
    await client.patch(f"/api/v1/lessons/{lid}", json={"owner_id": seed["engineer_id"]}, headers=eng_auth)
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "in_work"}, headers=eng_auth)
    assert res.status_code == 409 and "target date" in res.json()["detail"]

    # Owner + date — still needs an action
    await client.patch(f"/api/v1/lessons/{lid}", json={"target_date": "2030-01-01T00:00:00"}, headers=eng_auth)
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "in_work"}, headers=eng_auth)
    assert res.status_code == 409 and "action" in res.json()["detail"]

    await client.post(
        f"/api/v1/lessons/{lid}/actions", json={"description": "Fix the process"}, headers=eng_auth
    )
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "in_work"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_work"
    assert res.json()["accepted_at"] is not None


async def test_reject_requires_category_and_reason(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]

    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "rejected"}, headers=admin_auth)
    assert res.status_code == 409 and "category" in res.json()["detail"]

    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "rejected", "reject_category": "nonsense", "reject_reason": "x"},
        headers=admin_auth,
    )
    assert res.status_code == 409

    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "rejected", "reject_category": "duplicate"},
        headers=admin_auth,
    )
    assert res.status_code == 409 and "reason" in res.json()["detail"]

    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "rejected", "reject_category": "duplicate", "reject_reason": "Same as lesson 12"},
        headers=admin_auth,
    )
    assert res.status_code == 200, res.text
    assert res.json()["reject_category"] == "duplicate"
    assert res.json()["allowed_transitions"] == []  # terminal

    # Submitter was notified
    res = await client.get("/api/v1/notifications", headers=eng_auth)
    assert any("rejected" in n["title"] for n in res.json())

    # Rejected lessons are read-only
    res = await client.patch(f"/api/v1/lessons/{lid}", json={"tags": "late"}, headers=eng_auth)
    assert res.status_code == 409


async def test_no_alternate_paths(client, eng_auth, admin_auth, seed):
    """Every edge not in the spec map must be refused, from every reachable state."""
    all_states = ["in_review", "in_work", "verification", "closed", "rejected"]
    allowed = {
        "in_review": {"in_work", "rejected"},
        "in_work": {"verification"},
        "verification": {"closed", "in_work"},
        "closed": set(),
        "rejected": set(),
    }

    async def build(state):
        lesson = await _create_lesson(client, eng_auth)
        lid = lesson["id"]
        if state == "in_review":
            return lid
        if state == "rejected":
            res = await client.post(
                f"/api/v1/lessons/{lid}/transition",
                json={"status": "rejected", "reject_category": "out_of_scope", "reject_reason": "n/a"},
                headers=admin_auth,
            )
            assert res.status_code == 200
            return lid
        action_id = await _to_in_work(client, eng_auth, lid, seed["engineer_id"])
        if state == "in_work":
            return lid
        await client.patch(f"/api/v1/lessons/actions/{action_id}", json={"status": "done"}, headers=eng_auth)
        res = await client.post(
            f"/api/v1/lessons/{lid}/transition", json={"status": "verification"}, headers=eng_auth
        )
        assert res.status_code == 200, res.text
        if state == "verification":
            return lid
        res = await client.post(
            f"/api/v1/lessons/{lid}/transition",
            json={"status": "closed", "effectiveness_verified": True},
            headers=admin_auth,
        )
        assert res.status_code == 200, res.text
        return lid

    for state in all_states:
        lid = await build(state)
        for target in all_states:
            if target == state or target in allowed[state]:
                continue
            res = await client.post(
                f"/api/v1/lessons/{lid}/transition", json={"status": target}, headers=admin_auth
            )
            assert res.status_code == 400, f"{state} -> {target} must be refused, got {res.status_code}"


async def test_field_locks_by_state(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]
    action_id = await _to_in_work(client, eng_auth, lid, seed["engineer_id"])

    # Reviewed content locked after acceptance
    res = await client.patch(f"/api/v1/lessons/{lid}", json={"title": "Sneaky new title"}, headers=eng_auth)
    assert res.status_code == 409 and "title" in res.json()["detail"]
    res = await client.patch(f"/api/v1/lessons/{lid}", json={"severity": "low"}, headers=eng_auth)
    assert res.status_code == 409

    # Analysis fields stay open in in_work; target change is audited
    res = await client.patch(
        f"/api/v1/lessons/{lid}",
        json={"root_cause": "Quote template missing tooling lead times", "target_date": "2030-06-01T00:00:00"},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text

    # Move to verification: analysis locked too, project link still allowed
    await client.patch(f"/api/v1/lessons/actions/{action_id}", json={"status": "done"}, headers=eng_auth)
    await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "verification"}, headers=eng_auth)
    res = await client.patch(f"/api/v1/lessons/{lid}", json={"root_cause": "rewrite"}, headers=eng_auth)
    assert res.status_code == 409
    res = await client.patch(f"/api/v1/lessons/{lid}", json={"project_id": seed["project_id"]}, headers=eng_auth)
    assert res.status_code == 200, res.text

    # Actions locked outside in_review/in_work
    res = await client.post(
        f"/api/v1/lessons/{lid}/actions", json={"description": "too late"}, headers=eng_auth
    )
    assert res.status_code == 409
    res = await client.patch(f"/api/v1/lessons/actions/{action_id}", json={"status": "open"}, headers=eng_auth)
    assert res.status_code == 409

    # Audit trail recorded the target date change
    res = await client.get(f"/api/v1/lessons/{lid}", headers=eng_auth)
    bodies = [c["body"] for c in res.json()["comments"] if c["is_system"]]
    assert any("Target date changed" in b for b in bodies)


async def test_verification_gates_and_send_back(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]
    action_id = await _to_in_work(client, eng_auth, lid, seed["engineer_id"])

    # Open action blocks verification
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "verification"}, headers=eng_auth)
    assert res.status_code == 409 and "open" in res.json()["detail"]

    await client.patch(f"/api/v1/lessons/actions/{action_id}", json={"status": "done"}, headers=eng_auth)

    # Only the owner sends to verification (engineer owns it; admin role bypasses)
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "verification"}, headers=eng_auth)
    assert res.status_code == 200, res.text

    # Close without effectiveness blocked
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "closed"}, headers=admin_auth)
    assert res.status_code == 409 and "ffectiveness" in res.json()["detail"]

    # Send back requires feedback
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "in_work"}, headers=admin_auth)
    assert res.status_code == 409 and "feedback" in res.json()["detail"]
    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "in_work", "feedback": "Evidence missing for station 40"},
        headers=admin_auth,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_work"

    # Owner notified of send-back with the feedback
    res = await client.get("/api/v1/notifications", headers=eng_auth)
    assert any("sent back" in n["title"] for n in res.json())

    # Round 2: verify and close
    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "verification"}, headers=eng_auth)
    assert res.status_code == 200
    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "closed", "effectiveness_verified": True, "effectiveness_note": "No recurrence in 3 builds"},
        headers=admin_auth,
    )
    assert res.status_code == 200, res.text
    assert res.json()["closed_at"] is not None
    assert res.json()["effectiveness_note"] == "No recurrence in 3 builds"


async def test_non_owner_cannot_send_to_verification(client, eng_auth, admin_auth, seed):
    # Admin owns the lesson; engineer (non-owner, non-admin) tries to send it
    lesson = await _create_lesson(client, admin_auth)
    lid = lesson["id"]
    action_id = await _to_in_work(client, admin_auth, lid, seed["admin_id"])
    await client.patch(f"/api/v1/lessons/actions/{action_id}", json={"status": "done"}, headers=admin_auth)

    res = await client.post(f"/api/v1/lessons/{lid}/transition", json={"status": "verification"}, headers=eng_auth)
    assert res.status_code == 409 and "owner" in res.json()["detail"]


# ---------------------------------------------------------------- evidence


async def test_evidence_files(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]

    res = await client.post(
        f"/api/v1/lessons/{lid}/files",
        files={"file": ("8d_report.txt", io.BytesIO(b"root cause evidence"), "text/plain")},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    file_id = res.json()["id"]
    assert res.json()["filename"] == "8d_report.txt"

    res = await client.get(f"/api/v1/lessons/{lid}", headers=eng_auth)
    assert [f["filename"] for f in res.json()["files"]] == ["8d_report.txt"]

    res = await client.get(f"/api/v1/lessons/files/{file_id}/download", headers=eng_auth)
    assert res.status_code == 200
    assert res.content == b"root cause evidence"

    # Evidence locked once rejected (terminal)
    res = await client.post(
        f"/api/v1/lessons/{lid}/transition",
        json={"status": "rejected", "reject_category": "insufficient_info", "reject_reason": "n/a"},
        headers=eng_auth,
    )
    assert res.status_code == 200
    res = await client.post(
        f"/api/v1/lessons/{lid}/files",
        files={"file": ("late.txt", io.BytesIO(b"x"), "text/plain")},
        headers=eng_auth,
    )
    assert res.status_code == 409
    res = await client.delete(f"/api/v1/lessons/files/{file_id}", headers=eng_auth)
    assert res.status_code == 409


# ---------------------------------------------------------------- QoL


async def test_duplicate_guard(client, eng_auth, seed):
    await _create_lesson(client, eng_auth, title="Weld fixture misalignment on station 40")
    res = await client.get(
        "/api/v1/lessons/check-duplicates?title=weld fixture issue", headers=eng_auth
    )
    assert res.status_code == 200, res.text
    matches = res.json()
    assert len(matches) == 1
    assert "Weld fixture" in matches[0]["title"]

    res = await client.get(
        "/api/v1/lessons/check-duplicates?title=completely unrelated topic", headers=eng_auth
    )
    assert res.json() == []


async def test_tags_autocomplete(client, eng_auth, seed):
    await _create_lesson(client, eng_auth, tags="welding, Fixture")
    await _create_lesson(client, eng_auth, title="Second weld issue", tags="welding")
    res = await client.get("/api/v1/lessons/tags", headers=eng_auth)
    tags = {t["tag"]: t["count"] for t in res.json()}
    assert tags == {"welding": 2, "fixture": 1}


async def test_mine_filter(client, eng_auth, admin_auth, seed):
    await _create_lesson(client, admin_auth, title="Owned by engineer", owner_id=seed["engineer_id"])
    await _create_lesson(client, admin_auth, title="Owned by admin", owner_id=seed["admin_id"])
    res = await client.get("/api/v1/lessons?mine=true", headers=eng_auth)
    assert [l["title"] for l in res.json()] == ["Owned by engineer"]


async def test_stale_and_time_in_state(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    assert lesson["days_in_state"] is not None
    assert lesson["stale"] is False  # just created


# ---------------------------------------------------------------- reminders / escalation


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


async def test_target_date_escalation(client, eng_auth, admin_auth, seed, session_factory):
    from app.services.lesson_reminder_service import escalate_overdue_targets

    lesson = await _create_lesson(client, admin_auth)
    lid = lesson["id"]
    await _to_in_work(client, admin_auth, lid, seed["engineer_id"], target="2026-01-01T00:00:00")

    async with session_factory() as s:
        assert await escalate_overdue_targets(s) == 1
    async with session_factory() as s:
        assert await escalate_overdue_targets(s) == 0  # 24h dedupe

    res = await client.get("/api/v1/notifications", headers=eng_auth)
    assert any("past target date" in n["title"] for n in res.json())

    # Lesson list shows the overdue flag
    res = await client.get("/api/v1/lessons", headers=eng_auth)
    assert res.json()[0]["target_overdue"] is True


# ---------------------------------------------------------------- misc API


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


async def test_comments_and_detail(client, eng_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    res = await client.post(
        f"/api/v1/lessons/{lesson['id']}/comments",
        json={"body": "We saw the same thing on the Atlanta line."},
        headers=eng_auth,
    )
    assert res.status_code == 201
    assert res.json()["user_name"] == "Engineer"

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
    res = await client.get("/api/v1/lessons?status=in_review", headers=eng_auth)
    assert len(res.json()) == 2


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
    mine = res.json()
    assert len(mine) == 1
    assert mine[0]["description"] == "Engineer's job"
    assert mine[0]["overdue"] is True

    await client.patch(
        f"/api/v1/lessons/actions/{mine[0]['id']}", json={"status": "done"}, headers=eng_auth
    )
    res = await client.get("/api/v1/lessons/my-actions", headers=eng_auth)
    assert res.json() == []


async def test_references_and_kpis(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, eng_auth)
    lid = lesson["id"]

    res = await client.post(
        f"/api/v1/lessons/{lid}/references",
        json={"project_id": seed["project_id"], "note": "Reviewed at kickoff"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/lessons/{lid}/references", json={"project_id": seed["project_id"]}, headers=eng_auth
    )
    assert res.status_code == 409

    res = await client.get(f"/api/v1/lessons/projects/{seed['project_id']}/references", headers=eng_auth)
    assert len(res.json()) == 1

    # Drive a second lesson through the full cycle so closure KPIs have data
    l2 = await _create_lesson(client, eng_auth, title="Cycle KPI lesson")
    action_id = await _to_in_work(client, eng_auth, l2["id"], seed["engineer_id"])
    await client.patch(f"/api/v1/lessons/actions/{action_id}", json={"status": "done"}, headers=eng_auth)
    await client.post(f"/api/v1/lessons/{l2['id']}/transition", json={"status": "verification"}, headers=eng_auth)
    await client.post(
        f"/api/v1/lessons/{l2['id']}/transition",
        json={"status": "closed", "effectiveness_verified": True},
        headers=admin_auth,
    )

    res = await client.get("/api/v1/lessons/kpis", headers=eng_auth)
    kpis = res.json()
    assert kpis["total_lessons"] == 2
    assert kpis["in_review_queue"] == 1
    assert kpis["references_total"] == 1
    assert kpis["avg_time_to_review_days"] is not None
    assert kpis["avg_time_to_close_days"] is not None
    assert kpis["on_time_close_rate"] == 1.0  # closed well before 2030 target
    assert kpis["implementation_rate"] == 1.0
    assert kpis["heatmap"]["high"]["tooling"] == 2
    assert len(kpis["cycle_time_trend"]) == 1


async def test_stats(client, eng_auth, seed):
    await _create_lesson(client, eng_auth, project_ref="Not in PLM yet")
    await _create_lesson(client, eng_auth, project_id=seed["project_id"], category="quality")
    res = await client.get("/api/v1/lessons/stats", headers=eng_auth)
    stats = res.json()
    assert stats["total"] == 2
    assert stats["unlinked"] == 1
    assert stats["by_status"]["in_review"] == 2


async def test_assignable_users_not_admin_gated(client, eng_auth, seed):
    res = await client.get("/api/v1/lessons/assignable-users", headers=eng_auth)
    assert res.status_code == 200, res.text
    names = [u["name"] for u in res.json()]
    assert "Admin" in names and "Engineer" in names
    assert "Ghost" not in names


async def test_owner_assignment_notifies(client, eng_auth, admin_auth, seed):
    lesson = await _create_lesson(client, admin_auth, owner_id=seed["engineer_id"])
    assert lesson["owner_id"] == seed["engineer_id"]
    res = await client.get("/api/v1/notifications", headers=eng_auth)
    titles = [n["title"] for n in res.json()]
    assert any("You own a new lesson" in t for t in titles)
