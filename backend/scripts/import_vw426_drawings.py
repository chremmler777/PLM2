"""Import the VW426 Atlas (project 1864) 2D drawing releases from SharePoint as customer revision history.

Source: ktxgroup.sharepoint.com/sites/KTW_OPVW_426, Shared Documents/08_Develeopment_public/03_Drawing/02_Release
  1 -- 9.16.24 Nomination Release, 2 -- 6.10.25 Release, 3 -- 7.10.26 Release.
The files are downloaded beforehand into --dir, named "<release no>__<original file name>".

Per part, one official customer major per drawing index (user decision 10/05/2026):
  index A goes on the part's existing official revision (sets its customer index and received date),
  B, C, D are new official majors (2, 3, 4) through RevisionService.receive_customer_data without an
  intake source (an import: active at once, no triage). The newest becomes the active revision.
Index source: the letter before the part number in the file name (A_, B_, C_), the letter after
"Out31x-" for the plot files, and for the six 7.10.26 files without a letter the next index after the
part's last known one (user decision; the summary says so, check against the title block).

Idempotent: an index the part already has is not created again, a file name already on that revision
is not stored again. Dry run by default:

    docker exec -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python -m scripts.import_vw426_drawings --dir /tmp/vw426 --user christoph.demmler [--apply]
"""
import argparse
import asyncio
import logging
import os
from datetime import date

from sqlalchemy import select

from app.models import AsyncSessionLocal
from app.models.entities import Project, User
from app.models.part import Part, PartRevision, RevisionFile
from app.services import revision_file_service as rfs
from app.services.part_service import ChangelogService, RevisionService

# Prod may not have the .CATDrawing mapping yet (f58ea193); same value as the code.
rfs.EXTENSION_MAP.setdefault(".catdrawing", ("drawing", "catia"))

PROJECT = "1864"
RELEASES = {
    "1": (date(2024, 9, 16), "9.16.24 Nomination Release"),
    "2": (date(2025, 6, 10), "6.10.25 Release"),
    "3": (date(2026, 7, 10), "7.10.26 Release"),
}
GUESSED = "Index not in the file name: taken as the next after the last known index; check the title block."

# customer part number -> [(index, [files]), ...] in index order; files as "<release>__<name>"
PLAN = {
    "3CR.807.425": [("A", ["1__A_3CR_807_425_DRW_POE.CATDrawing"]),
                    ("B", ["3__3CR_807_425_DRW_POE.CATDrawing"])],
    "3CR.807.425.B": [("A", ["1__A_3CR_807_425_B_DRW_POE.CATDrawing"]),
                      ("B", ["3__3CR_807_425_B_DRW_POE.CATDrawing"])],
    "3CR.807.531.A": [("A", ["1__A_3CR_807_531_A.CATDrawing", "2__A_3CR_807_531_A_DRW_POE.CATDrawing",
                             "2__A_3CR_807_531_A_DRW_POE.CATDrawing.pdf",
                             "2__A_3CR_807_531_A_DRW_POE - Page 2.CATDrawing.pdf"]),
                      ("B", ["2__Out316-B_3CR_807_531_A_DRW_POE.CATDrawing"]),
                      ("C", ["3__3CR_807_531_A_DRW_POE.CATDrawing"])],
    "3CR.807.532.A": [("A", ["1__A_3CR_807_532_A_POE.CATDrawing"]),
                      ("B", ["2__B_3CR_807_532_A_POE.CATDrawing"]),
                      ("C", ["2__Out316-C_3CR_807_532_A_POE.CATDrawing"]),
                      ("D", ["3__3CR_807_532_A_POE.CATDrawing"])],
    "3CR.853.653": [("A", ["1__A_3CR_853_653_DRW_POE.CATDrawing"]),
                    ("B", ["2__B_3CR_853_653_DRW_POE.CATDrawing"]),
                    ("C", ["3__C_3CR_853_653_DRW_POE.CATDrawing"])],
    "3CR.919.491.A": [("A", ["1__A_3CR_919_491_A_DRW_POE.CATDrawing"]),
                      ("B", ["3__B_3CR_919_491_A_DRW_POE.CATDrawing"])],
    "3CR.919.491.C": [("A", ["1__A_3CR_919_491_C_DRW_POE.CATDrawing"]),
                      ("B", ["3__B_3CR_919_491_C_DRW_POE.CATDrawing"])],
    "3CS.807.425": [("A", ["1__A_3CS_807_425_DRW_POE.CATDrawing"]),
                    ("B", ["2__Out314-B_3CS_807_425_DRW_POE.CATDrawing"]),
                    ("C", ["3__3CS_807_425_DRW_POE.CATDrawing"])],
    "3CS.807.643": [("A", ["1__A_3CS_807_643_DRW_POE.CATDrawing"]),
                    ("B", ["2__Out314-B_3CS_807_643_DRW_POE.CATDrawing"]),
                    ("C", ["3__3CS_807_643_DRW_POE.CATDrawing"])],
}


def _guessed(name: str) -> bool:
    base = name.split("__", 1)[1]
    return not (base[:2] in ("A_", "B_", "C_", "D_") or base.startswith("Out31"))


def _summary(files: list[str]) -> str:
    rels = sorted({f.split("__", 1)[0] for f in files})
    text = "VW 2D drawing, " + " and ".join(RELEASES[r][1] for r in rels) + " (SharePoint KTW_OPVW_426, 02_Release)"
    return text + (". " + GUESSED if any(_guessed(f) for f in files) else "")


async def main(folder: str, username: str, apply: bool) -> None:
    missing = [f for steps in PLAN.values() for _, fs in steps for f in fs if not os.path.exists(os.path.join(folder, f))]
    if missing:
        raise SystemExit(f"missing files: {missing}")
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        project = (await db.execute(select(Project).where(Project.code == PROJECT))).scalar_one()
        print(f"project {project.code} {project.name}, as {user.full_name} (id {user.id}), {'APPLY' if apply else 'dry run'}")
        for cpn, steps in PLAN.items():
            part = (await db.execute(select(Part).where(Part.project_id == project.id,
                                                        Part.customer_part_number == cpn))).scalar_one()
            majors = (await db.execute(select(PartRevision).where(PartRevision.part_id == part.id)
                                       .order_by(PartRevision.id))).scalars().all()
            print(f"{cpn} ({part.part_number}): {[(m.revision_name, m.customer_index) for m in majors]}")
            for index, files in steps:
                received = RELEASES[files[0].split("__", 1)[0]][0]
                rev = next((m for m in majors if (m.customer_index or "").upper() == index), None)
                if rev is None and index == "A":
                    first = next((m for m in majors if m.customer_index is None and "." not in m.revision_name), None)
                    if first is None:
                        raise SystemExit(f"{cpn}: no revision without an index to take A")
                    print(f"  A -> existing {first.revision_name}: index A, received {received}")
                    if apply:
                        first.customer_index, first.customer_received_at = "A", received
                        first.summary = first.summary or _summary(files)
                        await ChangelogService.log_action(
                            db, part_id=part.id, revision_id=first.id, action="metadata_updated",
                            action_description=f"Customer index A (VW drawing {RELEASES['1'][1]}) set on "
                                               f"{first.revision_name}", performed_by=user.id,
                            field_name="customer_index", old_value=None, new_value="A")
                    rev = first
                elif rev is None:
                    print(f"  {index} -> new official major, received {received}{' (index assumed)' if any(_guessed(f) for f in files) else ''}")
                    if apply:
                        rev = await RevisionService.receive_customer_data(
                            db, part.id, "official", received, customer_index=index,
                            summary=_summary(files), created_by=user.id)
                        majors.append(rev)
                else:
                    print(f"  {index} -> already {rev.revision_name}")
                have = set() if rev is None or rev.id is None else set((await db.execute(
                    select(RevisionFile.filename).where(RevisionFile.revision_id == rev.id,
                                                        RevisionFile.is_deleted.is_(False)))).scalars())
                for f in files:
                    name = f.split("__", 1)[1]
                    if name in have:
                        print(f"     = {name}")
                        continue
                    print(f"     + {name} ({os.path.getsize(os.path.join(folder, f)) // 1024} KB)")
                    if apply:
                        with open(os.path.join(folder, f), "rb") as fh:
                            contents = fh.read()
                        await rfs.store_revision_file(db, rev, name, contents, uploaded_by=user.id,
                                                      file_type="drawing", kind="DRW",
                                                      note=f"VW release {received:%m/%d/%Y}")
        if apply:
            await db.commit()
            print("committed")
        else:
            await db.rollback()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.dir, a.user, a.apply))
