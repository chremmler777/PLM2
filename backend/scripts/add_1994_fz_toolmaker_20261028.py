"""Toolmaker proposal E1.x on three 1994 parts: FZ toolmaker-modified data sent to Brose
(Philip Paluch) via GlobalX 2026-10-28, awaiting customer confirmation. Requested by Dale Perry
(mails 2026-10-28 10:32 "Files for Brose" and 10:51 "Another file transfer"). Replaces the
10/22 versions (E1.2), which stay open until Brose answers.

Each file becomes a new proposal under the part's latest customer major, named by
RevisionService (E1.3). No part-data mail (requested 2026-10-28): the outbox rows the new
proposal queues are removed in the same transaction. Idempotent: skips a part whose proposal
already holds the same file. Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/add_1994_fz_toolmaker_20261028.py --stage /app/uploads/_stage-1994-fz-1028 [--apply]
"""
import argparse
import asyncio
import hashlib
import os

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.mail import MailOutbox
from app.models.part import Part, PartRevision, RevisionFile
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import store_revision_file

U_DIR = r"U:\Projects\1994\Modified Part Files\Sent to Brose\2026-10-28_GlobalX_to_Paluch"
D = "2026-10-28"
NOTE = ("Toolmaker-modified (FZ 2026-10-28), sent to Brose via GlobalX 2026-10-28, awaiting Brose review. "
        "Brose adopts -> E next; rejects -> close.")
# (Brose no. of the PLM2 article, KTX tool, FZ mold, sent time, extra note, sent file, sha256 from mapping.csv)
PARTS = [
    ("206.881.800", "199404", "FZ-26362", "10:39", "Replaces the 10/22 toolmaker version.",
     f"206.881.800_S00H48-110_A-BRKT-INNER-TRIM_toolmaker-modified_{D}.stp",
     "a4d9b0db9a48b96c77bb2598a7ac97d6e43f07736b0fa534e4cac73f429ee23b"),
    ("206.881.799", "199410", "FZ-26370", "10:39",
     "One file; replaces the 10/22 version (options 1 and 2).",
     f"206.881.799_S00HP8-110_A-BRKT-OUTER-TRIM_toolmaker-modified_{D}.stp",
     "f9e5ac109c62fa41020d5f95117ce7ae729cc25edf966656df69d693d37a642d"),
    ("206.885.967", "199402", "FZ-26364", "11:10",
     "Replaces the 10/22 version; follows Steffen Maciej's 10/27 mail rejecting the shortened clip "
     "(\"retain the original design\").",
     f"206.885.967_S00G0E-110_LATCH-COVER-40_toolmaker-modified_{D}.stp",
     "a365895cbfe540c9cfcc921e189d56c2eaa1c5344f21a9d528113909560412d2"),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        for cpn, tool, mold, sent_at, extra, fname, sha in PARTS:
            src = os.path.join(args.stage, fname)
            if not os.path.exists(src):
                raise SystemExit(f"missing {src}")
            with open(src, "rb") as fh:
                contents = fh.read()
            if hashlib.sha256(contents).hexdigest() != sha:
                raise SystemExit(f"sha256 mismatch {fname}")
            part = (await s.execute(select(Part).where(
                Part.project_id == project.id, Part.customer_part_number == cpn,
                Part.item_category == "article"))).scalar_one()
            revs = (await s.execute(select(PartRevision).where(
                PartRevision.part_id == part.id).order_by(PartRevision.id))).scalars().all()
            majors = [r for r in revs if r.parent_revision_id is None and r.revision_name.startswith("E")]
            base = max(majors, key=lambda r: int(r.revision_name[1:]))
            done = None
            for r in revs:
                if r.parent_revision_id == base.id:
                    hashes = set((await s.execute(select(RevisionFile.file_hash).where(
                        RevisionFile.revision_id == r.id, RevisionFile.is_deleted == False))).scalars())  # noqa: E712
                    if sha in hashes:
                        done = r
            label = f"{cpn} / {part.tier1_part_number} {part.name} (KTX {tool}, {mold})"
            summary = (f"{NOTE} {label}, sent to Brose (Philip Paluch) {D} {sent_at}. {extra} "
                       f"Base {base.revision_name} · {base.customer_index}.")
            print(f"{part.part_number} {label}: base {base.revision_name} id {base.id} "
                  f"({base.status}, index {base.customer_index}), open: "
                  f"{[r.revision_name for r in revs if r.parent_revision_id == base.id]}")
            if done:
                print(f"  file already on {done.revision_name} (id {done.id}); skip")
                continue
            print(f"  attach {fname} ({len(contents) / 1048576:.1f} MB) as cad/step with viewer")
            if not args.apply:
                continue
            first_mail = (await s.execute(select(func.coalesce(func.max(MailOutbox.id), 0)))).scalar_one()
            prop = await RevisionService.create_proposal(s, part.id, base.id, summary=summary, created_by=args.user)
            await s.flush()
            print(f"  created {prop.revision_name} (id {prop.id})")
            rf = await store_revision_file(s, prop, fname, contents, args.user, content_type="application/step")
            rf.cad_data = {"cad_revision": f"FZ toolmaker-modified {D}", "note": NOTE,
                           "toolmaker": "FZ Tools", "fz_mold": mold, "ktx_tool": tool,
                           "sent": f"GlobalX to Brose (Philip Paluch) {D} {sent_at}",
                           "source": U_DIR + r"\02_Sent", "fz_original": U_DIR + r"\01_FZ_original",
                           "evidence": U_DIR + r"\03_Evidence"}
            print(f"  attached file {rf.id}, viewer: {rf.has_viewer}")
            await ChangelogService.log_action(
                s, part_id=part.id, revision_id=prop.id, action="metadata_updated",
                action_description=f"{prop.revision_name} opened for FZ toolmaker data sent to Brose {D}, "
                                   "awaiting confirmation",
                performed_by=args.user, field_name="summary", new_value=summary)
            await s.flush()
            gone = await s.execute(delete(MailOutbox).where(
                MailOutbox.id > first_mail, MailOutbox.part_id == part.id, MailOutbox.mail_status == "pending"))
            print(f"  mail rows suppressed: {gone.rowcount}")
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
