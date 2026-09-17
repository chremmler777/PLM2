"""Fill computed fields, computed columns and table footers of a form instance.

Every evaluation is guarded: a cell whose expression blows up on the data at hand
(wrong type, bad function arity) degrades to None -- matching the frontend --
rather than failing the whole save.
"""
from __future__ import annotations

from app.forms.expr import evaluate


def _scope_for_fields(values: dict) -> dict:
    return dict(values)


def recompute(body: dict, data: dict) -> dict:
    out: dict = {}
    for section in body.get("sections", []):
        sid = section["id"]
        if section["kind"] == "fields":
            values = dict(data.get(sid) or {})
            for f in section["fields"]:
                if f["type"] == "computed":
                    try:
                        values[f["id"]] = evaluate(f["expr"], _scope_for_fields(values))
                    except Exception:
                        values[f["id"]] = None
            out[sid] = values
        else:
            rows = [dict(r) for r in (data.get(sid) or [])]
            for row in rows:
                for c in section["columns"]:
                    if c["type"] == "computed":
                        try:
                            row[c["id"]] = evaluate(c["expr"], row)
                        except Exception:
                            row[c["id"]] = None
            out[sid] = rows
            if section.get("footer"):
                footer = {}
                for f in section["footer"]:
                    try:
                        footer[f["label"]] = evaluate(f["expr"], {"_rows": rows})
                    except Exception:
                        footer[f["label"]] = None
                out[f"{sid}_footer"] = footer
    # keep unknown keys (forward compatibility) without overriding computed sections
    for k, v in data.items():
        out.setdefault(k, v)
    return out
