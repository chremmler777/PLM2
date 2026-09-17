"""SharePoint "Lessons Learned (Toccoa Project Management)" -> PLM2 lessons.

Source: sharepoint_lessons.json, a REST export of the StrategicManagement list
(https://ktxgroup.sharepoint.com/sites/StrategicManagement/Lists/Lessons Learned
Toccoa Project Management). Mapping follows the June 2026 import (commit 0e90a065):
Key Topic -> title, Identified Issue -> description, Necessary Measures ->
recommendation + open action, Priority -> severity, Business Area -> category,
project as free-text ref plus project_id when the code exists locally.
A provenance comment carries LL number, initiator, original status, business
area and evidence links. Everything lands in in_review for team triage.

Idempotent: a lesson whose tags already contain its LL number is skipped.
Runs in the PLM backend container:
    docker exec -e PYTHONPATH=/app claude-plm2-backend-1 python scripts/import_sharepoint_lessons.py [--dry-run]
"""
import asyncio
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.entities import Project
from app.models.lesson import LessonAction, LessonComment, LessonLearned

CREATED_BY = 3  # chris
SP_ROOT = "https://ktxgroup.sharepoint.com"
DATA = Path(__file__).with_name("sharepoint_lessons.json")

# SharePoint user id -> display name (site user list, 2026-09-15)
USERS = {6: "Stocks, Steven", 11: "Demmler, Christoph"}

CATEGORY = {
    "tool build (mold)": "tooling",
    "tooling": "tooling",
    "pre-series samples": "quality",
    "quality / logistics": "logistics",
    "quality / apqp / production": "quality",
    "quality/ development": "quality",
    "assembly": "manufacturing",
    "sales": "project_management",
    "project team": "project_management",
    "sales/ projects/ engineering": "project_management",
}
SEVERITY = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}

# Key Topic repeats across the 2026 batch; give each lesson a distinct title.
TITLES = {
    "LL-0010": "Pre-Series Sample Quality: AI level not etched on tool and parts",
    "LL-0011": "Pre-Series Sample Quality: 3344 received without 2K",
    "LL-0012": "Pre-Series Sample Quality: 3351 samples without engraving",
    "LL-0013": "Tool / Gauge Shipments: incompatible trailers for mold delivery",
    "LL-0014": "Series Production Logistics: 3360 wrong AI level shipped by supplier",
    "LL-0015": "DMC Label Requirements: 3349 shipped without DMC label",
    "LL-0016": "Pre-Series Sample Quality: G67 sample shipments missing critical parts",
    "LL-0017": "Tool / Gauge Shipments: molds shipped without gauges",
    "LL-0018": "BMW Munich Prototype Requirements: samples shipped back for prototype POs",
    "LL-0019": "Pre-Series Sample Quality: identification labels must be removed before BMW",
}


def clean(text):
    return (text or "").replace("\r\n", "\n").strip()


def evidence_links(raw):
    """Extract (title, absolute url) pairs from the rich-text evidence field."""
    if not raw:
        return []
    out = []
    for m in re.finditer(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', raw, re.S):
        href = html.unescape(m.group(1))
        label = re.sub(r"<[^>]+>", "", html.unescape(m.group(2))).strip()
        url = href if href.startswith("http") else SP_ROOT + href
        out.append((label or url, url))
    return out


def map_item(it):
    ll = it["LL_x0023_"]
    project_number = it.get("ProjectNumber")
    code = str(int(project_number)) if project_number else None
    customer = clean(it.get("Customer")) or None
    ref_bits = [b for b in (code, customer) if b]
    project_ref = clean(it.get("ProjectName"))
    if ref_bits:
        project_ref += f" ({', '.join(ref_bits)})"
    tags = [ll.lower(), "sharepoint-import"]
    if customer:
        tags.append(customer.lower().split("/")[0].strip())
    return {
        "ll": ll,
        "title": TITLES.get(ll) or clean(it.get("KeyTopic")) or clean(it.get("ProjectName")),
        "description": clean(it.get("IdentifiedIssue")),
        "recommendation": clean(it.get("NecessaryMeasures")) or None,
        "project_code": code,
        "project_ref": project_ref[:200],
        "category": CATEGORY.get(clean(it.get("BusinessArea")).lower(), "other"),
        "severity": SEVERITY.get((it.get("Priority") or "").lower(), "medium"),
        "tags": ", ".join(tags),
        "initiator": USERS.get(it.get("InitiatorId"), f"SharePoint user {it.get('InitiatorId')}"),
        "original_status": it.get("Status") or "(none)",
        "business_area": clean(it.get("BusinessArea")) or "(none)",
        "evidence": evidence_links(it.get("EvidenceDocuments_x002f_Images")),
        "created": datetime.fromisoformat(it["Created"].replace("Z", "+00:00")).replace(tzinfo=None),
    }


async def main(dry_run):
    items = [map_item(it) for it in json.loads(DATA.read_text())["items"] if it.get("LL_x0023_")]
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        rows = (await db.execute(select(LessonLearned.tags, LessonLearned.title))).all()
        present = {t.strip().lower() for tags, _ in rows if tags for t in tags.split(",")}
        titles = {title.strip().lower() for _, title in rows}  # June import lacks tag on LL-0009
        projects = {p.code: p.id for p in (await db.execute(select(Project))).scalars().all()}

        created = skipped = 0
        for m in items:
            if m["ll"].lower() in present or m["title"].lower() in titles:
                skipped += 1
                continue
            if not m["description"]:
                print(f"{m['ll']}: no identified issue, skipped")
                skipped += 1
                continue
            project_id = projects.get(m["project_code"]) if m["project_code"] else None
            print(f"{m['ll']}: {m['title']}  [{m['category']}/{m['severity']}] "
                  f"project_id={project_id} ref={m['project_ref']!r} evidence={len(m['evidence'])}")
            created += 1
            if dry_run:
                continue
            lesson = LessonLearned(
                title=m["title"][:200], description=m["description"],
                project_id=project_id, project_ref=m["project_ref"],
                category=m["category"], lesson_type="problem", severity=m["severity"],
                recommendation=m["recommendation"], tags=m["tags"],
                status="in_review", created_by=CREATED_BY,
            )
            db.add(lesson)
            await db.flush()
            if m["recommendation"]:
                db.add(LessonAction(lesson_id=lesson.id, description=m["recommendation"],
                                    status="open", created_by=CREATED_BY))
            body = (f"Imported from SharePoint Toccoa Lessons Learned list ({m['ll']}). "
                    f"Initiator: {m['initiator']}. Original status: {m['original_status']}. "
                    f"Business area: {m['business_area']}. "
                    f"Created in SharePoint: {m['created']:%Y-%m-%d}.")
            if m["evidence"]:
                body += " Evidence (SharePoint): " + "; ".join(f"{t} <{u}>" for t, u in m["evidence"])
            db.add(LessonComment(lesson_id=lesson.id, user_id=CREATED_BY, body=body, is_system=False))
        if not dry_run:
            await db.commit()
        print(f"{'would create' if dry_run else 'created'} {created}, skipped {skipped} (already present or empty)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
