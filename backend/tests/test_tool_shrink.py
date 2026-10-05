"""Tool shrinkage decision record: candidates from MaterialDB with their source, decide with a
reason (tool fields follow), verify after the trial, report back to MaterialDB."""
import copy

import httpx
import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.services import materialdb_client


@pytest.fixture(autouse=True)
def _tool_engineer_member(tool_engineer):
    """Tool data is Tool Engineer or admin only (tool_rights); the seeded engineer works as Tool Engineer."""

pytestmark = pytest.mark.asyncio

HOSTACOM = {
    "id": 19, "ktx_number": "40-0223", "trade_name": "Hostacom", "grade": "TRC 352N", "family": "PP",
    "filler_type": "TD", "notes": "KTX tooling: 3127/3128 laid out 0.75 / 1.05",
    "documents": [
        {"id": 5, "kind": "tds", "title": "Hostacom TRC 352N datasheet", "source": "SharePoint", "doc_date": "2023-01-01",
         "origin": "sharepoint", "filename": "tds.pdf"},
        {"id": 6, "kind": "other", "title": "LyondellBasell: processing shrinkage", "source": "Mail K. Reinert 2026-10-02",
         "doc_date": "2026-10-02", "origin": "upload", "filename": "mail.msg"},
    ],
    "properties": [
        {"key": "shrinkage_flow", "value": 0.8, "value_max": None, "test_method": "LyondellBasell internal method",
         "condition": "plaque 2.5 mm", "source_document_id": 6},
        {"key": "shrinkage_cross", "value": 1.1, "value_max": None, "test_method": "LyondellBasell internal method",
         "condition": "plaque 2.5 mm", "source_document_id": 6},
        {"key": "density", "value": 1.0, "source_document_id": 5},
    ],
    "shrink_experiences": [
        {"id": 3, "tool_number": "3127", "project": "1416", "article": "VW316 trim", "planned_flow": 0.9,
         "planned_cross": 0.9, "planned_source": "M. Rautzenberg", "measured_flow": None, "measured_cross": None,
         "measured_ref": None, "verdict": None, "recommendation": "Use along/cross", "updated_at": "2026-10-02T10:00:00"},
    ],
}


@pytest_asyncio.fixture
async def mdb(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "materialdb_base_url", "http://materialdb.test/")
    monkeypatch.setattr(settings, "materialdb_service_token", "svc-token")
    state = {"detail": copy.deepcopy(HOSTACOM), "fail": None, "puts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"] == "down":
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if request.method == "GET" and path == "/v1/materials/by-id/19":
            return httpx.Response(200, json=state["detail"])
        if request.method == "PUT" and path.startswith("/v1/shrink-experiences/plm/"):
            import json
            state["puts"].append((path, json.loads(request.content)))
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404, json={"detail": "nope"})

    monkeypatch.setattr(materialdb_client, "TRANSPORT", httpx.MockTransport(handler))
    materialdb_client.clear_cache()
    yield state
    materialdb_client.clear_cache()


async def _part(client, auth, seed, number, category):
    r = await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": number, "name": number,
                                                 "part_type": "internal_mfg", "item_category": category}, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _tool_with_article(session_factory, client, auth, seed):
    from app.models.part import Part
    tool = await _part(client, auth, seed, "3501", "tool")
    art = await _part(client, auth, seed, "5A65DF8", "article")
    async with session_factory() as s:
        a = await s.get(Part, art)
        a.material_source, a.materialdb_id, a.material_label = "materialdb", 19, "40-0223 Hostacom TRC 352N"
        await s.commit()
    r = await client.post(f"/api/v1/parts/{tool}/relations", json={"to_part_id": art, "relation_type": "produces"},
                          headers=auth)
    assert r.status_code == 201, r.text
    return tool


DECISION = {"parallel_pct": 0.8, "normal_pct": 1.1, "source_kind": "supplier",
            "source_label": "LyondellBasell: processing shrinkage (Mail K. Reinert 2026-10-02)",
            "rationale": "Supplier measured along/cross; KTX 3127 combined 0.9 is history only",
            "materialdb_id": 19, "material_label": "40-0223 Hostacom TRC 352N"}


async def test_candidates_carry_their_source(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    r = await client.get(f"/api/v1/parts/{tool}/shrinkage", headers=eng_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None and body["decisions"] == []
    kinds = [(c["kind"], c["parallel_pct"], c["normal_pct"]) for c in body["candidates"]]
    assert kinds == [("supplier", 0.8, 1.1), ("ktx_experience", 0.9, 0.9)]
    sup = body["candidates"][0]
    assert sup["source_label"] == "LyondellBasell: processing shrinkage (Mail K. Reinert 2026-10-02)"
    assert (sup["method"], sup["condition"]) == ("LyondellBasell internal method", "plaque 2.5 mm")
    assert body["materials"][0]["articles"] == ["5A65DF8"]


async def test_materialdb_down_still_allows_own_value(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    mdb["fail"] = "down"
    body = (await client.get(f"/api/v1/parts/{tool}/shrinkage", headers=eng_auth)).json()
    assert body["candidates"] == [] and "unreachable" in body["error"]
    r = await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", headers=eng_auth,
                          json={"parallel_pct": 0.9, "normal_pct": 0.9, "source_kind": "own", "rationale": "Toolmaker standard"})
    assert r.status_code == 200, r.text


async def test_decide_sets_tool_fields_and_supersedes(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    r = await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", json=DECISION, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["tool"] == {"parallel_pct": 0.8, "normal_pct": 1.1, "combined_pct": None}
    part = (await client.get(f"/api/v1/parts/{tool}", headers=eng_auth)).json()
    assert (part["tool_shrink_parallel_pct"], part["tool_shrink_normal_pct"]) == (0.8, 1.1)

    second = {**DECISION, "parallel_pct": 0.85, "source_kind": "own", "source_label": None, "rationale": "Toolmaker asked"}
    body = (await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", json=second, headers=eng_auth)).json()
    assert [(d["status"], d["parallel_pct"]) for d in body["decisions"]] == [("current", 0.85), ("superseded", 0.8)]
    assert body["decisions"][1]["source_label"].startswith("LyondellBasell")
    assert body["decisions"][0]["decided_by"]

    log = (await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)).json()
    actions = [e["action"] for e in log]
    assert actions.count("shrink_decided") == 2
    assert any(e["action"] == "field_updated" and e["field_name"] == "tool_shrink_parallel_pct" for e in log)


async def test_decide_needs_reason_and_source(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    url = f"/api/v1/parts/{tool}/shrinkage/decisions"
    assert (await client.post(url, json={**DECISION, "rationale": "  "}, headers=eng_auth)).status_code == 400
    assert (await client.post(url, json={**DECISION, "source_label": None}, headers=eng_auth)).status_code == 400
    assert (await client.post(url, json={**DECISION, "parallel_pct": 7}, headers=eng_auth)).status_code == 422
    art = await _part(client, eng_auth, seed, "X-1", "article")
    assert (await client.get(f"/api/v1/parts/{art}/shrinkage", headers=eng_auth)).status_code == 400


async def test_decision_reports_to_materialdb_right_away(client, eng_auth, seed, session_factory, mdb):
    """MaterialDB shows the decided value as tool experience at once, not verified yet; one entry per tool."""
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    d = (await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", json=DECISION,
                           headers=eng_auth)).json()["decisions"][0]
    assert d["feedback_status"] == "sent"
    path, sent = mdb["puts"][0]
    assert path == f"/v1/shrink-experiences/plm/{tool}"
    assert (sent["planned_flow"], sent["planned_cross"], sent["measured_flow"], sent["verdict"]) == (0.8, 1.1, None, None)
    assert sent["recommendation"] is None and sent["source"].endswith("decided, not verified yet")
    # a new decision updates the same MaterialDB entry
    await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", headers=eng_auth,
                      json={**DECISION, "parallel_pct": None, "normal_pct": None, "combined_pct": 0.9})
    assert [p for p, _ in mdb["puts"]] == [f"/v1/shrink-experiences/plm/{tool}"] * 2
    assert mdb["puts"][1][1]["planned_flow"] == 0.9


async def test_verify_reports_to_materialdb(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    did = (await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", json=DECISION,
                             headers=eng_auth)).json()["decisions"][0]["id"]
    url = f"/api/v1/parts/{tool}/shrinkage/decisions/{did}/verify"
    # A verdict other than "correct" needs a note for the next tool
    bad = {"measured_parallel_pct": 0.86, "measured_normal_pct": 1.15, "measured_ref": "TH1 6-pc CMM", "verdict": "offset"}
    assert (await client.post(url, json=bad, headers=eng_auth)).status_code == 400

    r = await client.post(url, json={**bad, "next_time_note": "Use 0.85 / 1.15 for 2.5 mm walls"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    d = r.json()["decisions"][0]
    assert (d["verdict"], d["feedback_status"], d["measured_normal_pct"]) == ("offset", "sent", 1.15)
    path, sent = mdb["puts"][-1]
    assert path == f"/v1/shrink-experiences/plm/{tool}"
    assert (sent["material_id"], sent["tool_number"], sent["planned_flow"], sent["measured_cross"]) == (19, "3501", 0.8, 1.15)
    assert sent["recommendation"] == "Use 0.85 / 1.15 for 2.5 mm walls"
    assert "Why: Supplier measured" in sent["planned_source"]


async def test_failed_report_is_kept_and_can_be_resent(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    did = (await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", json=DECISION,
                             headers=eng_auth)).json()["decisions"][0]["id"]
    base = f"/api/v1/parts/{tool}/shrinkage/decisions/{did}"
    mdb["fail"] = "down"
    d = (await client.post(f"{base}/verify", headers=eng_auth, json={
        "measured_parallel_pct": 0.8, "measured_normal_pct": 1.1, "measured_ref": "TH1", "verdict": "correct"})).json()["decisions"][0]
    assert d["feedback_status"] == "failed" and d["verified_at"]
    mdb["fail"] = None
    d = (await client.post(f"{base}/report", headers=eng_auth)).json()["decisions"][0]
    assert d["feedback_status"] == "sent"
    assert mdb["puts"][-1][1]["recommendation"] == "Keep 0.8 / 1.1 % parallel / normal"


async def test_combined_or_parallel_normal_never_both(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    url = f"/api/v1/parts/{tool}/shrinkage/decisions"
    base = {"source_kind": "own", "rationale": "Painted Bayblend"}
    for bad in ({}, {"combined_pct": 0.65, "parallel_pct": 0.6, "normal_pct": 0.7}, {"parallel_pct": 0.6},
                {"combined_pct": 0.65, "normal_pct": 0.7}):
        assert (await client.post(url, json={**base, **bad}, headers=eng_auth)).status_code == 400, bad

    # split first, then combined: the tool holds only the combined value afterwards
    await client.post(url, json={**DECISION}, headers=eng_auth)
    body = (await client.post(url, json={**base, "combined_pct": 0.65}, headers=eng_auth)).json()
    assert body["tool"] == {"parallel_pct": None, "normal_pct": None, "combined_pct": 0.65}
    d = body["decisions"][0]
    assert (d["combined_pct"], d["parallel_pct"], d["normal_pct"]) == (0.65, None, None)
    part = (await client.get(f"/api/v1/parts/{tool}", headers=eng_auth)).json()
    assert (part["tool_shrink_combined_pct"], part["tool_shrink_parallel_pct"]) == (0.65, None)
    log = (await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)).json()
    assert any(e["action"] == "shrink_decided" and "0.65 % combined" in e["action_description"] for e in log)


async def test_combined_decision_reports_one_value_both_directions(client, eng_auth, seed, session_factory, mdb):
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    did = (await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", headers=eng_auth, json={
        **DECISION, "parallel_pct": None, "normal_pct": None, "combined_pct": 0.9})).json()["decisions"][0]["id"]
    url = f"/api/v1/parts/{tool}/shrinkage/decisions/{did}/verify"
    both = {"measured_combined_pct": 0.95, "measured_parallel_pct": 0.9, "measured_ref": "TH1", "verdict": "correct"}
    assert (await client.post(url, json=both, headers=eng_auth)).status_code == 400
    r = await client.post(url, json={"measured_combined_pct": 0.95, "measured_ref": "TH1", "verdict": "correct"},
                          headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["decisions"][0]["measured_combined_pct"] == 0.95
    sent = mdb["puts"][-1][1]
    assert (sent["planned_flow"], sent["planned_cross"], sent["measured_flow"], sent["measured_cross"]) == (0.9, 0.9, 0.95, 0.95)
    assert sent["planned_source"].startswith("combined value; supplier")
    assert sent["recommendation"] == "Keep 0.9 % combined"


async def test_tool_data_is_view_only_outside_tool_engineer(client, eng_auth, admin_auth, seed, session_factory, mdb):
    """Tool fields, produces links and shrinkage: Tool Engineer or admin; acting as another department views only."""
    from tests.conftest import make_department_member
    from app.services.tool_rights import TOOL_EDIT_DENIED
    quality = await make_department_member(session_factory, seed["admin_id"], "Quality")
    as_quality = {**admin_auth, "X-Acts-As-Department": str(quality)}
    tool = await _tool_with_article(session_factory, client, eng_auth, seed)
    art = await _part(client, eng_auth, seed, "5A65DF9", "article")

    res = await client.put(f"/api/v1/parts/{tool}", json={"tool_cavities": 4}, headers=as_quality)
    assert res.status_code == 403 and res.json()["detail"] == TOOL_EDIT_DENIED
    res = await client.post(f"/api/v1/parts/{tool}/relations", json={"to_part_id": art, "relation_type": "produces"},
                            headers=as_quality)
    assert res.status_code == 403
    res = await client.post(f"/api/v1/parts/{tool}/shrinkage/decisions", json=DECISION, headers=as_quality)
    assert res.status_code == 403
    body = (await client.get(f"/api/v1/parts/{tool}/shrinkage", headers=as_quality)).json()
    assert body["can_edit"] is False
    assert (await client.get("/api/v1/auth/me", headers=as_quality)).json()["can_edit_tools"] is False

    # an article's own fields stay open; the admin (not acting) and the Tool Engineer edit tools
    assert (await client.put(f"/api/v1/parts/{art}", json={"name": "x"}, headers=as_quality)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=admin_auth)).json()["can_edit_tools"] is True
    assert (await client.put(f"/api/v1/parts/{tool}", json={"tool_cavities": 4}, headers=eng_auth)).status_code == 200
