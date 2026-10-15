"""One name per rule (R37): the backend's RULE_LABELS (changelog, My
actions, notifications, refusals) say exactly what the UI's rule.<key> says
in English (frontend/src/i18n/cmLabels.ts)."""
import re
from pathlib import Path

import pytest

from app.services.cm_rules import RULE_LABELS

LABELS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "cmLabels.ts"


def _ui_rule_labels() -> dict[str, str]:
    out = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*'rule\.([a-z_]+)':\s*\{.*\ben:\s*(['\"])(.*)\2\s*\},?\s*$", line)
        if m:
            out[m.group(1)] = m.group(3)
    return out


def test_backend_and_ui_name_every_rule_the_same():
    if not LABELS.exists():  # a backend-only checkout (container image)
        pytest.skip("frontend sources not present")
    ui = _ui_rule_labels()
    assert ui, "no rule.<key> labels found in cmLabels.ts"
    assert set(RULE_LABELS) == set(ui)
    assert {k: v for k, v in RULE_LABELS.items() if ui[k] != v} == {}
