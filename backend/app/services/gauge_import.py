"""Plan the FM-QUA-0094-17 gauge-inventory import.

Pure decision logic over plain rows so it can be tested without Excel or a
database. The importer script reads the sheet, calls plan_import, prints the
report, and only then writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.equipment_numbering import equipment_number, normalise_tool_ref

GAUGE_FAMILY = 4
MAX_PER_TOOL = 10

# Sheet rows that are not gauges. Keyed by (zero-padded tool, legacy no) with the
# reason, so a re-import cannot silently resurrect them.
EXCLUSIONS: dict[tuple[str, str], str] = {
    ("3457", "P1403"): "PDC brackets are measured by caliber, not gauged "
                       "(Christoph, 2026-07-24)",
}


@dataclass
class GaugeRow:
    """One data row of the inventory sheet."""
    customer: str
    tool_ref: str
    description: str
    legacy_no: str
    storage: str


@dataclass
class PlannedGauge:
    part_number: str
    name: str
    notes: str
    owner_tool: str
    serves: list[str] = field(default_factory=list)
    legacy_no: str = ""


def plan_import(
    rows: list[GaugeRow],
    known_tools: set[str],
    existing: set[tuple[str, str]],
) -> tuple[list[PlannedGauge], list[str]]:
    """Turn sheet rows into a write plan plus a human-readable report.

    ``known_tools`` are the zero-padded numbers of tool parts that exist. Rows
    naming anything else are skipped and reported — this importer never creates a
    tool. ``existing`` holds (owner tool, legacy no) pairs already imported; the
    legacy number alone is not unique across the sheet.
    """
    plan: list[PlannedGauge] = []
    report: list[str] = []
    next_index: dict[str, int] = {}

    for r in rows:
        tools = normalise_tool_ref(r.tool_ref)
        if not tools:
            report.append(f"SKIP unparseable tool reference {r.tool_ref!r} "
                          f"({r.legacy_no} {r.description})")
            continue

        unknown = [t for t in tools if t not in known_tools]
        if unknown:
            report.append(f"SKIP {r.tool_ref!r}: no tool part for "
                          f"{', '.join(unknown)} ({r.legacy_no} {r.description})")
            continue

        owner = tools[0]  # normalise_tool_ref sorts, so this is the lowest
        if len(tools) > 1:
            report.append(f"COLLAPSE {r.tool_ref!r} -> owner {owner}, "
                          f"serves {', '.join(tools)} ({r.legacy_no})")

        reason = EXCLUSIONS.get((owner, r.legacy_no))
        if reason is not None:
            report.append(f"EXCLUDE {owner} / {r.legacy_no}: {reason}")
            continue

        if (owner, r.legacy_no) in existing:
            report.append(f"SKIP already imported: {owner} / {r.legacy_no}")
            continue

        index = next_index.get(owner, 0)
        if index >= MAX_PER_TOOL:
            report.append(f"SKIP {r.legacy_no}: tool {owner} already has "
                          f"{MAX_PER_TOOL} gauges; op code has one index digit")
            continue
        next_index[owner] = index + 1

        notes = (f"Legacy gauge no: {r.legacy_no}. Storage: {r.storage}. "
                 f"Customer: {r.customer}. Sheet tool ref: {r.tool_ref}.")
        plan.append(PlannedGauge(
            part_number=equipment_number(owner, GAUGE_FAMILY, index),
            name=r.description.strip(),
            notes=notes,
            owner_tool=owner,
            serves=tools,
            legacy_no=r.legacy_no,
        ))

    return plan, report
