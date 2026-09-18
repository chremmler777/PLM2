"""Rules of the customer package receive (pure, no database).

A delivery is the assembly file plus one file per part. A file belongs to
the part whose customer part number (or, failing that, our part number) is
in the filename. If the customer index of the file equals the index already
on the part's active revision, the data did not change and the E does not
change either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ACTION_NEW = "new_major"
ACTION_UNCHANGED = "unchanged"
ACTION_UNMATCHED = "unmatched"
ACTION_ERROR = "error"

_SEP = re.compile(r"[.\s_-]")


@dataclass(frozen=True)
class Candidate:
    part_id: int
    part_number: str
    customer_part_number: str | None
    in_tree: bool  # the assembly itself or a part on its BOM tree


def squash(s: str | None) -> str:
    return _SEP.sub("", (s or "").lower())


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def match_file(filename: str, candidates: list[Candidate]) -> Candidate | None:
    """Tree candidates before project candidates; customer number before our
    number; the longest matching number wins so 3CR.807.531.A beats 3CR.807.531."""
    hay = squash(_stem(filename))
    for in_tree in (True, False):
        for attr in ("customer_part_number", "part_number"):
            best: Candidate | None = None
            best_len = 0
            for c in candidates:
                if c.in_tree != in_tree:
                    continue
                needle = squash(getattr(c, attr))
                if needle and needle in hay and len(needle) > best_len:
                    best, best_len = c, len(needle)
            if best is not None:
                return best
    return None


def index_from_filename(filename: str, customer_part_number: str | None) -> str | None:
    """The single index token right after the customer part number in the
    filename: '3CR807425B_x' -> 'B', '3CR.807.425.B' -> 'B'. Two letters or
    nothing after the number means no index in the name.

    Separators are stripped to match the number, but the index letter itself
    must sit on its own in the *original* filename (bounded by a separator
    or by the end of the stem) so '3CR807425_Unterfahrschutz' does not read
    the 'U' of "Unterfahrschutz" as an index.
    """
    needle = squash(customer_part_number)
    if not needle:
        return None
    stem = _stem(filename)
    # squashed non-separator chars, each paired with its original index
    kept = [(i, ch.lower()) for i, ch in enumerate(stem) if not _SEP.match(ch)]
    squashed = "".join(ch for _, ch in kept)
    pos = squashed.find(needle)
    if pos < 0:
        return None
    end = pos + len(needle)
    if end >= len(kept):
        return None  # number is the last thing in the filename
    i = kept[end][0]  # original index of the first char after the number
    while i < len(stem) and _SEP.match(stem[i]):
        i += 1
    if i >= len(stem) or not stem[i].isalpha():
        return None
    boundary = i + 1 >= len(stem) or bool(_SEP.match(stem[i + 1]))
    if not boundary:
        return None
    return stem[i].upper()


def decide_action(row_index: str | None, current_index: str | None) -> str:
    a = (row_index or "").strip().lower()
    b = (current_index or "").strip().lower()
    return ACTION_UNCHANGED if a and b and a == b else ACTION_NEW
