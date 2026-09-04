"""Static validation of form definitions and submit-time completeness check."""
from __future__ import annotations

from app.forms.expr import evaluate, ExprError

FIELD_TYPES = {"text", "multiline", "number", "date", "checkbox", "choice", "multichoice", "user", "computed"}
PREFILL_ROOTS = {"project.code", "project.name", "project.plant", "user.me", "user.me_name", "date.today", "team.members"}
SIGNATURE_ROLES = ("md", "pm", "quality", "dt")
CARDINALITIES = ("single", "multi")


def _template_item_refs(template: dict) -> set[str]:
    return {f"{g['code']}:{i['item_no']}" for g in template["gates"] for i in g["items"]}


def _check_expr(expr: str, ids: list[str], problems: list[str], where: str) -> None:
    scope = {i: 0 for i in ids}
    scope["_rows"] = [dict(scope)]
    try:
        evaluate(expr, scope)
    except ExprError as e:
        problems.append(f"{where}: bad expression {expr!r}: {e}")


def validate_definition(body: dict, template: dict) -> list[str]:
    p: list[str] = []
    for req in ("key", "version", "title", "cardinality", "sections"):
        if req not in body:
            p.append(f"missing top-level key {req}")
    if p:
        return p
    if body["cardinality"] not in CARDINALITIES:
        p.append(f"cardinality must be one of {CARDINALITIES}")
    refs = _template_item_refs(template)
    for ref in body.get("sep_items", []):
        if ref not in refs:
            p.append(f"sep_items: unknown SEP item {ref}")
    for role in body.get("signatures", []):
        if role not in SIGNATURE_ROLES:
            p.append(f"signatures: unknown role {role}")
    section_ids: set[str] = set()
    for s in body["sections"]:
        sid = s.get("id")
        if not sid or sid in section_ids:
            p.append(f"section id missing or duplicate: {sid}")
        section_ids.add(sid)
        if s.get("kind") not in ("fields", "table"):
            p.append(f"section {sid}: kind must be fields or table")
            continue
        members = s.get("fields" if s["kind"] == "fields" else "columns", [])
        ids = [m.get("id") for m in members]
        if len(set(ids)) != len(ids):
            p.append(f"section {sid}: duplicate field ids")
        for m in members:
            where = f"section {sid}.{m.get('id')}"
            if m.get("type") not in FIELD_TYPES:
                p.append(f"{where}: unknown type {m.get('type')}")
                continue
            if m["type"] in ("choice", "multichoice") and not m.get("options"):
                p.append(f"{where}: choice needs options")
            if m["type"] == "computed":
                _check_expr(m.get("expr", ""), ids, p, where)
            if "prefill" in m and m["prefill"] not in PREFILL_ROOTS:
                p.append(f"{where}: unknown prefill {m['prefill']}")
        for f in s.get("footer", []) or []:
            if s["kind"] != "table":
                p.append(f"section {sid}: footer only on tables")
            _check_expr(f.get("expr", ""), ids, p, f"section {sid} footer {f.get('label')}")
    for path in body.get("required_for_submit", []):
        sec = path.split(".")[0]
        if sec not in section_ids:
            p.append(f"required_for_submit: unknown section in {path}")
    return p


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v is False


def missing_for_submit(body: dict, data: dict) -> list[str]:
    missing: list[str] = []
    sections = {s["id"]: s for s in body["sections"]}
    for path in body.get("required_for_submit", []):
        sid, _, fid = path.partition(".")
        s = sections[sid]
        if s["kind"] == "table":
            if len(data.get(sid) or []) < max(1, int(s.get("min_rows", 1) or 1)):
                missing.append(path)
        else:
            if _empty((data.get(sid) or {}).get(fid)):
                missing.append(path)
    for s in body["sections"]:
        if s["kind"] == "fields":
            for f in s["fields"]:
                if f.get("required") and _empty((data.get(s["id"]) or {}).get(f["id"])):
                    path = f"{s['id']}.{f['id']}"
                    if path not in missing:
                        missing.append(path)
    return missing


def _cell_problems(member: dict, value, where: str, p: list[str]) -> None:
    if value is None:
        return
    t = member.get("type")
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            p.append(f"{where}: expected a number")
    elif t == "checkbox":
        if not isinstance(value, bool):
            p.append(f"{where}: expected true or false")
    elif t == "multichoice":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            p.append(f"{where}: expected a list of strings")


def validate_data(body: dict, data) -> list[str]:
    """Shape-check submitted instance data against its definition.

    Returns human-readable problems; an empty list means the payload is safe to
    recompute. Unknown section keys and `<section>_footer` keys are ignored
    (footers are recomputed), as are unknown keys inside a known section.
    """
    p: list[str] = []
    if not isinstance(data, dict):
        return ["data must be an object"]
    sections = {s["id"]: s for s in body.get("sections", []) if s.get("id")}
    for key, value in data.items():
        if key.endswith("_footer"):
            continue
        section = sections.get(key)
        if section is None:
            continue
        if section.get("kind") == "table":
            if not isinstance(value, list):
                p.append(f"section {key}: expected a list of rows")
                continue
            columns = {c["id"]: c for c in section.get("columns", []) if c.get("id")}
            for n, row in enumerate(value):
                if not isinstance(row, dict):
                    p.append(f"section {key} row {n + 1}: expected an object")
                    continue
                for cid, cell in row.items():
                    col = columns.get(cid)
                    if col:
                        _cell_problems(col, cell, f"section {key} row {n + 1}.{cid}", p)
        else:
            if value is None:
                continue
            if not isinstance(value, dict):
                p.append(f"section {key}: expected an object")
                continue
            fields = {f["id"]: f for f in section.get("fields", []) if f.get("id")}
            for fid, cell in value.items():
                field = fields.get(fid)
                if field:
                    _cell_problems(field, cell, f"section {key}.{fid}", p)
    return p
