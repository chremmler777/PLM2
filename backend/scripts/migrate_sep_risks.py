"""Copy legacy sep_risks rows into each project's risk_assessment form.

Deploy step, run after `alembic upgrade` reaches revision 065 (run_backend.sh
does this automatically). Idempotent: rows already copied are skipped, marked
migrated_from_sep_risk. Exits non-zero on failure so the log shows it.
"""
import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import AsyncSessionLocal  # noqa: E402
from app.forms.risks import copy_sep_risks_to_forms  # noqa: E402


async def main() -> int:
    async with AsyncSessionLocal() as session:
        n = await copy_sep_risks_to_forms(session)
        await session.commit()
    return n


if __name__ == "__main__":
    try:
        copied = asyncio.run(main())
    except Exception:
        print("migrate_sep_risks FAILED: legacy sep_risks were NOT copied into "
              "the risk_assessment forms; gate colour and sign-off will ignore them.",
              file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    print(f"migrate_sep_risks: copied {copied} sep_risks row(s) into risk_assessment forms")
