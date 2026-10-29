"""Audit 2026-10-29 (P2-4): on the Article check workflow Development designs
(R) and is not also A on the same step: one task per job. The Tool template
keeps Development A (the Tool Engineer designs there)."""
from app.services.wf_seed_service import ECN_UMSETZUNG_ARTIKEL, ECN_UMSETZUNG_WERKZEUG


def _design(template):
    stage = next(s for s in template["stages"] if s[0] == "Design")
    return {step: rasic for step, rasic, _ in stage[1]}


def test_article_design_steps_have_one_development_row():
    for step, rasic in _design(ECN_UMSETZUNG_ARTIKEL).items():
        dev = [letter for dept, letter in rasic if dept == "Development"]
        assert dev == ["R"], (step, rasic)


def test_tool_design_steps_keep_development_accountable():
    for step, rasic in _design(ECN_UMSETZUNG_WERKZEUG).items():
        assert ("Tool Engineer", "R") in rasic and ("Development", "A") in rasic, step
