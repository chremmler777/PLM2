"""072 renames RFQ/ENG/IND/ECR rows to E<n>/<n> per part, in creation order."""
import importlib.util
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.models.part import Part, PartRevision

MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "072_customer_data_index.py"


def _load_migration():
    # backend/alembic/ shadows the real alembic distribution; the helper in
    # test_change_starter_departments purges it and imports the real one.
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    spec = importlib.util.spec_from_file_location("mig072", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_rename_legacy_revisions(session_factory, seed):
    mod = _load_migration()
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="P-L", name="Legacy",
                    part_type="purchased", created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        ids = {}
        for name, phase, day in [("RFQ1", "rfq_phase", 1), ("ENG1", "engineering", 2),
                                 ("IND1", "freeze", 3), ("ECR1.1", "ecn", 4)]:
            r = PartRevision(part_id=part.id, revision_name=name, phase=phase,
                             status="approved", created_by=seed["admin_id"],
                             created_at=datetime(2026, 1, day))
            s.add(r)
            await s.flush()
            ids[name] = r.id
        await s.commit()

        wc_part = Part(project_id=seed["project_id"], part_number="P-WC", name="WinCarat",
                       part_type="internal_mfg", created_by=seed["admin_id"])
        s.add(wc_part)
        await s.flush()
        wc = PartRevision(part_id=wc_part.id, revision_name="WC-IMP", phase="engineering",
                          status="approved", created_by=seed["admin_id"],
                          created_at=datetime(2026, 1, 1))
        s.add(wc)
        await s.flush()
        ids["WC-IMP"] = wc.id
        wc_part_id = wc_part.id
        await s.commit()

    async with session_factory() as s:
        conn = await s.connection()
        await conn.run_sync(mod.rename_legacy_revisions)
        await s.commit()

    async with session_factory() as s:
        got = {r.id: (r.revision_name, r.phase, r.source, r.parent_revision_id) for r in
               (await s.execute(select(PartRevision))).scalars().all()}
    assert got[ids["RFQ1"]] == ("E1", "review", "customer", None)
    assert got[ids["ENG1"]] == ("E2", "review", "customer", None)
    assert got[ids["IND1"]] == ("1", "official", "customer", None)
    # the old change engine spawned ECR proposals with no parent; the
    # migration links the orphan minor to its official major
    assert got[ids["ECR1.1"]] == ("1.1", "official", "internal", ids["IND1"])
    # WinCarat baseline: official 1, source import, part already in series
    assert got[ids["WC-IMP"]] == ("1", "official", "import", None)
    async with session_factory() as s:
        wc_part = await s.get(Part, wc_part_id)
        legacy_part = await s.get(Part, part.id)
    assert wc_part.lifecycle_phase == "series"
    assert legacy_part.lifecycle_phase == "rfq"
