"""Cavity layout of a tool: "4", or "2+2" for a family tool (2 per article).

The layout is kept as written. "2+2" is never added up to 4, anywhere: it says
how the cavities split between the articles, which a total loses.
"""
import re
from typing import Optional

LAYOUT_RE = re.compile(r"^[1-9]\d{0,2}(\+[1-9]\d{0,2})*$")


def normalize_cavity_layout(value) -> Optional[str]:
    """'2 + 2' -> '2+2', 4 -> '4', '' / None -> None. ValueError when it is no layout."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("cavities must be a number or a layout like 2+2")
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("cavities must be whole numbers")
        value = str(int(value))
    text = re.sub(r"\s+", "", str(value))
    if text == "":
        return None
    if not LAYOUT_RE.match(text):
        raise ValueError("cavities must be a number or a layout like 2+2")
    return text


def layout_from_text(text: Optional[str]) -> Optional[str]:
    """The layout in a free-text cell like '1+1', '2 + 2 cav.' or '4-fach'; None when there is none."""
    if not text:
        return None
    m = re.search(r"\d+(?:\s*\+\s*\d+)*", str(text))
    return re.sub(r"\s+", "", m.group(0)) if m else None
