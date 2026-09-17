import json
from pathlib import Path

from sqlalchemy import select

from app.forms.compute import recompute
from app.forms.validate import validate_definition, missing_for_submit
from app.forms.loader import load_definitions, DEFINITIONS_DIR, latest_definitions
from app.models.forms import FormDefinition

TEMPLATE = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "sep_template.json").read_text())

MINI = {
    "key": "mini", "version": 1, "title": "Mini", "implements": None, "cardinality": "single",
    "gate_items": False, "sep_items": ["K0/RG1:2"], "signatures": [], "required_for_submit": ["header.name", "rows"],
    "sections": [
        {"id": "header", "title": "H", "kind": "fields", "fields": [
            {"id": "name", "label": "Name", "type": "text", "prefill": "project.name"},
            {"id": "n", "label": "N", "type": "number"},
            {"id": "double", "label": "Double", "type": "computed", "expr": "n * 2"},
        ]},
        {"id": "rows", "title": "Rows", "kind": "table", "min_rows": 1, "columns": [
            {"id": "q", "label": "Q", "type": "number"},
            {"id": "p", "label": "P", "type": "number"},
            {"id": "r", "label": "R", "type": "computed", "expr": "q * p"},
            {"id": "status", "label": "Status", "type": "choice", "options": ["open", "done"]},
        ], "footer": [{"label": "Open", "expr": "count(status == 'open')"}]},
    ],
}


def test_recompute_fields_tables_footer():
    data = {"header": {"name": "x", "n": 2}, "rows": [{"q": 0.5, "p": 1, "status": "open"}, {"q": 1, "p": 1, "status": "done"}]}
    out = recompute(MINI, data)
    assert out["header"]["double"] == 4
    assert [r["r"] for r in out["rows"]] == [0.5, 1]
    assert out["rows_footer"] == {"Open": 1}


def test_validate_definition_catches_problems():
    assert validate_definition(MINI, TEMPLATE) == []
    bad = json.loads(json.dumps(MINI))
    bad["sep_items"] = ["K0/RG1:999"]
    bad["sections"][0]["fields"][0]["prefill"] = "rfq.sop"
    bad["sections"][0]["fields"][1]["type"] = "money"
    bad["sections"][0]["fields"][2]["expr"] = "nope * 2"
    problems = validate_definition(bad, TEMPLATE)
    assert any("K0/RG1:999" in p for p in problems)
    assert any("rfq.sop" in p for p in problems)
    assert any("money" in p for p in problems)
    assert any("nope" in p for p in problems)


def test_missing_for_submit():
    assert missing_for_submit(MINI, {"header": {"name": ""}, "rows": []}) == ["header.name", "rows"]
    assert missing_for_submit(MINI, {"header": {"name": "a"}, "rows": [{"q": 1}]}) == []


def test_all_shipped_definitions_valid():
    files = sorted(DEFINITIONS_DIR.glob("*.json"))
    keys = [f.stem for f in files if f.stem != "expr_vectors"]
    assert set(keys) >= {"risk_assessment", "sales_pm_handover", "project_legitimization",
                         "contact_list", "lop", "deviation_agreement"}
    for f in files:
        if f.stem == "expr_vectors":
            continue
        body = json.loads(f.read_text())
        assert body["key"] == f.stem
        assert validate_definition(body, TEMPLATE) == [], f.name
        recompute(body, {})  # empty data must not crash


async def test_loader_is_idempotent(session_factory, seed):
    async with session_factory() as s:
        n1 = await load_definitions(s)
        await s.commit()
    async with session_factory() as s:
        n2 = await load_definitions(s)
        await s.commit()
        rows = (await s.execute(select(FormDefinition))).scalars().all()
        latest = await latest_definitions(s)
    assert n1 >= 6 and n2 == 0
    assert len(rows) == n1 and len(latest) == n1
