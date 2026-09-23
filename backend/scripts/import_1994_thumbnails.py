"""Import article thumbnails for a project from an RFQ2 export, then give
every tool that still has no thumbnail the picture of the first article it
produces.

PLM and RFQ2 are separate databases, so this is a two-step process:

  1. Export from RFQ2 (see scripts/export_rfq_thumbnails.sql), e.g.:

       docker exec -i rfq2-postgres-1 psql -U rfq_user -d rfq_db \\
           -v rfq_id=26 -f scripts/export_rfq_thumbnails.sql -t -A \\
           > /tmp/rfq26_thumbs.jsonl

  2. Import into PLM (this script), against the PLM database:

       docker exec -i -e PYTHONPATH=/app <plm-backend-container> \\
           python scripts/import_1994_thumbnails.py --file /path/in/container.jsonl \\
           [--project 1994] [--apply]

Each JSON line is {"part_number": "<raw bom_items.part_number>",
"thumbnail": "<data URI>"}. The raw part_number looks like
"S00G77-000\\n206_887_233" (Brose number, newline, VW number with
underscores) - the second line, underscores turned to dots, is matched
against Part.customer_part_number within the project.

Thumbnails are written through app.services.thumbnail_service.set_thumbnail,
the same function the PUT /parts/{id}/thumbnail endpoint uses, so there is
one code path for "a part gets a thumbnail image" and one changelog action
name ("thumbnail_updated").

Dry run by default; prints the plan (matched, unmatched, tools covered) and
writes nothing until --apply.
"""
import argparse
import asyncio
import base64
import json
import os
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRelation
from app.services.thumbnail_service import InvalidThumbnail, sniff_image

DATA_URI_RE = re.compile(r"^data:[^;]+;base64,(.+)$", re.DOTALL)


def parse_vw_number(raw_part_number: str) -> str | None:
    """Second line of the raw bom_items.part_number, underscores to dots.
    None if there is no second line."""
    lines = (raw_part_number or "").splitlines()
    if len(lines) < 2 or not lines[1].strip():
        return None
    return lines[1].strip().replace("_", ".")


def decode_data_uri(data_uri: str) -> bytes:
    m = DATA_URI_RE.match((data_uri or "").strip())
    if not m:
        raise ValueError("not a data: URI")
    return base64.b64decode(m.group(1))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="jsonl export from export_rfq_thumbnails.sql")
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with open(args.file) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        articles = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.item_category == "article"))).scalars().all()
        by_customer_number = {a.customer_part_number: a for a in articles if a.customer_part_number}

        matched: list[tuple[Part, bytes]] = []  # (article, image bytes)
        unmatched: list[str] = []
        for row in rows:
            raw = row.get("part_number", "")
            vw_number = parse_vw_number(raw)
            article = by_customer_number.get(vw_number) if vw_number else None
            if article is None:
                unmatched.append(f"{raw!r} (parsed {vw_number!r})")
                continue
            try:
                content = decode_data_uri(row.get("thumbnail", ""))
                sniff_image(content)  # validate png/jpeg/webp, raises otherwise
            except (ValueError, InvalidThumbnail) as e:
                unmatched.append(f"{raw!r} matched {article.part_number} but image invalid: {e}")
                continue
            matched.append((article, content))

        print(f"== ARTICLE THUMBNAILS ({len(matched)} matched, {len(unmatched)} unmatched)")
        for article, content in matched:
            print(f"   {article.part_number:<12} {article.customer_part_number:<20} {len(content)} bytes")
        if unmatched:
            print(f"\n-- unmatched ({len(unmatched)}):")
            for u in unmatched:
                print(f"   {u}")

        # Tools with no thumbnail get the picture of the first article they produce.
        tools = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.item_category == "tool"))).scalars().all()
        tools_without_thumb = [t for t in tools if not t.thumbnail_path]
        relations = (await s.execute(select(PartRelation).where(
            PartRelation.relation_type == "produces",
            PartRelation.from_part_id.in_([t.id for t in tools_without_thumb]),
        ).order_by(PartRelation.id))).scalars().all() if tools_without_thumb else []
        by_article_id = {a.id: (a, content) for a, content in matched}
        first_produced: dict[int, int] = {}  # tool_id -> article_id (first 'produces' relation)
        for r in relations:
            first_produced.setdefault(r.from_part_id, r.to_part_id)

        tool_plan: list[tuple[Part, Part, bytes]] = []  # (tool, source article, content)
        for tool in tools_without_thumb:
            article_id = first_produced.get(tool.id)
            if article_id is None:
                continue
            source = by_article_id.get(article_id)
            if source is None:
                continue  # that article has no new thumbnail in this run and none on disk either
            article, content = source
            tool_plan.append((tool, article, content))

        print(f"\n== TOOLS COVERED ({len(tool_plan)} of {len(tools_without_thumb)} without a thumbnail)")
        for tool, article, _content in tool_plan:
            print(f"   {tool.part_number:<12} <- {article.part_number} ({article.customer_part_number})")

        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return

        from app.services.thumbnail_service import set_thumbnail

        for article, content in matched:
            await set_thumbnail(s, article, content, args.user, source_note="RFQ2 import")
        for tool, article, content in tool_plan:
            await set_thumbnail(s, tool, content, args.user,
                               source_note=f"copied from {article.part_number}")
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
