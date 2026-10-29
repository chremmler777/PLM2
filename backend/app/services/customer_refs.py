"""F9 (test 2026-10-27, Christoph's rule): what the customer reads leads
with the customer's own numbers and keeps KTX's internal numbers internal.
A change title is built from our part number and the part name
("20-3101-001-1 - 1383 BOTTOM COVER LEFT G01 LCI"): the customer copy drops
our part number, our project code and our CR number, and names the
customer's part numbers where the parts carry them."""
import re
from typing import Iterable, Optional

#: our article number at the front of an auto title, "+1" for further parts
_KTX_PART = re.compile(r"^\s*\d{2}-\d{4}-\d{3}-\d+(?:\s*\+\s*\d+)?\s*-\s*")
#: our 4-digit project code in front of the part name ("1383 BOTTOM ...")
_PROJECT_CODE = re.compile(r"^\s*\d{4}\s+(?=\S)")
#: our article numbers anywhere else in a title
_KTX_PART_ANY = re.compile(r"\b\d{2}-\d{4}-\d{3}-\d+\b")


def customer_title(title: Optional[str], drop: Iterable[Optional[str]] = ()) -> str:
    """The change title as the customer may read it. drop: numbers already
    named in front (the customer part numbers), not repeated in the title.
    Audit 2026-10-29 (P2-3): the auto title is now "<our part> - <customer
    part> - <project> <name>", so every " - " segment is cleaned, not only
    the first."""
    t = _KTX_PART.sub("", title or "")
    t = _KTX_PART_ANY.sub("", t)
    dropped = {(n or "").strip() for n in drop if (n or "").strip()}
    parts = [_PROJECT_CODE.sub("", seg).strip() for seg in re.split(r"\s+-\s+", t)]
    t = " - ".join(p for p in parts if p and p not in dropped)
    t = re.sub(r"\s{2,}", " ", t).strip(" -:")
    return t or "your change request"


def customer_numbers(numbers: Iterable[Optional[str]]) -> str:
    """'51 12 7 123456, 51 12 7 123457' (customer part numbers, no blanks)."""
    seen: list[str] = []
    for n in numbers:
        n = (n or "").strip()
        if n and n not in seen:
            seen.append(n)
    return ", ".join(seen)


def customer_heading(title: Optional[str], numbers: Iterable[Optional[str]] = ()) -> str:
    """Customer part numbers first, then the title without our numbers."""
    numbers = list(numbers)
    nums = customer_numbers(numbers)
    name = customer_title(title, numbers)
    return f"{nums} {name}" if nums else name


async def change_customer_numbers(session, change) -> list[str]:
    """The impacted parts' customer part numbers, the lead part first."""
    from sqlalchemy import select
    from app.models.change import ChangeImpactedItem
    from app.models.part import Part
    rows = (await session.execute(
        select(Part.customer_part_number, ChangeImpactedItem.is_lead)
        .join(ChangeImpactedItem, ChangeImpactedItem.part_id == Part.id)
        .where(ChangeImpactedItem.change_id == change.id)
        .order_by(ChangeImpactedItem.is_lead.desc(), ChangeImpactedItem.id))).all()
    return [n for n, _ in rows if n]
