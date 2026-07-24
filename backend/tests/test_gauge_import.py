"""Planning the FM-QUA-0094-17 import. Pure decision logic over plain rows:
lowest-tool-ID ownership, per-tool index allocation, idempotency, and a report
that names every skipped row rather than guessing."""
from app.services.gauge_import import GaugeRow, plan_import

TOOLS = {"0918", "0919", "3454", "3455", "0745"}


def row(tool_ref, desc="Cover", legacy="P1", customer="BMW", storage="Cage A/1/2"):
    return GaugeRow(customer=customer, tool_ref=tool_ref, description=desc,
                    legacy_no=legacy, storage=storage)


def test_single_tool_gauge_gets_index_zero():
    plan, report = plan_import([row("745", legacy="P7")], TOOLS, set())
    assert len(plan) == 1
    assert plan[0].part_number == "0745-40"
    assert plan[0].owner_tool == "0745"
    assert plan[0].serves == ["0745"]


def test_multi_tool_gauge_is_numbered_after_the_lowest_tool():
    plan, report = plan_import([row("3454/3455", legacy="P1289")], TOOLS, set())
    assert plan[0].part_number == "3454-40"
    assert plan[0].serves == ["3454", "3455"]
    assert any("3454/3455" in line and "3454" in line for line in report)


def test_two_gauges_on_one_tool_take_consecutive_indices():
    plan, _ = plan_import(
        [row("745", desc="LH", legacy="P7"), row("745", desc="RH", legacy="P57")],
        TOOLS, set())
    assert [p.part_number for p in plan] == ["0745-40", "0745-41"]


def test_index_allocation_counts_against_the_owner_tool_only():
    plan, _ = plan_import(
        [row("3454/3455", legacy="P1289"), row("3455", legacy="P9")], TOOLS, set())
    # the multi-tool gauge is owned by 3454, so 3455 is still free at index 0
    assert [p.part_number for p in plan] == ["3454-40", "3455-40"]


def test_unknown_tool_is_reported_and_skipped():
    plan, report = plan_import([row("9999", legacy="P3")], TOOLS, set())
    assert plan == []
    assert any("9999" in line for line in report)


def test_unparseable_tool_ref_is_reported_and_skipped():
    plan, report = plan_import([row("n/a", legacy="P3")], TOOLS, set())
    assert plan == []
    assert any("n/a" in line for line in report)


def test_already_imported_row_is_skipped():
    # Idempotency key is (owner tool, legacy no) — P468/P481/P419 each appear
    # twice in the sheet on DIFFERENT tools, so the legacy number alone is not unique.
    plan, _ = plan_import([row("745", legacy="P7")], TOOLS, {("0745", "P7")})
    assert plan == []


def test_same_legacy_number_on_two_tools_both_import():
    plan, _ = plan_import(
        [row("745", legacy="P468"), row("3454", legacy="P468")], TOOLS, set())
    assert [p.part_number for p in plan] == ["0745-40", "3454-40"]


def test_notes_carry_the_legacy_number_and_storage():
    plan, _ = plan_import(
        [row("745", legacy="P7", storage="Cage Racks / C / 5 / 3")], TOOLS, set())
    assert "P7" in plan[0].notes
    assert "Cage Racks / C / 5 / 3" in plan[0].notes


def test_eleventh_gauge_on_one_tool_is_reported_not_crashed():
    rows = [row("745", legacy=f"P{i}") for i in range(11)]
    plan, report = plan_import(rows, TOOLS, set())
    assert len(plan) == 10
    assert any("P10" in line for line in report)


def test_excluded_row_is_reported_and_never_imported():
    """P1403 is a caliber measurement, not a gauge — it must not come back on a
    re-import after being deleted from the database."""
    from app.services.gauge_import import EXCLUSIONS

    assert ("3457", "P1403") in EXCLUSIONS
    plan, report = plan_import(
        [row("3457", desc="PDC Bracket", legacy="P1403")], TOOLS | {"3457"}, set())
    assert plan == []
    assert any("P1403" in line and "caliber" in line for line in report)
