import json
from pathlib import Path

import pytest

from app.forms.expr import evaluate, ExprError

VECTORS = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "forms" / "expr_vectors.json").read_text())


@pytest.mark.parametrize("vec", VECTORS, ids=[v["expr"] for v in VECTORS])
def test_vector(vec):
    if vec.get("error"):
        with pytest.raises(ExprError):
            evaluate(vec["expr"], vec["scope"])
    else:
        got = evaluate(vec["expr"], vec["scope"])
        if isinstance(vec["expected"], float):
            assert got == pytest.approx(vec["expected"])
        else:
            assert got == vec["expected"]


def test_today_is_iso_date():
    assert len(evaluate("today()", {})) == 10
