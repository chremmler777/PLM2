"""Worksheet audit log: the part changelog of a project's parts, limited to
worksheet-relevant actions, with field keys mapped to the worksheet columns,
newest first, filterable, paged by before_id, and exported as CSV."""
import csv
import io
from datetime import datetime

import pytest

from app.models.entities import Organization, Plant, Project
from app.models.part import Part, RevisionChangelog
from app.services.worksheet_audit import audit_field_key

pytestmark = pytest.mark.asyncio


async def _build(session_factory, seed):
    uid = seed["engineer_id"]
    async with session_factory() as s:
        def part(number, project_id=seed["project_id"], category="article", **kw):
            p = Part(project_id=project_id, part_number=number, name=f"Name {number}", part_type="internal_mfg",
                     item_category=category, created_by=uid, **kw)
            s.add(p)
            return p
        art = part("20-1994-001-0", customer_part_number="206.882.251")
        tool = part("199401", category="tool")
        other_project = Project(plant_id=(await s.get(Project, seed["project_id"])).plant_id,
                                name="Other", code="other", status="active")
        org2 = Organization(name="Org 2", code="org-2", is_active=True)
        s.add_all([other_project, org2])
        await s.flush()
        plant2 = Plant(organization_id=org2.id, name="P2", code="p2", location="DE", is_active=True)
        s.add(plant2)
        await s.flush()
        foreign_project = Project(plant_id=plant2.id, name="Foreign", code="foreign", status="active")
        s.add(foreign_project)
        await s.flush()
        stranger = part("99-0000-001-0", project_id=other_project.id)
        await s.flush()

        def log(p, action, field=None, old=None, new=None, desc="d", at=datetime(2026, 9, 20, 10, 0)):
            e = RevisionChangelog(part_id=p.id, action=action, action_description=desc, field_name=field,
                                  old_value=old, new_value=new, performed_by=uid, performed_at=at)
            s.add(e)
            return e
        entries = [
            log(art, "field_comment_added", "part.material", new="Check PA6", desc="Comment on part.material: Check PA6"),
            log(art, "field_flag_set", "part.material", new="open", desc="Flag on part.material: none to open"),
            log(art, "material_set", "part.material", old="PP", new="PA6", desc="Material: PP to PA6"),
            log(art, "metadata_updated", "tier1_part_number", new="S00H4X-110", desc="Tier 1 number from 1994 BOM"),
            log(art, "field_updated", "colour_code", new="NM0", desc="Colour code set to NM0"),
            log(art, "field_updated", "grain", new="KF8", desc="Grain set to KF8"),
            log(tool, "metadata_updated", "tool_cavities", old="4", new="2", desc="Cavities 4 -> 2"),
            log(art, "file_uploaded", desc="file.stp uploaded"),  # not worksheet relevant
            log(art, "metadata_updated", "some_internal_field", new="x"),  # unmapped field: not shown
            log(stranger, "field_comment_added", "part.name", new="elsewhere"),  # other project
        ]
        await s.commit()
        return {"art": art.id, "tool": tool.id, "ids": [e.id for e in entries],
                "foreign_project": foreign_project.id, "other_project": other_project.id}


def _url(seed, suffix=""):
    return f"/api/v1/projects/{seed['project_id']}/worksheet/audit{suffix}"


async def test_lists_worksheet_actions_newest_first_with_mapped_keys(client, eng_auth, seed, session_factory):
    ids = await _build(session_factory, seed)
    r = await client.get(_url(seed), headers=eng_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    entries = body["entries"]
    assert [e["id"] for e in entries] == list(reversed(ids["ids"][:7]))
    assert body["has_more"] is False
    by_action = {(e["action"], e["field_key"]): e for e in entries}
    assert set(by_action) == {
        ("field_comment_added", "part.material"), ("field_flag_set", "part.material"),
        ("material_set", "part.material"), ("metadata_updated", "part.tier1_part_number"),
        ("field_updated", "part.colour_code"), ("field_updated", "part.grain"),
        ("metadata_updated", "tool.cavities"),
    }
    groups = {e["action"]: e["action_group"] for e in entries}
    assert groups == {"field_comment_added": "comments", "field_flag_set": "flags", "material_set": "material",
                      "metadata_updated": "values", "field_updated": "values"}
    cav = by_action[("metadata_updated", "tool.cavities")]
    assert cav["part"] == {"id": ids["tool"], "part_number": "199401", "customer_part_number": None,
                           "item_category": "tool"}
    assert (cav["old_value"], cav["new_value"], cav["description"]) == ("4", "2", "Cavities 4 -> 2")
    assert cav["actor"] == {"id": seed["engineer_id"], "name": "Engineer"}
    assert cav["at"].startswith("2026-09-20T10:00")


async def test_filters_group_part_and_field(client, eng_auth, seed, session_factory):
    ids = await _build(session_factory, seed)
    flags = (await client.get(_url(seed), params={"action_group": "flags"}, headers=eng_auth)).json()["entries"]
    assert [e["action"] for e in flags] == ["field_flag_set"]
    tool = (await client.get(_url(seed), params={"part_id": ids["tool"]}, headers=eng_auth)).json()["entries"]
    assert [e["field_key"] for e in tool] == ["tool.cavities"]
    material = (await client.get(_url(seed), params={"part_id": ids["art"], "field_key": "part.material"},
                                 headers=eng_auth)).json()["entries"]
    assert [e["action"] for e in material] == ["material_set", "field_flag_set", "field_comment_added"]
    # A mapped legacy field name is found by its worksheet key.
    tier1 = (await client.get(_url(seed), params={"field_key": "part.tier1_part_number"},
                              headers=eng_auth)).json()["entries"]
    assert [e["new_value"] for e in tier1] == ["S00H4X-110"]
    text = (await client.get(_url(seed), params={"part": "206.882"}, headers=eng_auth)).json()["entries"]
    assert {e["part"]["id"] for e in text} == {ids["art"]}
    bad = await client.get(_url(seed), params={"action_group": "nope"}, headers=eng_auth)
    assert bad.status_code == 422


async def test_pagination_by_before_id_and_limit_cap(client, eng_auth, seed, session_factory):
    ids = await _build(session_factory, seed)
    first = (await client.get(_url(seed), params={"limit": 3}, headers=eng_auth)).json()
    assert len(first["entries"]) == 3 and first["has_more"] is True
    older = (await client.get(_url(seed), params={"limit": 3, "before_id": first["entries"][-1]["id"]},
                              headers=eng_auth)).json()
    assert [e["id"] for e in older["entries"]] == list(reversed(ids["ids"][:7]))[3:6]
    last = (await client.get(_url(seed), params={"limit": 3, "before_id": older["entries"][-1]["id"]},
                             headers=eng_auth)).json()
    assert len(last["entries"]) == 1 and last["has_more"] is False
    assert (await client.get(_url(seed), params={"limit": 501}, headers=eng_auth)).status_code == 422
    assert (await client.get(_url(seed), params={"limit": 0}, headers=eng_auth)).status_code == 422


async def test_scoped_to_org_and_project(client, eng_auth, seed, session_factory):
    ids = await _build(session_factory, seed)
    r = await client.get(f"/api/v1/projects/{ids['foreign_project']}/worksheet/audit", headers=eng_auth)
    assert r.status_code == 404
    r = await client.get(f"/api/v1/projects/{ids['foreign_project']}/worksheet/audit.csv", headers=eng_auth)
    assert r.status_code == 404
    other = (await client.get(f"/api/v1/projects/{ids['other_project']}/worksheet/audit", headers=eng_auth)).json()
    assert [e["new_value"] for e in other["entries"]] == ["elsewhere"]
    assert (await client.get(_url(seed))).status_code in (401, 403)


async def test_csv_export_with_filters(client, eng_auth, seed, session_factory):
    await _build(session_factory, seed)
    r = await client.get(_url(seed, ".csv"), params={"action_group": "values"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    disposition = r.headers["content-disposition"]
    assert 'filename="proj-worksheet-audit-' in disposition and disposition.endswith('.csv"')
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["Time (UTC)", "User", "KTX no.", "OEM no.", "Group", "Action", "Field", "Old value",
                       "New value", "Description"]
    assert [row[6] for row in rows[1:]] == ["tool.cavities", "part.grain", "part.colour_code", "part.tier1_part_number"]
    assert rows[1][2] == "199401" and rows[1][7:9] == ["4", "2"]


async def test_csv_neutralises_formula_like_text(client, eng_auth, seed, session_factory):
    async with session_factory() as s:
        p = Part(project_id=seed["project_id"], part_number="20-1994-009-0", name="n", part_type="internal_mfg",
                 item_category="article", created_by=seed["engineer_id"])
        s.add(p)
        await s.flush()
        s.add(RevisionChangelog(part_id=p.id, action="field_comment_added", action_description="=HYPERLINK(1)",
                                field_name="part.name", new_value="=1+1", performed_by=seed["engineer_id"]))
        await s.commit()
    r = await client.get(_url(seed, ".csv"), headers=eng_auth)
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[1][8] == "'=1+1" and rows[1][9] == "'=HYPERLINK(1)"


async def test_field_key_mapping():
    assert audit_field_key("metadata_updated", "tier1_part_number") == "part.tier1_part_number"
    assert audit_field_key("metadata_updated", "tool_cavities") == "tool.cavities"
    assert audit_field_key("metadata_updated", "tool_cycle_time_s") == "tool.cycle_time_s"
    assert audit_field_key("field_updated", "colour_code") == "part.colour_code"
    assert audit_field_key("field_updated", "grain") == "part.grain"
    assert audit_field_key("metadata_updated", "customer_index") == "revision.level"
    assert audit_field_key("renumbered", "part_number") == "part.part_number"
    assert audit_field_key("lifecycle_phase", "lifecycle_phase") == "part.lifecycle_phase"
    assert audit_field_key("field_flag_set", "paint.colour") == "paint.colour"
    assert audit_field_key("dfm_topic_opened", None) == "dfm.status"
    assert audit_field_key("paint_updated", None) == "paint.colour"
    assert audit_field_key("metadata_updated", "unknown") is None
    assert audit_field_key("file_uploaded", None) is None
