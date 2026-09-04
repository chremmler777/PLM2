"""Copy legacy sep_risks rows into each project's risk_assessment form.

Deploy step, run once after `alembic upgrade` reaches revision 065:
    python scripts/migrate_sep_risks.py
Idempotent: rows already copied are skipped (marked migrated_from_sep_risk).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import AsyncSessionLocal  # noqa: E402
from app.forms.risks import copy_sep_risks_to_forms  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        n = await copy_sep_risks_to_forms(session)
        await session.commit()
    print(f"copied {n} sep_risks row(s) into risk_assessment forms")


if __name__ == "__main__":
    asyncio.run(main())
