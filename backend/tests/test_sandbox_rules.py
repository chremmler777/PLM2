"""Sandbox instance rules (app/sandbox.py): who gets in, which departments
they get in their own copy, and the per-person database name."""
from app import sandbox


def test_db_name_is_per_person_and_safe():
    assert sandbox.db_name_for("cody.hrtyanski") == "plm_sbx_cody_hrtyanski"
    assert sandbox.db_name_for('Evil"; DROP') == "plm_sbx_evil_drop"
    assert sandbox.db_name_for("...") == "plm_sbx_user"


def test_only_pm_sales_and_admin_get_in():
    assert sandbox.allowed(["plm2_ProjectManager"])
    assert sandbox.allowed(["plm2_Sales"])
    assert sandbox.allowed(["plm2_Admin"])
    assert not sandbox.allowed(["plm2_APQP"])
    assert not sandbox.allowed([])


def test_pm_and_sales_both_get_both_departments():
    assert set(sandbox.widen_roles(["plm2_ProjectManager"])) == {
        "plm2_ProjectManager", "plm2_Sales"}
    assert set(sandbox.widen_roles(["plm2_Sales", "plm2_Quality"])) == {
        "plm2_Sales", "plm2_Quality", "plm2_ProjectManager"}
    assert sandbox.widen_roles(["plm2_Admin"]) == ["plm2_Admin"]
    assert sandbox.widen_roles(["plm2_APQP"]) == ["plm2_APQP"]
