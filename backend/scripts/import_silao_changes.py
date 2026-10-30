"""AU436 customer changes from Christoph's mail -> PLM changes on project AU436.

LCMEI-7815 (Schlitten stop ribs, incl. the Kunststoffachse force-feeling work
merged into it) and LCMEI-7386 (Blende FS 'Y' gap). Each is created through
ChangeService (number, release gate, changelog) as a customer change, left in
'captured' for the project team to take forward, with the molds as lead items,
every part those molds produce as impacted items, and the mail attachments on
the change.

Idempotent on the title prefix ("LCMEI-7815" / "LCMEI-7386") within AU436.

    docker exec -e PYTHONPATH=/app compose-plm2-backend-1 python \
        /app/uploads/_stage_silao/import_silao_changes.py \
        --stage /app/uploads/_stage_silao [--apply] [--created-by 14]
"""
import argparse
import asyncio
import hashlib
import mimetypes
import os
import shutil
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.change import ChangeRequest
from app.models.entities import Project
from app.models.part import Part, PartRelation
from app.services.change_service import ChangeService

PROJECT_CODE = "AU436"

CHANGES = [
    {
        "key": "LCMEI-7815",
        "title": "LCMEI-7815 Schlitten stop ribs + force feeling (Mannanstroemer zu leichtgaengig), LL+RL",
        "priority": "high",
        "tools": ["0033M", "0060M", "0045M"],
        "mails": ["E0ADEAAE0000", "E0ADE6320000", "E0AE15190000", "E0AE40360000",
                  "E0AE655F0000", "E0AE3FA50000", "E0ADE4F10000", "9E215B850000", "9E2148A50000"],
        "description": (
            "Audi LCMEI-7815 G2 B10 AU436: Mannanstroemer in Horizontalverstellung zu leichtgaengig "
            "(horizontal adjustment of the air vents too easy). Imported from Christoph's mail "
            "2026-10-30; the change ran before AU436 was in PLM.\n\n"
            "Schlitten FS/BFS/Mitte LL+RL (molds 0033M LHD, 0060M RHD, 4 cavities each): stop ribs top "
            "and bottom (4 ribs). V1 2026-02-17 (0.9 mm high), V2 02-18 (max gap 0.4 mm), then Audi asked "
            "for contact: top 1.6+0.8 mm, bottom 0.4 mm. Final 4.036-4.066 g per slide, cycle +2 s, "
            "36 h x 75 EUR. New drawings 260316 (FS DRW_TZ 005, BFS 004, Mitte 004) in KVS 2026-04-16; "
            "in PLM as revision 2 of the FS/BFS/Mitte finished goods. Quoted 2026-02-19, AVON status 410 "
            "2026-06-08, Audi GO before 2026-08-14.\n"
            "Force feeling (2025-12..2026-01, merged into 7815): Kunststoffachse (0045M, POM-GF25) "
            "matching area +0.20 mm, +0.002 g per axle, no runner or drawing change.\n\n"
            "STATUS 2026-10-30: tools 0033M/0060M back from the toolshop with the ribs (2026-10-14); "
            "K30 graining (EDM) of the ribs still open (Uwe confirmed K30, not K31, 2026-10-19). "
            "Kunststoffachse change in the tool: unverified. Open question 2026-02-17: tool 3D showed "
            "2 ribs per Schlitten before this change, customer data none.\n"
            "People: Uwe Schulz (data/KVS), Carlos Gonzalez, Oscar Herrera; Audi Adam Farkas, then "
            "Brodbeck."),
    },
    {
        "key": "LCMEI-7386",
        "title": "LCMEI-7386 Blende FS 'Y' gap on left conduction air vent, LHD+RHD",
        "priority": "medium",
        "tools": ["0026M", "0055M"],
        "mails": ["E0AD72910000", "E0ADE49C0000", "E0ADEBDF0000", "9E2153490000", "9E2154410000",
                  "E0AE3FA50000"],
        "description": (
            "Audi LCMEI-7386 G2 B10 AU436: gap on left conduction air vent (Blende FS 8MB.820.901 LHD "
            "and 8MC.820.902 RHD, molds 0026M / 0055M, molded at DEMO). Imported from Christoph's mail "
            "2026-10-30.\n\n"
            "2025-11..2026-03: cross-dome stiffened, rib version chosen instead of honeycomb; tool needs "
            "2 new sub-inserts and a shouldered block ejector instead of the round ejector; feasible LHD "
            "and RHD (feasibility 2026-02-26). First KTX data in KVS 2025-11-25 "
            "(8MB_820_901_C__DMU_TM__005 ... 251124_KTX).\n"
            "2026-02..10: rib variants V1-V3 (V2 shorter rib at the angled section, V3 side rib moved "
            "1.5 mm, 2.6 mm wall left). Audi passed V1 on a 3D print, then Uwe and Audi settled on V2 "
            "(2026-09-02): +0.104 cm3 / +0.114 g PC/ABS, no runner change.\n\n"
            "STATUS 2026-10-30: not released, 2D/3D not updated, tool NOT changed. Quoted 36 h "
            "CATIA/drawing (Audi buyer wants 18 h), commercial agreement open. V2 LHD print in Puebla; "
            "fit trial at Audi 2026-10-26, result not in mail yet.\n"
            "People: Uwe Schulz, Carlos Gonzalez, Adriana Capri; Audi Rodrigo Garcia, Haimerl, "
            "Ana Cuenya, Hammer."),
    },
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def main(stage, apply, created_by):
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    written = []
    async with Session() as s:
        try:
            proj = (await s.execute(select(Project).where(Project.code == PROJECT_CODE))).scalar_one()
            parts = {p.part_number: p for p in (await s.execute(
                select(Part).where(Part.project_id == proj.id))).scalars()}
            for c in CHANGES:
                if (await s.execute(select(ChangeRequest.id).where(
                        ChangeRequest.project_id == proj.id,
                        ChangeRequest.title.like(c["key"] + "%")))).first():
                    print(f"skip {c['key']}: already in PLM")
                    continue
                missing = [t for t in c["tools"] if t not in parts]
                if missing:
                    raise SystemExit(f"{c['key']}: molds missing: {missing}")
                produced = []
                for t in c["tools"]:
                    for (pid,) in (await s.execute(select(PartRelation.to_part_id).where(
                            PartRelation.from_part_id == parts[t].id,
                            PartRelation.relation_type == "produces"))).all():
                        if pid not in produced:
                            produced.append(pid)
                files = []
                for short in c["mails"]:
                    d = os.path.join(stage, "files", "_mail", short)
                    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                        if fn.lower().startswith(("outlook-", "image", "img_")):
                            continue
                        files.append((short, os.path.join(d, fn), fn))

                ch = await ChangeService.create_change(
                    s, project_id=proj.id, title=c["title"][:255], change_type="physical_part",
                    raised_by=created_by, reason=f"Audi change {c['key']}",
                    description=c["description"], priority=c["priority"],
                    customer_relevant=True, origin="customer")
                ch.issuer = "Audi (LCMEI), via Uwe Schulz / KTX Silao"
                ch.car_line = "Audi Q5 AU436"
                ch.is_series = True
                for t in c["tools"]:
                    await s.refresh(ch, ["impacted_items"])
                    await ChangeService.add_impacted_item(
                        s, ch, parts[t].id, created_by, is_lead=True,
                        impact_note=f"Mold for {c['key']} (from mail)")
                for pid in produced:
                    await s.refresh(ch, ["impacted_items"])
                    await ChangeService.add_impacted_item(
                        s, ch, pid, created_by, is_lead=False,
                        impact_note=f"Produced by an impacted mold ({c['key']})")
                up = os.path.join(os.getcwd(), "uploads", "changes", str(ch.id))
                for short, src, fn in files:
                    stored = os.path.join(up, f"{uuid.uuid4().hex}_{fn}")
                    if apply:
                        os.makedirs(up, exist_ok=True)
                        shutil.copy2(src, stored)
                        written.append(stored)
                    await ChangeService.add_attachment(
                        s, ch, filename=fn[:255], stored_path=stored,
                        content_type=mimetypes.guess_type(fn)[0] or "application/octet-stream",
                        size_bytes=os.path.getsize(src), sha256=sha256(src), user_id=created_by)
                await s.flush()
                print(f"{c['key']}: {ch.change_number} (id {ch.id}) status={ch.status} "
                      f"impacted={len(c['tools'])}+{len(produced)} attachments={len(files)}")
            if apply:
                await s.commit()
            else:
                await s.rollback()
        except BaseException:
            await s.rollback()
            for p in written:
                if os.path.exists(p):
                    os.remove(p)
            raise
    await engine.dispose()
    print("APPLIED" if apply else "DRY RUN (rolled back)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="/app/uploads/_stage_silao")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--created-by", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(main(a.stage, a.apply, a.created_by))
