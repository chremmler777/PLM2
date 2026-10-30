"""Plant country flags for projects and parts (Silao MX / Toccoa US / both).

A project's country is its plant's. A part belongs to its project's plant and
also to every other plant whose projects use it: as a BOM line under one of
their parts, or through a part relation in either direction (a tool producing
it, a mirror, an assembly). So a clip or resin used by Toccoa and Silao shows
both flags, and a project shows both when any of its parts is shared.

Everything is derived; nothing is stored.
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Plant, Project
from app.models.part import Part, PartBOMItem, PartRelation, PartRevision

# plant code -> ISO country; unknown codes fall back to the plant location.
PLANT_COUNTRY = {"usa-toccoa": "US", "SIL": "MX", "WUG": "DE", "main-plant": "DE"}
LOCATION_COUNTRY = (("mx", "MX"), ("mexico", "MX"), ("usa", "US"), ("ga", "US"),
                    ("de", "DE"), ("germany", "DE"))
# Display order: the US plant first, then Mexico, then Germany.
ORDER = {"US": 0, "MX": 1, "DE": 2}


def plant_country(plant: Plant) -> str | None:
    if plant.code in PLANT_COUNTRY:
        return PLANT_COUNTRY[plant.code]
    tokens = set(re.split(r"[\s,]+", (plant.location or "").lower()))
    return next((cc for token, cc in LOCATION_COUNTRY if token in tokens), None)


def _sorted(cs) -> list[str]:
    return sorted((c for c in cs if c), key=lambda c: ORDER.get(c, 9))


async def _project_country(session: AsyncSession) -> dict[int, str | None]:
    rows = (await session.execute(select(Project.id, Plant).join(Plant, Plant.id == Project.plant_id))).all()
    return {pid: plant_country(plant) for pid, plant in rows}


async def part_countries(session: AsyncSession, part_ids: list[int]) -> dict[int, list[str]]:
    """Countries per part: its own project's plant plus every plant that uses it."""
    if not part_ids:
        return {}
    proj_cc = await _project_country(session)
    own = dict((await session.execute(
        select(Part.id, Part.project_id).where(Part.id.in_(part_ids)))).all())
    out: dict[int, set] = defaultdict(set)
    for pid, project_id in own.items():
        out[pid].add(proj_cc.get(project_id))

    # BOM: the part is a child line under a revision of another project's part
    bom = (await session.execute(
        select(PartBOMItem.child_part_id, Part.project_id)
        .join(PartRevision, PartRevision.id == PartBOMItem.revision_id)
        .join(Part, Part.id == PartRevision.part_id)
        .where(PartBOMItem.child_part_id.in_(part_ids)))).all()
    for child, project_id in bom:
        out[child].add(proj_cc.get(project_id))
    # The other direction is not counted: an assembly that uses a Toccoa clip
    # does not become Toccoa's.

    # Relations either way (tool produces part, mirror, assembles, feeds, serves)
    rel = (await session.execute(
        select(PartRelation.from_part_id, PartRelation.to_part_id)
        .where(or_(PartRelation.from_part_id.in_(part_ids), PartRelation.to_part_id.in_(part_ids))))).all()
    other_ids = {x for pair in rel for x in pair} - set(own)
    other_project = dict((await session.execute(
        select(Part.id, Part.project_id).where(Part.id.in_(other_ids))))) if other_ids else {}
    project_of = {**own, **other_project}
    for a, b in rel:
        if a in own:
            out[a].add(proj_cc.get(project_of.get(b)))
        if b in own:
            out[b].add(proj_cc.get(project_of.get(a)))
    return {pid: _sorted(out[pid]) for pid in own}


async def project_part_countries(session: AsyncSession, project_id: int) -> dict[int, list[str]]:
    ids = [i for (i,) in (await session.execute(
        select(Part.id).where(Part.project_id == project_id))).all()]
    return await part_countries(session, ids)


async def project_countries(session: AsyncSession, projects: list[Project]) -> dict[int, list[str]]:
    """Countries per project: its plant, plus the plants that share any of its parts."""
    if not projects:
        return {}
    proj_cc = await _project_country(session)
    ids = [p.id for p in projects]
    out: dict[int, set] = {pid: {proj_cc.get(pid)} for pid in ids}

    # a part of project X used as a BOM line by a part of project Y (other plant)
    child = Part.__table__.alias("child")
    parent = Part.__table__.alias("parent")
    rows = (await session.execute(
        select(child.c.project_id, parent.c.project_id)
        .select_from(PartBOMItem.__table__
                     .join(child, child.c.id == PartBOMItem.child_part_id)
                     .join(PartRevision.__table__, PartRevision.id == PartBOMItem.revision_id)
                     .join(parent, parent.c.id == PartRevision.part_id))
        .where(child.c.project_id != parent.c.project_id)
        .where(or_(child.c.project_id.in_(ids), parent.c.project_id.in_(ids))))).all()
    for cp, pp in rows:
        if cp in out:  # the used part's project is shared with the user's plant
            out[cp].add(proj_cc.get(pp))

    a = Part.__table__.alias("a")
    b = Part.__table__.alias("b")
    rows = (await session.execute(
        select(a.c.project_id, b.c.project_id)
        .select_from(PartRelation.__table__
                     .join(a, a.c.id == PartRelation.from_part_id)
                     .join(b, b.c.id == PartRelation.to_part_id))
        .where(a.c.project_id != b.c.project_id)
        .where(or_(a.c.project_id.in_(ids), b.c.project_id.in_(ids))))).all()
    for pa, pb in rows:
        if pa in out:
            out[pa].add(proj_cc.get(pb))
        if pb in out:
            out[pb].add(proj_cc.get(pa))
    return {pid: _sorted(cs) for pid, cs in out.items()}
