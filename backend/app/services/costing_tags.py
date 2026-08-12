"""Suggested tags for costing positions.

Config, not data — the same call assessment_checklist.py makes. A tag is what
makes positions countable across changes ("what does a tool change usually cost
us?"), and a list somebody can quietly edit per department would make that
count meaningless. Reviewed in a diff instead.

Unlike the checklist, this list does NOT constrain writes: CostingPosition.tag
is free text, and a department that needs a word nobody thought of types it.
The endpoint is a suggestion list, so the common cases are one click and the
odd one is still possible.
"""

# Everybody's tags: things any department can end up paying for.
COMMON_TAGS = (
    "tool_change", "equipment_change", "gauge_change", "external_design",
    "moldflow", "testing", "sampling", "measurement", "prototyping",
    "packaging_change", "process_trial", "automation", "documentation",
    "other",
)

# Department name -> the extras that only make sense for it. Keyed by the same
# department names _DOMAIN_BY_DEPARTMENT uses, so a department owning tools
# gets tool words and nobody else is offered them.
DEPARTMENT_TAGS = {
    "Tool Engineer": ("tool_rework", "hot_runner", "steel_insert",
                      "tool_transfer", "spare_part"),
    "Manufacturing Engineer": ("fixture_change", "eoat_change",
                               "robot_program", "line_layout", "spare_part"),
    "APQP": ("ppap_documentation", "control_plan_update", "pfmea_update",
             "capability_study"),
    "Development": ("cad_update", "drawing_update", "tolerance_study",
                    "simulation"),
    "Quality": ("layout_inspection", "supplier_audit"),
    "Logistics": ("packaging_trial", "freight", "storage"),
}


def tags_for(department_name: str | None) -> list[dict]:
    """The common tags, then the department's own. A department nobody
    configured still gets the common set — it has costs like everyone else."""
    items = [{"key": k, "extra": False} for k in COMMON_TAGS]
    seen = {k for k in COMMON_TAGS}
    for key in DEPARTMENT_TAGS.get(department_name or "", ()):
        if key in seen:
            continue
        seen.add(key)
        items.append({"key": key, "extra": True})
    return items
