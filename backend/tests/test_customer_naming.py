from datetime import date

from app.services.customer_naming import CONVENTIONS, KIND_LABELS, kind_label, parse_filename


def test_vw_pca_part_model():
    p = parse_filename("206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.CATPart", "vw")
    assert p.customer_part_number == "206.881.479"
    assert p.variant is None
    assert p.kind == "PCA"
    assert p.kind_label.startswith("PCA engineering master")
    assert p.model_type == "TM"
    assert p.customer_index == "003"
    assert p.release == "B-RELEASE"
    assert p.dated == date(2026, 5, 28)


def test_vw_dmu_and_drawing():
    d = parse_filename("206_885_967____DMU_TM__004_____LATCH_COVER_40_____B-RELEASE_2026-05-28.CATPart", "vw")
    assert (d.kind, d.customer_index, d.dated) == ("DMU", "004", date(2026, 5, 28))
    z = parse_filename("206_887_233____DRW_TZ__001_____ISOFIX_COVER_______B-RELEASE___20260528.pdf", "vw")
    assert (z.kind, z.model_type, z.customer_index) == ("DRW", "TZ", "001")
    assert z.kind_label == KIND_LABELS["DRW"]


def test_vw_variant_letter_and_assembly_position():
    v = parse_filename("206_881_971_B__PCA_TM__001_____SEAT_BACK_PANEL____B-RELEASE___20260528.stp", "vw")
    assert v.customer_part_number == "206.881.971.B"
    assert v.variant == "B"
    g = parse_filename("206_881_971____G02_TM__004_003_MAP_POCKET_________B-RELEASE___20260528.stp", "vw")
    assert g.kind == "G02"
    assert g.kind_label == "Assembly position G02."
    assert g.customer_index == "004"


def test_vw_release_stage_variants():
    c = parse_filename("206_881_971____PCA_TM__003_____SEAT_BACK_PANEL____CP3_________20260220.stp", "vw")
    assert (c.release, c.dated) == ("CP3", date(2026, 2, 20))
    u = parse_filename("206_886_197____PCA_TM__003_000_CTR_BEARING_COVER__B_RELEASE___20260528.stp", "vw")
    assert (u.release, u.customer_index) == ("B_RELEASE", "003")


def test_vw_release_cp_stage_with_two_digits_is_not_truncated():
    c = parse_filename("206_881_971____PCA_TM__003_____SEAT_BACK_PANEL____CP10_________20260220.stp", "vw")
    assert (c.release, c.dated) == ("CP10", date(2026, 2, 20))


def test_vw_non_matching_name_is_empty_but_keeps_filename():
    p = parse_filename("readme.txt", "vw")
    assert p.filename == "readme.txt"
    assert p.customer_part_number is None and p.customer_index is None and p.kind is None


def test_none_convention_falls_back_to_letter_index():
    p = parse_filename("3CR807425B_Unterfahrschutz.stp", None, customer_part_number="3CR.807.425")
    assert p.customer_index == "B"
    assert p.kind is None
    q = parse_filename("3CR807425_Unterfahrschutz.stp", None, customer_part_number="3CR.807.425")
    assert q.customer_index is None


def test_scout_parses_like_vw_for_now():
    p = parse_filename("206_881_479____PCA_TM__003_____X___B-RELEASE___20260528.CATPart", "scout")
    assert p.customer_index == "003"


def test_unknown_convention_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_filename("x.stp", "bmw")


def test_registry_and_labels():
    assert CONVENTIONS == {"vw": "VW group", "scout": "Scout"}
    assert kind_label("PCA") == KIND_LABELS["PCA"]
    assert kind_label("G07") == "Assembly position G07."
    assert kind_label("XYZ") is None
    assert kind_label(None) is None
