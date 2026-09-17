"""Pure rules for E<n>[.<m>] (review) and <n>[.<m>] (official) names."""
from datetime import datetime

import pytest

from app.services.revision_naming import (
    RevisionRuleViolation, format_name, legacy_rename, next_major_name,
    next_minor_name, parse_name,
)


def test_parse_and_format_roundtrip():
    for name, expected in [
        ("E1", (False, 1, None)), ("E12.3", (False, 12, 3)),
        ("1", (True, 1, None)), ("4.2", (True, 4, 2)),
    ]:
        assert parse_name(name) == expected
        assert format_name(*expected) == name


@pytest.mark.parametrize("bad", ["RFQ1", "ENG1.1", "IND1", "ECR1.1", "E", "E0", "0", "1.0", "e1", "E1.1.1", ""])
def test_parse_rejects_legacy_and_garbage(bad):
    with pytest.raises(ValueError):
        parse_name(bad)


def test_first_major_is_e1_or_1():
    assert next_major_name([], "review") == "E1"
    assert next_major_name([], "official") == "1"


def test_counters_are_independent_and_never_reset():
    assert next_major_name(["E1", "E2"], "review") == "E3"
    assert next_major_name(["E1", "E2"], "official") == "1"
    assert next_major_name(["E1", "E2", "1"], "official") == "2"
    assert next_major_name(["1", "3"], "official") == "4"


def test_review_after_official_is_a_rule_violation():
    with pytest.raises(RevisionRuleViolation):
        next_major_name(["E1", "1"], "review")


def test_next_major_ignores_minors_in_input():
    assert next_major_name(["E1", "E1.1", "E1.2"], "review") == "E2"


def test_next_minor():
    assert next_minor_name("E1", []) == "E1.1"
    assert next_minor_name("E1", ["E1.1", "E1.2"]) == "E1.3"
    assert next_minor_name("2", ["2.1"]) == "2.2"


def test_next_minor_refuses_minor_parent():
    with pytest.raises(ValueError):
        next_minor_name("E1.1", [])


def _row(i, name, phase, parent=None, day=1):
    return (i, name, phase, parent, datetime(2026, 1, day))


def test_legacy_rename_maps_rfq_eng_ind_ecr():
    rows = [
        _row(1, "RFQ1", "rfq_phase", day=1),
        _row(2, "RFQ1.1", "rfq_phase", parent=1, day=2),
        _row(3, "RFQ2", "rfq_phase", day=3),
        _row(4, "ENG1", "engineering", day=4),
        _row(5, "ENG1.1", "engineering", parent=4, day=5),
        _row(6, "IND1", "freeze", day=6),
        _row(7, "ECR1.1", "ecn", day=7),
        _row(8, "IND2", "freeze", day=8),
        _row(9, "ECR2.1", "ecn", day=9),
    ]
    assert legacy_rename(rows) == {
        1: ("E1", "review"), 2: ("E1.1", "review"), 3: ("E2", "review"),
        4: ("E3", "review"), 5: ("E3.1", "review"),
        6: ("1", "official"), 7: ("1.1", "official"),
        8: ("2", "official"), 9: ("2.1", "official"),
    }


def test_legacy_rename_orphan_ecr_without_freeze_hangs_off_first_official():
    rows = [_row(1, "E1", "review"), _row(2, "ECR1.1", "ecn", day=2), _row(3, "ECR2.1", "ecn", day=3)]
    assert legacy_rename(rows) == {1: ("E1", "review"), 2: ("1.1", "official"), 3: ("1.2", "official")}


def test_legacy_rename_leaves_new_style_names_alone():
    rows = [_row(1, "E1", "review"), _row(2, "E1.1", "review", parent=1, day=2), _row(3, "1", "official", day=3)]
    assert legacy_rename(rows) == {1: ("E1", "review"), 2: ("E1.1", "review"), 3: ("1", "official")}
