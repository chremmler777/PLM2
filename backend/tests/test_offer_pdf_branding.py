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
from tests.test_offers import (  # noqa: F401  (offer_world is a fixture)
    _auth, _create, _sent_v1, _url, offer_world,
)


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


def test_issued_by_says_each_place_once():
    from app.services.offer_pdf import issued_by
    assert issued_by("KTX Toccoa", "Plant Toccoa", "Toccoa, GA") == "KTX Toccoa, GA"
    assert issued_by("Org", "Plant Wolfsburg", "Wolfsburg") == "Org, Plant Wolfsburg"
    assert issued_by("", "Plant 2", "Wolfsburg") == "Plant 2, Wolfsburg"
    assert issued_by("KTX", "", "") == "KTX"
    assert issued_by(None, None, None) == ""


async def test_usd_offer_prints_us_dates_and_numbers():
    from app.services.offer_pdf import _chart_date, _d, render_offer_pdf
    assert _d(date(2026, 9, 25), "en") == "09/25/2026"
    assert _d("2026-09-25") == "25.09.2026"
    assert _chart_date(date(2026, 9, 25), "en") == "09/25/26"
    ctx = _pdf_ctx({"cost_lines": [{"key": "a", "label": "Tooling", "amount": 1234.5}],
                    "timing": {"include": True, "weeks_from_order": 1500,
                               "milestones": [{"label": "M", "date": "2026-12-04"}]}},
                   currency="USD")
    s = date(2026, 10, 5)
    ctx["tasks"] = [{"name": "Work", "lane": "", "kind": "work", "start": s,
                     "end": s + timedelta(days=3), "duration": 3}]
    ctx["offer"]["sent_at"] = date(2026, 9, 25)
    ctx["offer"]["valid_until"] = date(2026, 10, 25)
    text = _text(render_offer_pdf(ctx))
    assert "09/25/2026" in text and "10/25/2026" in text and "12/04/2026" in text
    assert "10/05/26" in text and "1,500 weeks" in text and "1,234.50 USD" in text
    assert "25.09.2026" not in text


async def test_sent_offer_keeps_its_letterhead(client, offer_world, monkeypatch):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    v1 = await _sent_v1(client, sales, cid)
    monkeypatch.setenv("KTX_COMPANY_LEGAL_NAME", "Renamed Corp")
    monkeypatch.setenv("KTX_COMPANY_ADDRESS", "1 New Street|Elsewhere")
    sent = _text((await client.get(_url(cid, f"/{v1['id']}/pdf"), headers=sales)).content)
    assert "KTX Group US Corp." in sent and "325 Hammerstone Drive" in sent
    assert "Renamed Corp" not in sent
    v2 = await _create(client, sales, cid)
    draft = _text((await client.get(_url(cid, f"/{v2['id']}/pdf"), headers=sales)).content)
    assert "Renamed Corp" in draft and "1 New Street" in draft
    assert "Hammerstone" not in draft


# --- Sales signs the offer (decision 2026-09-25) -----------------------------

def test_offer_signer_is_the_person_with_env_as_override_only():
    from app.services.company_profile import offer_signer
    assert offer_signer("Jane Sales", env={}) == {"name": "Jane Sales", "title": "Sales"}
    assert offer_signer("Jane", "Key Account Manager", env={})["title"] == "Key Account Manager"
    assert offer_signer(None, env={}) == {"name": "", "title": "Sales"}
    assert offer_signer("Jane", env={"KTX_COMPANY_SIGNATURE_NAME": "Fixed Name",
                                      "KTX_COMPANY_SIGNATURE_TITLE": "Head of Sales"}) == \
        {"name": "Fixed Name", "title": "Head of Sales"}
    assert offer_signer("Jane", env={"KTX_COMPANY_SIGNATURE_NAME": " "})["name"] == "Jane"


async def test_pdf_prints_the_signer_or_the_role_line_only():
    from app.services.offer_pdf import render_offer_pdf
    ctx = _pdf_ctx({"timing": {"include": False}})
    ctx["signer"] = {"name": "Jane Sales", "title": "Sales"}
    text = _text(render_offer_pdf(ctx))
    assert "Jane Sales" in text and "KTX Group US Corp. | Sales" in text
    ctx["signer"] = {"name": "", "title": "Sales"}
    text = _text(render_offer_pdf(ctx))
    assert "Jane" not in text and "KTX Group US Corp. | Sales" in text


async def _pdf(client, auth, cid, oid):
    res = await client.get(_url(cid, f"/{oid}/pdf"), headers=auth)
    assert res.status_code == 200, res.text
    return _text(res.content)


async def test_sent_offer_is_signed_by_its_sender_for_good(
        client, offer_world, session_factory, monkeypatch):
    from app.models.change_offer import ChangeOffer
    monkeypatch.delenv("KTX_COMPANY_SIGNATURE_NAME", raising=False)
    monkeypatch.delenv("KTX_COMPANY_SIGNATURE_TITLE", raising=False)
    cid = offer_world["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    v1 = await _sent_v1(client, sales, cid)
    async with session_factory() as s:
        snap = (await s.get(ChangeOffer, v1["id"])).data["_snapshot"]
    assert snap["signer"] == {"name": "Offer sales", "title": "Sales"}
    text = await _pdf(client, pm, cid, v1["id"])
    assert "Offer sales" in text and "KTX Group US Corp. | Sales" in text
    # a later override never rewrites what went out
    monkeypatch.setenv("KTX_COMPANY_SIGNATURE_NAME", "Somebody Else")
    text = await _pdf(client, pm, cid, v1["id"])
    assert "Offer sales" in text and "Somebody Else" not in text


async def _add_sales_responsible(session_factory, seed, offer_world):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import ProjectResponsible, UserDepartment
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="off-sales2",
                 email="off-sales2@test.io", full_name="Resp Sales", role="engineer",
                 hashed_password=get_password_hash("role-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=offer_world["depts"]["Sales"]))
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=offer_world["depts"]["Sales"], user_id=u.id))
        await s.commit()


async def _make_lead(session_factory, cid, user_id):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).lead_id = user_id
        await s.commit()


async def _send_as(client, auth, cid, oid):
    await client.patch(_url(cid, f"/{oid}"),
                       json={"data": {"timing": {"include": False}}}, headers=auth)
    res = await client.post(_url(cid, f"/{oid}/send"), json={}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _frozen_signer(session_factory, oid):
    from app.models.change_offer import ChangeOffer
    async with session_factory() as s:
        return (await s.get(ChangeOffer, oid)).data["_snapshot"]["signer"]


def _no_signature_env(monkeypatch):
    monkeypatch.delenv("KTX_COMPANY_SIGNATURE_NAME", raising=False)
    monkeypatch.delenv("KTX_COMPANY_SIGNATURE_TITLE", raising=False)


async def test_pm_lead_sends_the_project_sales_responsible_signs(
        client, offer_world, session_factory, seed, monkeypatch):
    _no_signature_env(monkeypatch)
    cid = offer_world["change_id"]
    await _add_sales_responsible(session_factory, seed, offer_world)
    await _make_lead(session_factory, cid, offer_world["users"]["pm"])
    pm = await _auth(client, "pm")
    draft = await _create(client, pm, cid)
    # the preview shows what sending would freeze, labelled as a preview
    text = await _pdf(client, pm, cid, draft["id"])
    assert "Signed by (preview)" in text and "Resp Sales" in text
    assert "Offer pm" not in text
    await _send_as(client, pm, cid, draft["id"])
    assert await _frozen_signer(session_factory, draft["id"]) == \
        {"name": "Resp Sales", "title": "Sales"}
    text = await _pdf(client, pm, cid, draft["id"])
    assert "Resp Sales" in text and "Offer pm" not in text
    assert "Signed by (preview)" not in text


async def test_admin_sends_without_sales_responsible_role_line_only(
        client, offer_world, session_factory, monkeypatch):
    from tests.conftest import ADMIN_PASSWORD, login
    _no_signature_env(monkeypatch)
    cid = offer_world["change_id"]
    admin = await login(client, "admin@test.io", ADMIN_PASSWORD)
    draft = await _create(client, admin, cid)
    text = await _pdf(client, admin, cid, draft["id"])
    assert "Signed by (preview)" in text and "KTX Group US Corp. | Sales" in text
    await _send_as(client, admin, cid, draft["id"])
    assert await _frozen_signer(session_factory, draft["id"]) == \
        {"name": "", "title": "Sales"}


async def test_sales_member_sends_and_signs_even_with_a_sales_responsible(
        client, offer_world, session_factory, seed, monkeypatch):
    _no_signature_env(monkeypatch)
    cid = offer_world["change_id"]
    await _add_sales_responsible(session_factory, seed, offer_world)
    sales = await _auth(client, "sales")
    draft = await _create(client, sales, cid)
    text = await _pdf(client, sales, cid, draft["id"])
    assert "Signed by (preview)" in text
    assert "Offer sales" in text and "Resp Sales" not in text
    await _send_as(client, sales, cid, draft["id"])
    assert await _frozen_signer(session_factory, draft["id"]) == \
        {"name": "Offer sales", "title": "Sales"}


async def test_draft_preview_follows_the_viewer(
        client, offer_world, session_factory, seed, monkeypatch):
    _no_signature_env(monkeypatch)
    cid = offer_world["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    draft = await _create(client, sales, cid)
    # nobody responsible: the Sales viewer would sign; a non-Sales viewer
    # sees the role line only
    assert "Offer sales" in await _pdf(client, sales, cid, draft["id"])
    text = await _pdf(client, pm, cid, draft["id"])
    assert "Offer sales" not in text and "Offer pm" not in text
    assert "KTX Group US Corp. | Sales" in text
    # with a Sales responsible: a non-Sales viewer sees them, the Sales
    # viewer still sees themselves (they would sign on send)
    await _add_sales_responsible(session_factory, seed, offer_world)
    text = await _pdf(client, pm, cid, draft["id"])
    assert "Resp Sales" in text and "Offer sales" not in text
    text = await _pdf(client, sales, cid, draft["id"])
    assert "Offer sales" in text and "Resp Sales" not in text
    # the fixed-name override still wins when a site sets it
    monkeypatch.setenv("KTX_COMPANY_SIGNATURE_NAME", "Fixed Signer")
    assert "Fixed Signer" in await _pdf(client, pm, cid, draft["id"])
