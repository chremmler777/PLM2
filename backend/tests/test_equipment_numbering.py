"""Equipment numbering per the 2026-07-24 'Naming of Equipment' scheme:
<tool#>[-<2-digit op code>]. Molds keep the bare tool number."""
import pytest

from app.services.equipment_numbering import (
    normalise_tool_ref, classify, parse_equipment_number, equipment_number,
    item_category_for,
)


def test_normalise_pads_to_four_digits():
    # The sheet writes 745; the PLM stores 0745.
    assert normalise_tool_ref("745") == ["0745"]
    assert normalise_tool_ref("3454") == ["3454"]


def test_normalise_splits_multi_tool_refs_and_sorts():
    assert normalise_tool_ref("918/919") == ["0918", "0919"]
    assert normalise_tool_ref("3454/3455") == ["3454", "3455"]


def test_normalise_strips_cavity_and_variant_suffixes():
    # 3197-001-0 and 930-002 name a variant of one tool, not an op code.
    assert normalise_tool_ref("3197-001-0") == ["3197"]
    assert normalise_tool_ref("930-002") == ["0930"]
    assert normalise_tool_ref("3101-01") == ["3101"]


def test_normalise_handles_mixed_multi_tool_and_suffix():
    assert normalise_tool_ref("931/990-001") == ["0931", "0990"]


def test_classify_maps_op_families():
    assert classify("10") == "eoat"
    assert classify("20") == "in_cell_station"
    assert classify("21") == "in_cell_station"
    assert classify("30") == "secondary_station"
    assert classify("40") == "gauge"
    assert classify("41") == "gauge"


def test_classify_rejects_unknown_family():
    with pytest.raises(ValueError):
        classify("50")


def test_parse_reads_tool_and_op_code():
    assert parse_equipment_number("3454-40") == ("3454", "40")


def test_parse_treats_bare_number_as_mold():
    assert parse_equipment_number("3454") == ("3454", None)


def test_parse_treats_single_digit_suffix_as_a_second_tool():
    # 0674 is tool 1, 0674-2 is tool 2 — a tool in its own right, not op code 2.
    assert parse_equipment_number("0674-2") == ("0674-2", None)


def test_parse_reads_equipment_on_a_second_tool():
    assert parse_equipment_number("0674-2-40") == ("0674-2", "40")


def test_parse_keeps_four_digit_suffix_tools_intact():
    # The 91-xxxx family numbers tools with a four-digit suffix.
    assert parse_equipment_number("91-0001") == ("91-0001", None)
    assert parse_equipment_number("91-0001-40") == ("91-0001", "40")


def test_parse_rejects_unknown_two_digit_family():
    with pytest.raises(ValueError):
        parse_equipment_number("3454-50")


def test_equipment_number_indexes_within_family():
    assert equipment_number("3454", 4, 0) == "3454-40"
    assert equipment_number("3454", 4, 1) == "3454-41"
    assert equipment_number("3450", 2, 0) == "3450-20"


def test_equipment_number_rejects_index_overflow():
    with pytest.raises(ValueError):
        equipment_number("3454", 4, 10)


def test_item_category_splits_gauges_from_equipment():
    assert item_category_for("40") == "gauge"
    assert item_category_for("41") == "gauge"
    assert item_category_for("10") == "assembly_equipment"
    assert item_category_for("30") == "assembly_equipment"
