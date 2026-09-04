"""Insert any new form definition versions from app/data/forms into the DB.

Usage (inside the backend container or venv): python scripts/load_form_definitions.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import AsyncSessionLocal  # noqa: E402
from app.forms.loader import load_definitions  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        n = await load_definitions(session)
        await session.commit()
    print(f"inserted {n} definition version(s)")


if __name__ == "__main__":
    asyncio.run(main())
