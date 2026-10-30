"""Plant flags: a project/part shows its plant's country, and both countries
when a part is shared with a project of another plant (BOM line or relation)."""
import pytest

from app.models.entities import Plant, Project
from app.models.part import Part, PartBOMItem, PartRelation, PartRevision
from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _setup(session_factory, seed):
    async with session_factory() as s:
        us = Plant(organization_id=seed["org_id"], name="USA Toccoa", code="usa-toccoa",
                   location="Toccoa, GA, USA", is_active=True)
        mx = Plant(organization_id=seed["org_id"], name="Silao Mexico", code="SIL",
                   location="MX", is_active=True)
        s.add_all([us, mx])
        await s.flush()
        p_us = Project(plant_id=us.id, name="Toccoa job", code="T1", status="active")
        p_mx = Project(plant_id=mx.id, name="Silao job", code="S1", status="active")
        p_mx2 = Project(plant_id=mx.id, name="Silao other", code="S2", status="active")
        s.add_all([p_us, p_mx, p_mx2])
        await s.flush()
        uid = seed["admin_id"]

        def part(pn, project, cat="article"):
            return Part(project_id=project.id, part_number=pn, name=pn, part_type="purchased",
                        item_category=cat, created_by=uid)

        clip = part("CLIP", p_us)          # Toccoa clip, also used by Silao
        fg = part("FG-MX", p_mx)           # Silao assembly using the clip
        tool = part("0067M", p_mx, "tool")
        molded = part("105300004", p_mx)
        lone = part("LONE", p_mx2)
        s.add_all([clip, fg, tool, molded, lone])
        await s.flush()
        rev = PartRevision(part_id=fg.id, revision_name="1", phase="official", status="approved",
                           created_by=uid)
        s.add(rev)
        await s.flush()
        s.add(PartBOMItem(revision_id=rev.id, child_part_id=clip.id, item_number="10",
                          name="CLIP", quantity=2, unit="pcs", position=1, created_by=uid))
        s.add(PartRelation(from_part_id=tool.id, to_part_id=molded.id, relation_type="produces",
                           created_by=uid))
        await s.commit()
        return {"us": p_us.id, "mx": p_mx.id, "mx2": p_mx2.id,
                "clip": clip.id, "fg": fg.id, "tool": tool.id, "molded": molded.id}


async def test_project_countries_mark_shared_projects(client, session_factory, seed):
    ids = await _setup(session_factory, seed)
    h = await login(client, "admin@test.io")
    r = await client.get("/api/v1/plants/projects", headers=h)
    assert r.status_code == 200, r.text
    by_id = {p["id"]: p["countries"] for p in r.json()}
    assert by_id[ids["us"]] == ["US", "MX"]   # its clip is used by a Silao assembly
    assert by_id[ids["mx2"]] == ["MX"]
    assert by_id[ids["mx"]] == ["MX"]         # using a Toccoa clip does not make it Toccoa's


async def test_part_countries_per_project(client, session_factory, seed):
    ids = await _setup(session_factory, seed)
    h = await login(client, "admin@test.io")
    r = await client.get(f"/api/v1/plants/projects/{ids['us']}/part-countries", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {str(ids["clip"]): ["US", "MX"]}
    r = await client.get(f"/api/v1/plants/projects/{ids['mx']}/part-countries", headers=h)
    got = r.json()
    assert got[str(ids["fg"])] == ["MX"]
    assert got[str(ids["tool"])] == ["MX"]
    assert got[str(ids["molded"])] == ["MX"]


async def test_part_countries_unknown_project_404(client, seed):
    h = await login(client, "admin@test.io")
    r = await client.get("/api/v1/plants/projects/99999/part-countries", headers=h)
    assert r.status_code == 404
