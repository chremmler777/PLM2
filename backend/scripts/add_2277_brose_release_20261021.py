"""2277 Brose Backpanel: first CAD in PLM2 (approved by Christoph 2026-10-21 via Ass).

Brose B-RELEASE 2026-08-28, received 2026-09-17, from
U:\\RFQ\\RFQ25_260112_Brose Backpanel\\20_Current\\260917_Datain (components from
20260917_KTX\\971_KVS). One CATPart per part, filed as review data E2 with
customer_index = the TM index, gated (in_review, intake pending for
Development's triage), one batch. The GEO/KPR/OUT CATProducts are the assembly
structure and reference the parts; PLM2 has no assembly attach, so they stay on
U: (noted in cad_data). 971_A and the 971 C/D AEKO variants of 10/13 are not
touched. Also sets tool_cavities on 227701 (2) and 227702 (1+1).

Project 2277 has no part data mail list, so nothing is mailed.
Idempotent: skips a part whose revision already holds the file. Dry run by
default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/add_2277_brose_release_20261021.py --stage /app/uploads/_stage-2277-20261021 [--apply]
"""
import argparse
import asyncio
import hashlib
import os
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionFile
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import store_revision_file

SRC = r"U:\RFQ\RFQ25_260112_Brose Backpanel\20_Current\260917_Datain"
KVS = SRC + r"\20260917_KTX\971_KVS"
RECEIVED = date(2026, 9, 17)

# part_number, customer_part_number, file, index, sha256, source folder
FILES = [
    ("20-2277-001-0", "206.881.971",
     "206_881_971____PCA_TM__005_____SEAT_BACK_PANEL____B-RELEASE___20260828.CATPart", "005",
     "f7b4a173ed29540d0e545b6783630b03962899cca129c8eebe1e322a6b5deb3a", SRC),
    ("20-2277-002-0", "206.881.971.B",
     "206_881_971_B__PCA_TM__001_____SEAT_BACK_PANEL____B-RELEASE___20260828.CATPart", "001",
     "3e7c6e934df1add265327a870a12c638a07491a4dc7cde954e0d6686a5798193", SRC),
    ("20-2277-003-0", "206.881.972.A",
     "206_881_972_A__PCA_TM__003_____SEAT_BACK_PANEL____B-RELEASE___20260828.CATPart", "003",
     "4d7080408917eb6bca3c37646ba1ca15ef92da30bac9bd4021e5e83032b8e369", SRC),
    ("20-2277-004-0", "206.881.971_G02",
     "206_881_971____G02_TM__005_____MAP_POCKET_________B-RELEASE___20260828.CATPart", "005",
     "741cfa018e1e566a121721abb67fd8c239e9e5069b8eb08efdc72b8e7bd67ed1", KVS),
    ("20-2277-005-0", "206.881.971_G05",
     "206_881_971____G05_TM__005_____PIVOT_AXIS_________B-RELEASE___20260828.CATPart", "005",
     "35c9b98a17a30d89deaad1259e56ef1935ac491ece9219f5ede709ff4a1baa92", KVS),
    ("20-2277-006-0", "206.881.971_G07",
     "206_881_971____G07_TM__002_____ROSSETTE___________B-RELEASE___20260828.CATPart", "002",
     "1a0be360861801a0a5d62ad0f673729c78f64a6d9b7814ba0c802e1ab378b3fe", KVS),
    ("50-2277-001-0", "206.881.971_G03",
     "206_881_971____G03_TM__005_____SPRING_____________B-RELEASE___20260828.CATPart", "005",
     "bcdc3596f8c10878c2a0aaec26901aa4b15c3ae567f65dc4b5176784c8c414a6", KVS),
    ("50-2277-002-0", "206.881.971_G04",
     "206_881_971____G04_TM__005_____RUBBER_BUMPER______B-RELEASE___20260828.CATPart", "005",
     "fb00b789429790b125a9b916b85afabc7d28ae7fe8695ac7ceeaed458b65e8a4", KVS),
    ("50-2277-003-0", "206.881.971_G06",
     "206_881_971____G06_TM__002_____STRAP_SUB_ASSY_____B-RELEASE___20260828.CATPart", "002",
     "7d60d4d6b6652d7db51dc66a58ef14563118afad772e9ab8213f04b2ed5db50d", KVS),
]
CAVITIES = {"227701": "2", "227702": "1+1"}


def load(stage, fname, sha):
    src = os.path.join(stage, fname)
    if not os.path.exists(src):
        raise SystemExit(f"missing {src}")
    with open(src, "rb") as fh:
        contents = fh.read()
    digest = hashlib.sha256(contents).hexdigest()
    if digest != sha:
        raise SystemExit(f"sha256 mismatch on {fname}: {digest}")
    return contents, digest


async def file_on_part(s, part, digest):
    return (await s.execute(select(RevisionFile).join(PartRevision).where(
        PartRevision.part_id == part.id, RevisionFile.file_hash == digest,
        RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712


async def file_part(s, project, row, stage, user, batch, apply):
    number, cpn, fname, index, sha, folder = row
    part = (await s.execute(select(Part).where(
        Part.project_id == project.id, Part.part_number == number))).scalar_one()
    if part.customer_part_number != cpn:
        raise SystemExit(f"{number}: customer number {part.customer_part_number} != {cpn}, stop")
    contents, digest = load(stage, fname, sha)
    if dup := await file_on_part(s, part, digest):
        print(f"{number} {cpn}: file already filed (file {dup.id}); skip")
        return
    print(f"{number} {cpn}: new E-index {index} (pending triage) + {fname} ({len(contents) / 1048576:.1f} MB)")
    if not apply:
        return
    summary = (f"Customer review data, index {index}: {cpn} {part.name}, Brose B-RELEASE 2026-08-28, "
               f"received 2026-09-17 ({folder}). First CAD in PLM2; replaces the awarded quote baseline. "
               f"Assembly structure (GEO/KPR/OUT CATProducts) stays on U:.")
    rev = await RevisionService.receive_customer_data(
        s, part.id, "review", RECEIVED, customer_index=index, summary=summary,
        created_by=user, intake_source="customer_data", batch_id=batch)
    await s.flush()
    rf = await store_revision_file(s, rev, fname, contents, user)
    rf.cad_data = {"cad_revision": f"TM {index}, B-RELEASE 2026-08-28",
                   "received": "Brose 2026-09-17", "source": folder,
                   "note": "GEO/KPR/OUT CATProducts (assembly structure) not attached; on U:."}
    await s.commit()
    print(f"  created {rev.revision_name} (id {rev.id}, {rev.status}), file {rf.id}")


async def set_cavities(s, project, user, apply):
    for number, value in CAVITIES.items():
        tool = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.part_number == number,
            Part.item_category == "tool"))).scalar_one()
        old = tool.tool_cavities
        print(f"{number} tool_cavities {old!r} -> {value!r}{'  (unchanged)' if old == value else ''}")
        if not apply or old == value:
            continue
        tool.tool_cavities = value
        await ChangelogService.log_action(
            s, part_id=tool.id, action="updated",
            action_description=f"Cavities set to {value} (Christoph 2026-10-21)",
            performed_by=user, field_name="tool_cavities", old_value=old, new_value=value)
    if apply:
        await s.commit()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--project", default="2277")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    batch = f"2277-brose-20260917-{uuid.uuid4().hex[:6]}"
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        for row in FILES:
            await file_part(s, project, row, args.stage, args.user, batch, args.apply)
        await set_cavities(s, project, args.user, args.apply)
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
