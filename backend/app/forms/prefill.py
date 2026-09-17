"""Initial data for a new form instance from project / user context."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Project, Plant
from app.models.sep import SepWorkItem


async def _team_rows(db: AsyncSession, project_id: int) -> list[dict]:
    uids = [u for (u,) in (await db.execute(
        select(SepWorkItem.responsible_id).where(
            SepWorkItem.project_id == project_id, SepWorkItem.responsible_id.isnot(None)
        ).distinct())).all()]
    if not uids:
        return []
    users = (await db.execute(select(User).where(User.id.in_(uids)).order_by(User.full_name))).scalars().all()
    return [{"name": u.full_name, "department": "", "position": "", "phone": "", "email": u.email, "external": False}
            for u in users]


async def build_prefill(db: AsyncSession, body: dict, project: Project, user: User) -> dict:
    plant = await db.get(Plant, project.plant_id)
    scalars = {
        "project.code": project.code,
        "project.name": project.name,
        "project.plant": plant.name if plant else "",
        "user.me": user.id,
        "user.me_name": user.full_name,
        "date.today": date.today().isoformat(),
    }
    data: dict = {}
    for s in body["sections"]:
        if s["kind"] == "fields":
            data[s["id"]] = {f["id"]: scalars.get(f["prefill"]) for f in s["fields"] if f.get("prefill")}
        else:
            data[s["id"]] = await _team_rows(db, project.id) if s.get("prefill") == "team.members" else []
    return data
