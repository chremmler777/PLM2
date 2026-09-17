"""Revision name rules.

The major number is always a customer-stated data state; the minor number is
always our internal iteration on it. Review data is E-prefixed (E1, E1.1),
official data is a bare number (1, 1.1). The two counters are independent and
never reset. Once a part has official data, new review data is refused.
"""
from __future__ import annotations

import re
from datetime import datetime

NAME_RE = re.compile(r"^(E?)([1-9]\d*)(?:\.([1-9]\d*))?$")
LEGACY_RE = re.compile(r"^(RFQ|ENG|IND|ECR)([1-9]\d*)(?:\.([1-9]\d*))?$")

STATEMENT_REVIEW = "review"
STATEMENT_OFFICIAL = "official"
STATEMENTS = (STATEMENT_REVIEW, STATEMENT_OFFICIAL)


class RevisionRuleViolation(ValueError):
    """A naming rule was broken (e.g. review data after official data)."""


def parse_name(name: str) -> tuple[bool, int, int | None]:
    m = NAME_RE.match(name or "")
    if not m:
        raise ValueError(f"Not a revision name: {name!r}")
    prefix, major, minor = m.groups()
    return (prefix == "", int(major), int(minor) if minor else None)


def format_name(is_official: bool, major: int, minor: int | None = None) -> str:
    base = f"{'' if is_official else 'E'}{major}"
    return base if minor is None else f"{base}.{minor}"


def _majors(names: list[str]) -> list[tuple[bool, int]]:
    out = []
    for n in names:
        is_official, major, minor = parse_name(n)
        if minor is None:
            out.append((is_official, major))
    return out


def next_major_name(existing_major_names: list[str], statement: str) -> str:
    if statement not in STATEMENTS:
        raise ValueError(f"statement must be one of {STATEMENTS}, got {statement!r}")
    want_official = statement == STATEMENT_OFFICIAL
    majors = _majors(existing_major_names)
    if not want_official and any(is_official for is_official, _ in majors):
        raise RevisionRuleViolation(
            "This part already has official customer data; the customer cannot "
            "un-release it, so new data must be official too.")
    highest = max((n for is_off, n in majors if is_off == want_official), default=0)
    return format_name(want_official, highest + 1)


def next_minor_name(parent_name: str, existing_child_names: list[str]) -> str:
    is_official, major, minor = parse_name(parent_name)
    if minor is not None:
        raise ValueError(f"{parent_name} is a proposal; proposals hang off majors only")
    highest = 0
    for child in existing_child_names:
        c_off, c_major, c_minor = parse_name(child)
        if c_off == is_official and c_major == major and c_minor is not None:
            highest = max(highest, c_minor)
    return format_name(is_official, major, highest + 1)


def legacy_rename(
    rows: list[tuple[int, str, str, int | None, datetime]],
) -> dict[int, tuple[str, str]]:
    """Map one part's legacy revisions to the new scheme.

    RFQ and ENG majors become E1..Ek in creation order; their proposals keep
    the parent's new major. IND majors become 1..k. ECR<n>.<m> proposals hang
    off official major <n> if it exists, else the latest official major, else
    the latest review major (E<k>.<m>), else a name-only official major 1.
    Orphans get consecutive minors. Rows that already carry new-style names
    pass through unchanged.
    """
    ordered = sorted(rows, key=lambda r: (r[4], r[0]))
    result: dict[int, tuple[str, str]] = {}
    review_count = 0
    official_count = 0
    legacy_major_to_new: dict[str, str] = {}
    minors_under: dict[str, int] = {}

    for rid, name, phase, parent_id, _ in ordered:
        if NAME_RE.match(name):
            is_official, major, minor = parse_name(name)
            result[rid] = (name, "official" if is_official else "review")
            if minor is None:
                if is_official:
                    official_count = max(official_count, major)
                else:
                    review_count = max(review_count, major)
            else:
                key = format_name(is_official, major)
                minors_under[key] = max(minors_under.get(key, 0), minor)
            continue
        m = LEGACY_RE.match(name)
        if not m:
            raise ValueError(f"Cannot migrate revision name {name!r} (id {rid})")
        prefix, major_s, minor_s = m.groups()
        legacy_major = f"{prefix}{major_s}"
        if minor_s is None:
            if prefix in ("RFQ", "ENG"):
                review_count += 1
                new, new_phase = format_name(False, review_count), "review"
            else:
                official_count += 1
                new, new_phase = format_name(True, official_count), "official"
            legacy_major_to_new[legacy_major] = new
            result[rid] = (new, new_phase)
        else:
            if prefix == "ECR":
                target = legacy_major_to_new.get(f"IND{major_s}")
                if target is None:
                    # Orphan ECR (old change engine spawned it without a
                    # parent). Hang it off the latest official major; if the
                    # part never had official data, off the latest review
                    # major so the name does not claim a release that never
                    # happened.
                    if official_count > 0:
                        target = format_name(True, min(int(major_s), official_count))
                    elif review_count > 0:
                        target = format_name(False, review_count)
                    else:
                        official_count = 1
                        target = format_name(True, 1)
                is_off_t, _, _ = parse_name(target)
                new_phase = "official" if is_off_t else "review"
            else:
                target = legacy_major_to_new.get(legacy_major)
                if target is None:
                    raise ValueError(f"Proposal {name} (id {rid}) has no migrated parent")
                new_phase = "official" if prefix == "IND" else "review"
            minors_under[target] = minors_under.get(target, 0) + 1
            is_off, mj, _ = parse_name(target)
            result[rid] = (format_name(is_off, mj, minors_under[target]), new_phase)
    return result
