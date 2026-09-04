"""Load JSON form definitions into form_definitions (insert-only, idempotent)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forms import FormDefinition

logger = logging.getLogger(__name__)
DEFINITIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "forms"


def read_definition_files() -> list[dict]:
    out = []
    for f in sorted(DEFINITIONS_DIR.glob("*.json")):
        if f.stem == "expr_vectors":
            continue
        out.append(json.loads(f.read_text()))
    return out


async def load_definitions(session: AsyncSession) -> int:
    existing = {(k, v) for k, v in (await session.execute(
        select(FormDefinition.key, FormDefinition.version))).all()}
    inserted = 0
    for body in read_definition_files():
        if (body["key"], body["version"]) in existing:
            continue
        session.add(FormDefinition(
            key=body["key"], version=body["version"], title=body["title"],
            implements=body.get("implements"), cardinality=body.get("cardinality", "single"),
            gate_items=bool(body.get("gate_items", False)), body=body,
        ))
        inserted += 1
    if inserted:
        await session.flush()
        logger.info("Loaded %d form definition version(s)", inserted)
    return inserted


async def latest_definitions(session: AsyncSession) -> list[FormDefinition]:
    sub = select(FormDefinition.key, func.max(FormDefinition.version).label("v")).group_by(FormDefinition.key).subquery()
    rows = (await session.execute(
        select(FormDefinition).join(sub, (FormDefinition.key == sub.c.key) & (FormDefinition.version == sub.c.v))
        .order_by(FormDefinition.title)
    )).scalars().all()
    return list(rows)


async def latest_definition(session: AsyncSession, key: str) -> FormDefinition | None:
    return (await session.execute(
        select(FormDefinition).where(FormDefinition.key == key).order_by(FormDefinition.version.desc()).limit(1)
    )).scalar_one_or_none()
