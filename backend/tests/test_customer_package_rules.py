"""Pure rules of the customer package receive: match a file to a part, read
the index from the filename, decide whether the part changed."""
import pytest

from app.services.customer_package import Candidate, decide_action, index_from_filename, match_file, squash

TREE = [
    Candidate(1, "1994-100", "3CR.807.425", True),
    Candidate(2, "1994-110", "3CR.807.531.A", True),
    Candidate(3, "1994-900", None, False),
]


def test_squash_drops_separators_and_case():
    assert squash("3CR.807.425.B") == "3cr807425b"
    assert squash(None) == ""


@pytest.mark.parametrize("filename,expected", [
    ("3CR807425B_Unterfahrschutz.stp", 1),
    ("3cr-807-425.pdf", 1),
    ("3CR.807.531.A.step", 2),
    ("1994-900 clamp.stp", 3),
    ("1994_900.pdf", 3),
    ("unrelated.stp", None),
])
def test_match_by_customer_number_then_our_number(filename, expected):
    m = match_file(filename, TREE)
    assert (m.part_id if m else None) == expected


def test_tree_candidates_win_over_project_candidates():
    cands = [Candidate(9, "X", "3CR.807.425", False), Candidate(1, "Y", "3CR.807.425", True)]
    assert match_file("3CR807425.stp", cands).part_id == 1


def test_longest_customer_number_wins():
    # 3CR.807.531 vs 3CR.807.531.A: the file names the longer one
    cands = [Candidate(1, "A", "3CR.807.531", True), Candidate(2, "B", "3CR.807.531.A", True)]
    assert match_file("3CR807531A.stp", cands).part_id == 2
    assert match_file("3CR807531.stp", cands).part_id == 1


@pytest.mark.parametrize("filename,number,expected", [
    ("3CR807425B_Unterfahrschutz.stp", "3CR.807.425", "B"),
    ("3CR.807.425.B.stp", "3CR.807.425", "B"),
    ("3CR-807-425-C.pdf", "3CR.807.425", "C"),
    ("3CR807425.stp", "3CR.807.425", None),
    ("3CR807425_Unterfahrschutz.stp", "3CR.807.425", None),
    ("3CR807425AB.stp", "3CR.807.425", None),
    ("anything.stp", None, None),
])
def test_index_from_filename(filename, number, expected):
    assert index_from_filename(filename, number) == expected


@pytest.mark.parametrize("row,current,expected", [
    ("B", "B", "unchanged"), ("b ", "B", "unchanged"),
    ("C", "B", "new_major"), ("B", None, "new_major"), (None, "B", "new_major"), (None, None, "new_major"),
])
def test_decide_action(row, current, expected):
    assert decide_action(row, current) == expected
