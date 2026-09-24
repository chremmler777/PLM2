"""Field notes over HTTP: threads, comments, flags, project listing, org scoping."""
import pytest

pytestmark = pytest.mark.asyncio


async def _part(client, auth, seed, number, category="article"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": "internal_mfg", "item_category": category}
    r = await client.post("/api/v1/parts", json=body, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_thread_is_empty_until_the_first_comment(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed, "A-1")
    r = await client.get(f"/api/v1/parts/{pid}/field-notes/part.material", headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["id"] is None and r.json()["comments"] == []

    r = await client.post(f"/api/v1/parts/{pid}/field-notes/part.material/comments",
                          json={"body": "Resin to be nominated"}, headers=eng_auth)
    assert r.status_code == 201, r.text
    thread = r.json()
    assert thread["comment_count"] == 1
    assert thread["comments"][0]["body"] == "Resin to be nominated"
    assert thread["comments"][0]["author_name"] == "Engineer"

    r = await client.get(f"/api/v1/parts/{pid}/field-notes", headers=eng_auth)
    assert [n["field_key"] for n in r.json()] == ["part.material"]
    assert "comments" not in r.json()[0]


async def test_flag_set_and_clear_over_http_with_changelog(client, eng_auth, seed):
    tid = await _part(client, eng_auth, seed, "T-1", "tool")
    r = await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag",
                         json={"status": "open"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["flag_status"] == "open"
    assert r.json()["flag_set_by_name"] == "Engineer"
    r = await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag",
                         json={"status": None}, headers=eng_auth)
    assert r.json()["flag_status"] is None
    r = await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag",
                         json={"status": "maybe"}, headers=eng_auth)
    assert r.status_code == 422
    log = (await client.get(f"/api/v1/parts/{tid}/changelog", headers=eng_auth)).json()
    assert [e["action"] for e in log if e["action"].startswith("field_")] == ["field_flag_set", "field_flag_set"]


async def test_clearing_a_missing_flag_returns_an_empty_thread(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed, "A-1")
    r = await client.put(f"/api/v1/parts/{pid}/field-notes/part.name/flag", json={"status": None}, headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["id"] is None


@pytest.mark.parametrize("key", ["Tool.cavities", "cavities", "tool.cavities"])
async def test_bad_field_keys_are_400(client, eng_auth, seed, key):
    pid = await _part(client, eng_auth, seed, "A-1")  # an article: tool.cavities does not apply
    r = await client.post(f"/api/v1/parts/{pid}/field-notes/{key}/comments", json={"body": "x"}, headers=eng_auth)
    assert r.status_code == 400, r.text
    assert "detail" in r.json()
    r = await client.get(f"/api/v1/parts/{pid}/field-notes/{key}", headers=eng_auth)
    assert r.status_code == 400


async def test_empty_and_blank_comments(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed, "A-1")
    r = await client.post(f"/api/v1/parts/{pid}/field-notes/part.name/comments", json={"body": ""}, headers=eng_auth)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/parts/{pid}/field-notes/part.name/comments", json={"body": "   "}, headers=eng_auth)
    assert r.status_code == 400


async def test_project_listing_includes_tools_and_stays_in_the_project(client, eng_auth, seed, session_factory):
    from app.models.entities import Project
    from app.models.part import Part
    aid = await _part(client, eng_auth, seed, "A-1")
    tid = await _part(client, eng_auth, seed, "T-1", "tool")
    async with session_factory() as s:
        home = await s.get(Project, seed["project_id"])
        other = Project(plant_id=home.plant_id, name="Other", code="other", status="active")
        s.add(other)
        await s.flush()
        foreign = Part(project_id=other.id, part_number="F-1", name="F", part_type="internal_mfg",
                       item_category="article", created_by=seed["engineer_id"])
        s.add(foreign)
        await s.commit()
        other_id, foreign_id = other.id, foreign.id
    await client.post(f"/api/v1/parts/{aid}/field-notes/part.material/comments", json={"body": "a"}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag", json={"status": "open"}, headers=eng_auth)
    await client.post(f"/api/v1/parts/{foreign_id}/field-notes/part.name/comments", json={"body": "b"}, headers=eng_auth)

    r = await client.get(f"/api/v1/projects/{seed['project_id']}/field-notes", headers=eng_auth)
    assert r.status_code == 200
    assert sorted((n["part_id"], n["field_key"]) for n in r.json()) == sorted(
        [(aid, "part.material"), (tid, "tool.cavities")])
    r = await client.get(f"/api/v1/projects/{other_id}/field-notes", headers=eng_auth)
    assert [n["part_id"] for n in r.json()] == [foreign_id]


async def test_other_org_part_and_project_are_404(client, eng_auth, session_factory, seed):
    from app.models.entities import Organization, Plant, Project
    from app.models.part import Part
    async with session_factory() as s:
        org = Organization(name="Other Org FN", code="other-org-fn", is_active=True)
        s.add(org)
        await s.flush()
        plant = Plant(organization_id=org.id, name="P", code="p-fn", location="DE", is_active=True)
        s.add(plant)
        await s.flush()
        project = Project(plant_id=plant.id, name="X", code="x-fn", status="active")
        s.add(project)
        await s.flush()
        part = Part(project_id=project.id, part_number="X-1", name="X", part_type="internal_mfg",
                    item_category="article", created_by=seed["admin_id"])
        s.add(part)
        await s.commit()
        pid, prj = part.id, project.id
    assert (await client.get(f"/api/v1/parts/{pid}/field-notes", headers=eng_auth)).status_code == 404
    assert (await client.post(f"/api/v1/parts/{pid}/field-notes/part.name/comments",
                              json={"body": "x"}, headers=eng_auth)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{prj}/field-notes", headers=eng_auth)).status_code == 404
