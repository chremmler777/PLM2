"""Costing derives the machine class from the impacted article's tool
tonnage: MachineDB first, TWOS second, the tonnage typed in plm2 last; the
sync is guarded (never wipes), a hand pick wins, a priced line keeps its
class, and the line says where the class came from."""
from datetime import datetime

import httpx
import pytest
from sqlalchemy import select

from app.models.change import ChangeImpactedItem, ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.part import Part, PartRelation
from app.services import costing_rates, machinedb_client, twos_client
from app.services import tool_tonnage_service as tts
from app.services.machinedb_client import ImToolDTO
from app.services.twos_client import TwosToolDTO
from tests.test_costing_cost_sheet import _add, _url, _version, world  # noqa: F401

pytestmark = pytest.mark.asyncio


def mdb(number, *, assigned=None, machine=None, qmin=None):
    return ImToolDTO(tool_number=number, qualified_min_tonnage_t=qmin,
                     qualified_max_tonnage_t=None, assigned_machine_name=machine,
                     assigned_machine_plant="usa" if machine else None,
                     assigned_clamping_force_t=assigned)


def twos(number, press):
    return TwosToolDTO(tool_number=number, press_t=twos_client.parse_press(press),
                       press_raw=press)


async def _tool(session_factory, world, number, **fields):
    async with session_factory() as s:
        t = Part(part_number=number, name=f"Tool {number}", item_category="tool",
                 part_type="tool", project_id=world["project_id"],
                 created_by=world["admin_id"], **fields)
        s.add(t)
        await s.commit()
        return t.id


async def _article_with_tool(session_factory, world, tool_number, **tool_fields):
    """An impacted article produced by a tool (part_relations 'produces')."""
    tool_id = await _tool(session_factory, world, tool_number, **tool_fields)
    async with session_factory() as s:
        art = Part(part_number=f"A-{tool_number}", name="Article", item_category="article",
                   part_type="internal_mfg", project_id=world["project_id"],
                   created_by=world["admin_id"])
        s.add(art)
        await s.flush()
        s.add(PartRelation(from_part_id=tool_id, to_part_id=art.id,
                           relation_type="produces", created_by=world["admin_id"]))
        s.add(ChangeImpactedItem(change_id=world["change_id"], part_id=art.id,
                                 created_by=world["admin_id"]))
        await s.commit()
    return tool_id


async def _sync(session_factory, world, **kw):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        report = await tts.sync_change(s, change, **kw)
        await s.commit()
        return report


async def _machine_version(session_factory, world):
    await _version(session_factory, world["org_id"], machines=[
        dict(machine_class="200-450 t", machine_class_id=world["big"],
             hourly_rate=85, currency="USD"),
        dict(machine_class="<=200 t", machine_class_id=world["small"],
             hourly_rate=40, currency="USD")])


# ---------------------------------------------------------------- matching, parsing

async def test_number_key_matches_zero_padded_numbers():
    assert tts.number_key("0745") == tts.number_key("745") == tts.number_key(" 745 ")
    assert tts.number_key("3454") != tts.number_key("3455")
    # not all digits, or longer than TOOL_WIDTH: no folded key, exact only
    assert tts.number_key("t-12a") is None and tts.exact_key(" t-12a ") == "T-12A"
    assert tts.number_key("012345") is None and tts.number_key("12345") is None


async def test_spellings_asked_of_machinedb():
    assert tts.spellings("45") == {"45", "045", "0045"}
    assert tts.spellings("0745") == {"745", "0745"}
    assert tts.spellings("012345") == {"012345"}
    assert tts.spellings("T-12") == {"T-12"}


async def test_exact_spelling_wins_and_long_numbers_do_not_fold(session_factory, world):
    a = await _article_with_tool(session_factory, world, "0745")
    b = await _article_with_tool(session_factory, world, "745")
    c = await _article_with_tool(session_factory, world, "012345")
    d = await _article_with_tool(session_factory, world, "0669")
    report = await _sync(
        session_factory, world, mdb_rows=[],
        twos_rows=[twos("745", "650"), twos("0745", "1,300"), twos("12345", "900"),
                   # TWOS writes 669 twice, only the second row knows the press
                   twos("669", "0"), twos("669", "400")])
    assert report["twos"]["matched"] == 3
    async with session_factory() as s:
        ta, tb, tc, td = [await s.get(Part, i) for i in (a, b, c, d)]
        # "0745" and "745" are both spelled in TWOS: each takes its own row
        assert ta.tool_tonnage_twos_t == 1300 and tb.tool_tonnage_twos_t == 650
        # "012345" is not "12345": no row
        assert tc.tool_tonnage_twos_t is None
        # no exact "0669" row: the folded one, the row with a tonnage
        assert td.tool_tonnage_twos_t == 400


async def test_manual_refresh_skips_the_twos_cache(client, admin_auth, world,
                                                   session_factory, monkeypatch):
    await _article_with_tool(session_factory, world, "3454")
    seen = []

    async def fake_twos(**kw):
        seen.append(kw.get("fresh"))
        return [twos("3454", "650")]
    monkeypatch.setattr(machinedb_client, "is_configured", lambda: False)
    monkeypatch.setattr(twos_client, "is_configured", lambda: True)
    monkeypatch.setattr(twos_client, "list_tools", fake_twos)
    res = await client.post(_url(world, "/costing/tool-tonnage/refresh"), headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["can_refresh_tonnage"] is True
    res = await client.post("/api/v1/cost-sheet/machines/tool-tonnage/sync",
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    # a background refresh may use the minute cache
    await _sync(session_factory, world)
    assert seen == [True, True, False]


async def test_twos_client_fresh_bypasses_cache(monkeypatch):
    monkeypatch.setenv("TWOS_API_URL", "http://twos.test/v1")
    monkeypatch.setenv("TWOS_SERVICE_TOKEN", "t")
    twos_client._cache.clear()
    calls = []

    async def fake_get(path, transport=None):
        calls.append(path)
        return [{"tool_number": "3454", "press": str(100 * len(calls))}]
    monkeypatch.setattr(twos_client, "_get", fake_get)
    try:
        assert (await twos_client.list_tools())[0].press_t == 100
        assert (await twos_client.list_tools())[0].press_t == 100      # cached
        assert (await twos_client.list_tools(fresh=True))[0].press_t == 200
        assert (await twos_client.list_tools())[0].press_t == 200      # stored
    finally:
        twos_client._cache.clear()
    assert tts.spellings("745") == {"745", "0745"}
    assert tts.spellings("0745") == {"0745", "745"}


async def test_twos_press_unknown_and_grouped():
    assert twos_client.parse_press("1,300") == 1300
    assert twos_client.parse_press("350") == 350
    assert twos_client.parse_press("450 t") == 450
    for unknown in ("0", "", None, "n/a", "-5"):
        assert twos_client.parse_press(unknown) is None


async def test_machinedb_tonnage_assigned_press_else_smallest_qualified():
    assert mdb("1", assigned=450, machine="KM 450", qmin=350).tonnage_t == (450, "assigned")
    assert mdb("1", qmin=350).tonnage_t == (350, "qualified_min")
    assert mdb("1").tonnage_t == (None, None)


# ---------------------------------------------------------------- clients

async def test_machinedb_im_tools_client(monkeypatch):
    monkeypatch.setenv("MACHINEDB_API_URL", "http://mdb.test/v1")
    monkeypatch.setenv("MACHINEDB_SERVICE_TOKEN", "secret-token")
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json=[{
            "tool_number": "0745", "qualified_min_tonnage_t": 350,
            "qualified_max_tonnage_t": 650, "assigned_machine_id": 7,
            "assigned_machine": {"internal_name": "KM 450", "plant": "usa",
                                 "clamping_force_t": "450.00"}}, {"bad": 1}])

    rows = await machinedb_client.list_im_tools(
        ["745", "0745"], transport=httpx.MockTransport(handler))
    assert [r.tonnage_t for r in rows] == [(450.0, "assigned")]
    assert rows[0].assigned_machine_name == "KM 450"
    assert seen[0].url.path == "/v1/im-tools"
    assert seen[0].url.params["tool_number"] == "0745,745"
    assert seen[0].headers["authorization"] == "Bearer secret-token"

    # an older MachineDB without the route: unavailable, not "no tools"
    with pytest.raises(machinedb_client.MachineDBUnavailable) as e:
        await machinedb_client.list_im_tools(
            ["1"], transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert "secret-token" not in str(e.value)


async def test_twos_client(monkeypatch):
    monkeypatch.setenv("TWOS_API_URL", "http://twos.test/v1")
    monkeypatch.setenv("TWOS_SERVICE_TOKEN", "twos-token")

    def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer twos-token"
        assert request.url.path == "/v1/tools"
        return httpx.Response(200, json=[{"id": 1, "tool_number": "668", "press": "1,300"},
                                         {"id": 2, "tool_number": "669", "press": "0"}])

    rows = await twos_client.list_tools(transport=httpx.MockTransport(handler))
    assert [(r.tool_number, r.press_t) for r in rows] == [("668", 1300.0), ("669", None)]
    with pytest.raises(twos_client.TwosUnavailable) as e:
        await twos_client.list_tools(
            transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert "twos-token" not in str(e.value)


async def test_sources_unset_are_skipped(monkeypatch):
    for k in ("MACHINEDB_API_URL", "MACHINEDB_SERVICE_TOKEN", "TWOS_API_URL",
              "TWOS_SERVICE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert not tts.any_source_configured()
    report = await tts.sync_tools(None, [])   # no tools: nothing asked, no session touched
    assert report["machinedb"]["status"] == "no_tools"


# ---------------------------------------------------------------- sync

async def test_sync_machinedb_first_twos_fallback_zero_pad(session_factory, world):
    a = await _article_with_tool(session_factory, world, "0745")
    b = await _article_with_tool(session_factory, world, "3454")
    c = await _article_with_tool(session_factory, world, "0669")
    report = await _sync(
        session_factory, world,
        mdb_rows=[mdb("3454", assigned=450, machine="KM 450", qmin=350)],
        # TWOS writes numbers without the zero padding; "0" = does not know
        twos_rows=[twos("745", "1,300"), twos("3454", "650"), twos("669", "0")])
    assert report["machinedb"]["status"] == "ok" and report["machinedb"]["matched"] == 1
    assert report["twos"]["matched"] == 3 and report["twos"]["no_tonnage"] == ["0669"]
    assert report["without"] == ["0669"]
    async with session_factory() as s:
        ta, tb, tc = (await s.get(Part, a), await s.get(Part, b), await s.get(Part, c))
        assert tts.tool_tonnage(ta).source == "twos" and tts.tool_tonnage(ta).tonnage == 1300
        # both know 3454: MachineDB wins
        got = tts.tool_tonnage(tb)
        assert (got.source, got.tonnage, got.machine, got.basis) == (
            "machinedb", 450, "KM 450", "assigned")
        assert tb.tool_tonnage_twos_t == 650
        assert tts.tool_tonnage(tc) is None and tc.tool_tonnage_twos_t is None


async def test_empty_or_failed_fetch_does_not_wipe(session_factory, world, monkeypatch):
    tid = await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)],
                twos_rows=[twos("3454", "650")])
    # an empty answer from both
    report = await _sync(session_factory, world, mdb_rows=[], twos_rows=[])
    assert report["machinedb"]["matched"] == 0
    # the tool listed without a tonnage
    await _sync(session_factory, world, mdb_rows=[mdb("3454")],
                twos_rows=[twos("3454", "0")])

    # both sources down
    async def down(*a, **k):
        raise machinedb_client.MachineDBUnavailable("MachineDB is not reachable from this server")

    async def twos_down(*a, **k):
        raise twos_client.TwosUnavailable("TWOS did not answer in time")
    monkeypatch.setattr(machinedb_client, "list_im_tools", down)
    monkeypatch.setattr(machinedb_client, "is_configured", lambda: True)
    monkeypatch.setattr(twos_client, "list_tools", twos_down)
    monkeypatch.setattr(twos_client, "is_configured", lambda: True)
    report = await _sync(session_factory, world)
    assert report["machinedb"]["status"] == "failed"
    assert report["twos"]["status"] == "failed"
    assert report["twos"]["error"] == "TWOS did not answer in time"
    async with session_factory() as s:
        t = await s.get(Part, tid)
        assert (t.tool_tonnage_mdb_t, t.tool_tonnage_mdb_basis) == (350, "qualified_min")
        assert t.tool_tonnage_twos_t == 650


# ---------------------------------------------------------------- costing

async def test_line_priced_on_tool_class_with_provenance(
        client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    # no tool tonnage anywhere: no class, and the context says which tool lacks one
    await _article_with_tool(session_factory, world, "3454")
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["default_machine_class_id"] is None
    assert ctx["tool_class_origin"] == {"kind": "none", "tools": ["3454"],
                                        "without": ["3454"]}
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate_missing"] and m["machine_class_origin"]["kind"] == "none"

    await _sync(session_factory, world,
                mdb_rows=[mdb("3454", assigned=450, machine="KM 450")], twos_rows=[])
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["default_machine_class_id"] == world["big"] and ctx["tonnage"] == 450
    origin = ctx["tool_class_origin"]
    assert (origin["kind"], origin["tool_number"], origin["source"], origin["tonnage"]) == (
        "tool", "3454", "machinedb", 450)
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate"] == 85 and m["machine_class_used_id"] == world["big"]
    assert m["machine_class_origin"]["source"] == "machinedb"
    assert m["machine_class_origin"]["machine"] == "KM 450"


async def test_largest_tool_wins_over_articles(client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "0100", tool_tonnage_twos_t=150)
    await _article_with_tool(session_factory, world, "0200", tool_tonnage_mdb_t=400,
                             tool_tonnage_mdb_basis="qualified_min")
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["tonnage"] == 400 and ctx["tool_class_origin"]["tool_number"] == "0200"


async def test_hand_pick_wins(client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454", tool_tonnage_mdb_t=450,
                             tool_tonnage_mdb_basis="assigned")
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["small"]}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["effective_machine_class_id"] == world["small"]
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=1)
    assert m["rate"] == 40 and m["machine_class_origin"] == {"kind": "change"}
    own = await _add(client, admin_auth, world, kind="machine_time", label="Own", hours=1,
                     machine_class_id=world["big"])
    assert own["rate"] == 85 and own["machine_class_origin"] == {"kind": "line"}


async def test_priced_line_keeps_its_class_when_tonnage_changes(
        client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate"] == 85
    # MachineDB now says the tool runs on a 180 t press
    await _sync(session_factory, world,
                mdb_rows=[mdb("3454", assigned=180, machine="KM 180")], twos_rows=[])
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["default_machine_class_id"] == world["small"]
    # the priced line stays on 200-450 t, also when its hours are edited
    res = await client.put(_url(world, f"/costing/positions/{m['id']}"),
                           json={"hours": 3}, headers=admin_auth)
    assert res.status_code == 200, res.text
    line = res.json()
    assert line["rate"] == 85 and line["machine_class_used_id"] == world["big"]
    assert line["machine_class_origin"]["tonnage"] == 350
    async with session_factory() as s:
        p = await s.get(CostingPosition, m["id"])
        assert p.rate_detail["machine_class_id"] == world["big"]
    # a new line takes the new class
    n = await _add(client, admin_auth, world, kind="machine_time", label="New", hours=1)
    assert n["rate"] == 40 and n["machine_class_origin"]["machine"] == "KM 180"


async def test_impacted_tool_itself_and_plm2_fallback(session_factory, world):
    tid = await _tool(session_factory, world, "0777", tool_tonnage_class=650)
    async with session_factory() as s:
        s.add(ChangeImpactedItem(change_id=world["change_id"], part_id=tid,
                                 created_by=world["admin_id"]))
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        ct = await tts.change_tonnage(s, change)
        assert (ct.best.tool_number, ct.best.source, ct.tonnage) == ("0777", "plm2", 650)


async def test_refresh_endpoint(client, admin_auth, world, session_factory, monkeypatch):
    await _article_with_tool(session_factory, world, "3454")

    async def fake_mdb(numbers, **kw):
        assert "3454" in numbers
        return [mdb("3454", assigned=450, machine="KM 450")]
    monkeypatch.setattr(machinedb_client, "is_configured", lambda: True)
    monkeypatch.setattr(machinedb_client, "list_im_tools", fake_mdb)
    monkeypatch.setattr(twos_client, "is_configured", lambda: False)
    res = await client.post(_url(world, "/costing/tool-tonnage/refresh"), headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tool_tonnage_refresh"]["machinedb"]["updated"] == 1
    assert body["tool_tonnage_refresh"]["twos"]["status"] == "not_configured"
    assert body["tonnage"] == 450

    res = await client.post("/api/v1/cost-sheet/machines/tool-tonnage/sync",
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["tools"] >= 1 and res.json()["machinedb"]["updated"] == 0


async def test_hand_pick_equal_to_new_tool_default_moves_a_frozen_line(
        client, admin_auth, world, session_factory):
    """Priced on 200-450 t (tool at 350 t); the tool moves to 180 t, so the
    tonnage default is now <=200 t; picking <=200 t by hand must re-price the
    line although the effective class of the change did not change."""
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate"] == 85
    await _sync(session_factory, world,
                mdb_rows=[mdb("3454", assigned=180, machine="KM 180")], twos_rows=[])
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["small"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    lines = (await client.get(_url(world, "/costing/positions"), headers=admin_auth)).json()
    line = next(p for p in lines if p["id"] == m["id"])
    assert line["rate"] == 40 and line["machine_class_used_id"] == world["small"]
    assert line["machine_class_origin"] == {"kind": "change"}
    # back to the default: the line follows today's tool class
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": None}, headers=admin_auth)
    assert res.status_code == 200, res.text
    lines = (await client.get(_url(world, "/costing/positions"), headers=admin_auth)).json()
    line = next(p for p in lines if p["id"] == m["id"])
    assert line["rate"] == 40 and line["machine_class_origin"]["machine"] == "KM 180"


async def test_line_priced_before_108_keeps_its_class_on_an_hours_edit(
        client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate"] == 85
    # as a line priced before 108 stored it: the class, no origin
    async with session_factory() as s:
        p = await s.get(CostingPosition, m["id"])
        detail = dict(p.rate_detail)
        detail.pop("machine_class_origin")
        p.rate_detail = detail
        await s.commit()
    await _sync(session_factory, world,
                mdb_rows=[mdb("3454", assigned=180, machine="KM 180")], twos_rows=[])
    res = await client.put(_url(world, f"/costing/positions/{m['id']}"),
                           json={"hours": 3}, headers=admin_auth)
    assert res.status_code == 200, res.text
    line = res.json()
    assert line["rate"] == 85 and line["machine_class_used_id"] == world["big"]
    assert line["machine_class_origin"] is None
    # and stays frozen on the next edit
    res = await client.put(_url(world, f"/costing/positions/{m['id']}"),
                           json={"hours": 4}, headers=admin_auth)
    assert res.json()["rate"] == 85


async def _legacy(session_factory, line_id, **fields):
    """Reshape a priced line as one priced before 108 stored it: the class
    in its snapshot, no origin."""
    async with session_factory() as s:
        p = await s.get(CostingPosition, line_id)
        detail = dict(p.rate_detail)
        detail.pop("machine_class_origin", None)
        for k, v in fields.pop("detail", {}).items():
            detail[k] = v
        p.rate_detail = detail
        for k, v in fields.items():
            setattr(p, k, v)
        await s.commit()


async def _press(session_factory, world, tonnage=150):
    from app.models.cost_sheet_machines import CostSheetMachine
    async with session_factory() as s:
        m = CostSheetMachine(organization_id=world["org_id"], machinedb_id=4711,
                             internal_name="KM 150", clamping_force_t=tonnage)
        s.add(m)
        await s.commit()
        return m.id


async def _line(client, admin_auth, world, line_id):
    lines = (await client.get(_url(world, "/costing/positions"), headers=admin_auth)).json()
    return next(p for p in lines if p["id"] == line_id)


async def test_clearing_own_class_of_a_line_priced_before_108_moves_it(
        client, admin_auth, world, session_factory):
    """Own class <=200 t, priced before 108; the user clears the class: the
    line goes to the tool default (200-450 t), not frozen on the class just
    removed."""
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    m = await _add(client, admin_auth, world, kind="machine_time", label="Own", hours=2,
                   machine_class_id=world["small"])
    assert m["rate"] == 40
    await _legacy(session_factory, m["id"])
    res = await client.put(_url(world, f"/costing/positions/{m['id']}"),
                           json={"machine_class_id": None}, headers=admin_auth)
    assert res.status_code == 200, res.text
    line = res.json()
    assert line["rate"] == 85 and line["machine_class_used_id"] == world["big"]
    assert line["machine_class_origin"]["kind"] == "tool"


async def test_clearing_named_machine_of_a_line_priced_before_108_moves_it(
        client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    press = await _press(session_factory, world)
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate"] == 85
    # priced before 108 on its 150 t press: <=200 t, the press in the snapshot
    await _legacy(session_factory, m["id"], machine_id=press, rate=40,
                  detail={"machine_class_id": world["small"], "machine_id": press})
    res = await client.put(_url(world, f"/costing/positions/{m['id']}"),
                           json={"machine_id": None}, headers=admin_auth)
    assert res.status_code == 200, res.text
    line = res.json()
    assert line["rate"] == 85 and line["machine_class_used_id"] == world["big"]
    assert line["machine_class_origin"]["kind"] == "tool"


async def test_clearing_the_hand_pick_moves_a_line_priced_before_108(
        client, admin_auth, world, session_factory):
    """A line priced before 108 on the hand pick <=200 t; the pick is
    cleared: the line moves to the live tool default 200-450 t."""
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["small"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["rate"] == 40
    await _legacy(session_factory, m["id"])
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": None}, headers=admin_auth)
    assert res.status_code == 200, res.text
    line = await _line(client, admin_auth, world, m["id"])
    assert line["rate"] == 85 and line["machine_class_used_id"] == world["big"]
    assert line["machine_class_origin"]["kind"] == "tool"


async def test_hand_pick_leaves_a_named_machine_line_priced_before_108(
        client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    press = await _press(session_factory, world)
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    await _legacy(session_factory, m["id"], machine_id=press, rate=40,
                  detail={"machine_class_id": world["small"], "machine_id": press})
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["big"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    line = await _line(client, admin_auth, world, m["id"])
    assert line["rate"] == 40 and line["machine_class_used_id"] == world["small"]
    async with session_factory() as s:
        p = await s.get(CostingPosition, m["id"])
        assert "machine_class_origin" not in p.rate_detail
    assert costing_rates._moves_with_change_class(
        CostingPosition(kind="machine_time", machine_id=press, rate=40,
                        rate_on=datetime(2026, 1, 1).date(),
                        rate_detail={"machine_class_id": world["small"]}),
        world["big"]) is False


async def test_frozen_tool_class_rules():
    def line(**kw):
        base = dict(kind="machine_time", rate=85, rate_on=datetime(2026, 1, 1).date(),
                    machine_class_id=None, machine_id=None,
                    rate_detail={"unit": "h", "machine_class_id": 3})
        base.update(kw)
        return CostingPosition(**base)

    class Change:
        machine_class_id = None
    legacy = line()
    assert costing_rates.frozen_tool_class(legacy, Change()) == (3, None)
    picked = Change()
    picked.machine_class_id = 4
    assert costing_rates.frozen_tool_class(legacy, picked) is None
    assert costing_rates.frozen_tool_class(line(machine_id=9), Change()) is None
    assert costing_rates.frozen_tool_class(line(rate_on=None), Change()) is None
    assert costing_rates.frozen_tool_class(line(rate_detail={"unit": "h"}), Change()) is None
    tool = {"kind": "tool", "tool_number": "3454"}
    assert costing_rates.frozen_tool_class(line(rate_detail={
        "machine_class_id": 3, "machine_class_origin": tool}), Change()) == (3, tool)
    assert costing_rates.frozen_tool_class(line(rate_detail={
        "machine_class_id": 3, "machine_class_origin": {"kind": "change"}}), Change()) is None


async def test_machine_hour_booking_defaults_to_the_costed_class(
        client, admin_auth, world, session_factory):
    await _machine_version(session_factory, world)
    await _article_with_tool(session_factory, world, "3454")
    await _sync(session_factory, world, mdb_rows=[mdb("3454", qmin=350)], twos_rows=[])
    await _add(client, admin_auth, world, hours=1)       # Tool implements
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2)
    assert m["machine_class_used_id"] == world["big"]
    await _sync(session_factory, world,
                mdb_rows=[mdb("3454", assigned=180, machine="KM 180")], twos_rows=[])
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "in_implementation"
        await s.commit()

    async def book():
        res = await client.post(_url(world, "/implementation/bookings"), json={
            "department_id": world["tool"], "hours": 1, "machine_hours": 1},
            headers=admin_auth)
        assert res.status_code == 201, res.text
        return res.json()["machine_class_id"]
    # the class the machine hours were costed on, not today's tool class
    assert await book() == world["big"]
    # no priced machine line: the live class
    async with session_factory() as s:
        await s.delete(await s.get(CostingPosition, m["id"]))
        await s.commit()
    assert await book() == world["small"]


async def test_create_change_with_items_schedules_the_tonnage_refresh(
        client, admin_auth, world, session_factory, monkeypatch):
    tool_id = await _tool(session_factory, world, "3454")
    scheduled = []

    async def fake_refresh(change_id):
        scheduled.append(change_id)
    monkeypatch.setattr(tts, "any_source_configured", lambda: True)
    monkeypatch.setattr(tts, "refresh_change_in_background", fake_refresh)
    body = {"project_id": world["project_id"], "title": "with tool", "reason": "r",
            "change_type": "physical_part"}
    res = await client.post("/api/v1/changes", json=body, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert scheduled == []
    res = await client.post("/api/v1/changes", json={**body, "impacted_part_ids": [tool_id]},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    assert scheduled == [res.json()["id"]]
