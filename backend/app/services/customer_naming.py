"""Customer filename conventions: read the customer index and the data kind
from a delivered filename. Detection only prefills the upload dialog; the
user always chooses. See docs/CUSTOMER_DATA_INDEX.md, "Customer file names".
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services.customer_package import index_from_filename

CONVENTIONS: dict[str, str] = {"vw": "VW group", "scout": "Scout"}

KIND_LABELS: dict[str, str] = {
    "PCA": "PCA engineering master: full construction model with RPS, reference points/lines, "
           "annotations. Open this one in CATIA.",
    "DMU": "DMU lightweight solid for packaging and quick viewing, no RPS or references. Archive copy.",
    "DRW": "DRW customer part drawing.",
}

# 206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528
# 206_881_971_B__PCA_TM__001_____...          variant letter
# 206_881_971____G02_TM__004_003_MAP_POCKET   assembly position + two indexes
_VW_HEAD = re.compile(
    r"^(?P<a>\d{3})_(?P<b>\d{3})_(?P<c>\d{3})(?:_(?P<variant>[A-Z]))?_+"
    r"(?P<kind>[A-Z]\d{2}|[A-Z]{3})_(?P<model>[A-Z]{2})__(?P<index>\d{3})",
    re.I,
)
_VW_RELEASE = re.compile(r"(B[-_]RELEASE|CP\d|ADS)", re.I)
_VW_DATE = re.compile(r"(?<!\d)(\d{4})-?(\d{2})-?(\d{2})(?!\d)")
_G_POS = re.compile(r"^G\d{2}$")


@dataclass
class ParsedName:
    filename: str
    customer_part_number: Optional[str] = None
    variant: Optional[str] = None
    kind: Optional[str] = None
    kind_label: Optional[str] = None
    model_type: Optional[str] = None
    customer_index: Optional[str] = None
    release: Optional[str] = None
    dated: Optional[date] = None


def kind_label(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return None
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    if _G_POS.match(kind):
        return f"Assembly position {kind}."
    return None


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _parse_vw(filename: str) -> ParsedName:
    stem = _stem(filename)
    out = ParsedName(filename=filename)
    m = _VW_HEAD.match(stem)
    if not m:
        return out
    number = f"{m['a']}.{m['b']}.{m['c']}"
    variant = m["variant"].upper() if m["variant"] else None
    out.customer_part_number = f"{number}.{variant}" if variant else number
    out.variant = variant
    out.kind = m["kind"].upper()
    out.kind_label = kind_label(out.kind)
    out.model_type = m["model"].upper()
    out.customer_index = m["index"]
    tail = stem[m.end():]
    rel = _VW_RELEASE.search(tail)
    if rel:
        out.release = rel.group(1).upper()
    for dm in _VW_DATE.finditer(tail):
        try:
            out.dated = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            continue
    return out


def parse_filename(filename: str, convention: Optional[str],
                   customer_part_number: Optional[str] = None) -> ParsedName:
    """Parse one filename under a convention. None = the letter-index rule
    that the package flow has always used (needs the part's customer number)."""
    if convention is None:
        return ParsedName(filename=filename,
                          customer_index=index_from_filename(filename, customer_part_number))
    if convention not in CONVENTIONS:
        raise ValueError(f"Unknown customer naming convention '{convention}'")
    # Scout has not shown a distinct grammar yet; it parses like VW group.
    return _parse_vw(filename)
