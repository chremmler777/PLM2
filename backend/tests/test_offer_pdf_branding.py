"""The offer PDF in the KTX house design: company profile, logo, page
furniture and the timing-style plan chart."""
import shutil
import subprocess
from datetime import date, timedelta

import pytest

from app.services.company_profile import (
    DEFAULTS, company_profile, contact_line, signature_line,
)
from tests.test_offer_walk1 import _pdf_ctx


def _text(pdf: bytes) -> str:
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext not installed")
    return subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf,
                          capture_output=True, check=True).stdout.decode()


def test_profile_defaults_and_env_overrides():
    p = company_profile("KTX Toccoa", env={})
    assert p["legal_name"] == "KTX Group US Corp."
    assert p["address_lines"] == DEFAULTS["address_lines"]
    assert signature_line(p) == "KTX Group US Corp. | Sales"
    p = company_profile("Org", env={
        "KTX_COMPANY_LEGAL_NAME": "KTX Other Inc.",
        "KTX_COMPANY_ADDRESS": " 1 Main St | | Town ",
        "KTX_COMPANY_FOOTER": "Line A|Line B",
        "KTX_COMPANY_PHONE": "",     # empty: the default stays
    })
    assert p["legal_name"] == "KTX Other Inc."
    assert p["address_lines"] == ["1 Main St", "Town"]
    assert p["footer_lines"] == ["Line A", "Line B"]
    assert p["phone"] == DEFAULTS["phone"]


def test_profile_empty_fields_fall_back_or_drop_out():
    empty = {k: [] if isinstance(v, list) else "" for k, v in DEFAULTS.items()}
    p = company_profile("Org from DB", env={}, defaults=empty)
    assert p["legal_name"] == "Org from DB"
    assert contact_line(p) == ""
    assert signature_line(p) == "Org from DB"
    p["phone"], p["website"] = "+1 2", "ktx.group"
    assert contact_line(p) == "Phone +1 2  |  ktx.group"


async def test_pdf_carries_logo_company_and_page_numbers():
    from app.services.offer_pdf import render_offer_pdf
    pdf = render_offer_pdf(_pdf_ctx({"cost_lines": [{"key": "a", "label": "Tooling",
                                                     "amount": 10}],
                                     "timing": {"include": False}}))
    assert b"/Subtype /Image" in pdf                       # the KTX logo
    text = _text(pdf)
    assert "OFFER" in text and "C-W-1-Q2" in text
    assert "KTX Group US Corp." in text and "325 Hammerstone Drive" in text
    assert "IATF 16949:2016 certified site" in text
    assert "KTX Group US Corp. | Sales" in text
    assert "Page 1 of" in text
    assert "\u2014" not in text


async def test_pdf_omits_empty_profile_fields():
    from app.services.offer_pdf import render_offer_pdf
    ctx = _pdf_ctx({"timing": {"include": False}})
    ctx["company"] = {"legal_name": "Only Name LLC", "address_lines": [],
                      "phone": "", "fax": "", "email": "", "website": "",
                      "footer_lines": [], "signature_name": "",
                      "signature_title": ""}
    text = _text(render_offer_pdf(ctx))
    assert "Only Name LLC" in text
    for word in ("Phone", "Fax", "Hammerstone", "TBC", "IATF"):
        assert word not in text


async def test_pdf_status_label_in_the_bar():
    from app.services.offer_pdf import render_offer_pdf
    for status, label in (("draft", "DRAFT"), ("declined", "DECLINED")):
        text = _text(render_offer_pdf(_pdf_ctx({"timing": {"include": False}},
                                               status=status)))
        assert label in text
    text = _text(render_offer_pdf(_pdf_ctx({"timing": {"include": False}})))
    assert "DRAFT" not in text and "SUPERSEDED" not in text


def test_chart_rows_group_milestones_then_lanes():
    from app.services.offer_pdf import MILESTONE_GROUP, _chart_rows
    s = date(2026, 10, 5)
    tasks = [{"name": "a", "lane": "Tool", "start": s, "end": s + timedelta(days=2),
              "duration": 2},
             {"name": "m", "lane": "Tool", "kind": "milestone", "start": s, "end": s,
              "duration": 0},
             {"name": "b", "lane": "QA", "start": s, "end": s + timedelta(days=1),
              "duration": 1},
             {"name": "c", "lane": "Tool", "start": s, "end": s + timedelta(days=1),
              "duration": 1}]
    rows = [(k, v if k == "group" else v["name"]) for k, v in _chart_rows(tasks)]
    assert rows == [("group", MILESTONE_GROUP), ("task", "m"), ("group", "Tool"),
                    ("task", "a"), ("task", "c"), ("group", "QA"), ("task", "b")]
    # a plan without milestones and lanes gets no group rows
    plain = [dict(t, lane="") for t in tasks if t["name"] != "m"]
    assert all(k == "task" for k, _ in _chart_rows(plain))


def test_axis_picks_days_weeks_or_months():
    from reportlab.lib.units import mm

    from app.services.offer_pdf import _axis
    s = date(2026, 10, 5)
    _, _, top, bottom, shaded = _axis(s, s + timedelta(days=30), 90 * mm)
    assert len(bottom) == 30 and shaded and top[0][2].startswith("CW")
    a0, a1, _, bottom, shaded = _axis(s, s + timedelta(days=120), 90 * mm)
    assert a0.weekday() == 0 and not shaded and len(bottom) == (a1 - a0).days // 7
    _, _, top, bottom, _ = _axis(s, s + timedelta(days=900), 90 * mm)
    assert top[0][2] == "2026" and len(bottom) >= 29
