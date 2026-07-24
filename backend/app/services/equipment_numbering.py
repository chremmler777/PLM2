"""Equipment numbering: <tool#>[-<2-digit op code>].

Adopted 2026-07-24 from the 'Naming of Equipment' thread. Molds keep the bare
tool number — they take no -00 suffix — so the 251 existing tool records are
untouched. See docs/superpowers/specs/2026-07-24-equipment-numbering-and-gauge-import-design.md
"""
from __future__ import annotations

import re

TOOL_WIDTH = 4

# First digit of the op code -> kind of equipment.
OP_CODE_KINDS: dict[int, str] = {
    1: "eoat",
    2: "in_cell_station",
    3: "secondary_station",
    4: "gauge",
}

# A sheet cell may name several tools ("918/919") and may carry a cavity or
# variant suffix ("3197-001-0"). Only the leading 3-4 digit run identifies a tool.
_TOOL_TOKEN = re.compile(r"^(\d{3,4})")

# Linkage vocabulary added alongside part_relations' existing
# produces / checks / assembles / related.
#   serves - equipment -> each tool it covers. The number carries only the
#            lowest such tool, so these rows are the authority on coverage.
#   feeds  - tool -> downstream tool whose station consumes its parts.
EQUIPMENT_RELATION_TYPES = frozenset({"serves", "feeds"})


def normalise_tool_ref(raw: str) -> list[str]:
    """Sheet tool reference -> sorted, zero-padded 4-char tool numbers.

    Splits multi-tool cells on '/', drops cavity/variant suffixes, and pads to the
    width the PLM stores ('745' -> '0745'). Returns [] when nothing parses, so the
    caller can report the row instead of inventing a tool.
    """
    out: list[str] = []
    for chunk in str(raw).split("/"):
        m = _TOOL_TOKEN.match(chunk.strip())
        if m:
            out.append(m.group(1).zfill(TOOL_WIDTH))
    return sorted(dict.fromkeys(out))


def classify(op_code: str) -> str:
    """Op code -> kind of equipment. Raises ValueError on an unknown family."""
    if not re.fullmatch(r"\d{2}", op_code):
        raise ValueError(f"Op code must be exactly two digits, got {op_code!r}")
    kind = OP_CODE_KINDS.get(int(op_code[0]))
    if kind is None:
        raise ValueError(f"Unknown op-code family {op_code!r}")
    return kind


def parse_equipment_number(number: str) -> tuple[str, str | None]:
    """Split an equipment number into (tool number, op code or None).

    Split on the LAST hyphen: the tool namespace already uses hyphens two other
    ways — '0674-2' is the second tool of 0674, and the 91-xxxx family numbers
    tools '91-0001'. Only a two-digit tail in a known family is an op code;
    everything else belongs to the tool. So a second tool owns its equipment
    nestedly: '0674-2-40' -> ('0674-2', '40').
    """
    head, sep, tail = number.rpartition("-")
    if not sep:
        return number, None
    if not re.fullmatch(r"\d{2}", tail):
        return number, None          # part of the tool's own number
    classify(tail)                   # a bad family is a typo, not a tool number
    return head, tail


def equipment_number(tool: str, op_family: int, index: int) -> str:
    """Compose a number: ('3454', 4, 1) -> '3454-41'."""
    if op_family not in OP_CODE_KINDS:
        raise ValueError(f"Unknown op-code family {op_family}")
    if not 0 <= index <= 9:
        raise ValueError(
            f"Only 10 slots per family; index {index} does not fit in one digit")
    return f"{tool}-{op_family}{index}"


def item_category_for(op_code: str) -> str:
    """Which parts.item_category an op code belongs in.

    Gauges are split out from generic equipment: they are inventoried, audited,
    and owned by Quality rather than Tooling.
    """
    return "gauge" if classify(op_code) == "gauge" else "assembly_equipment"
