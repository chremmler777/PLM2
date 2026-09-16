"""Cost categories per department, each with the kind of line it makes.

Config, not data — the same call assessment_checklist.py makes. A category is
what makes positions countable across changes ("what does a tool change
usually cost us?"), and every category says what a line under it IS:

  money — something bought: a house estimate or a vendor's quote
  time  — the department's own hours, valued at its rate

Every department gets the COMMON categories; each gets its own on top, in the
order the department thinks about them. A department extends the list itself
(DepartmentCostCategory): a word nobody thought of is one click away and it
persists, so the count still works next time.

The write endpoints still accept any tag string: rows raised under a category
that was later removed keep their key, and imports keep working.
"""

ENTRY_TYPES = ("money", "time")

# key -> (label_de, label_en, entry_type)
COMMON_CATEGORIES = [
    ("other_money", "Sonstiges (Kosten)", "Other (cost)", "money"),
    ("other_time", "Sonstiges (Eigenzeit)", "Other (own time)", "time"),
]

DEPARTMENT_CATEGORIES = {
    "Tool Engineer": [
        ("tool_change", "Werkzeugänderung / Nacharbeit", "Tool change / rework", "money"),
        ("hot_runner", "Heißkanal", "Hot runner", "money"),
        ("steel_insert", "Stahleinsatz", "Steel insert", "money"),
        ("tool_transfer", "Werkzeugtransfer", "Tool transfer", "money"),
        ("spare_part", "Ersatzteil", "Spare part", "money"),
        ("external_design", "Externe Konstruktion", "External design", "money"),
        ("moldflow", "Moldflow", "Moldflow", "money"),
        ("sampling", "Bemusterung", "Sampling", "time"),
        ("trial_support", "Versuchsbegleitung", "Trial support", "time"),
    ],
    "Process Engineer": [
        ("automation", "Automation / EOAT", "Automation / EOAT", "money"),
        ("trial_equipment", "Versuchsausrüstung", "Process trial equipment", "money"),
        ("process_trial", "Prozessversuch", "Process trial", "time"),
        ("cycle_time_study", "Zykluszeitstudie", "Cycle time study", "time"),
        ("parameter_setup", "Parametereinstellung", "Parameter setup", "time"),
    ],
    "Manufacturing Engineer": [
        ("fixture_change", "Vorrichtungsänderung", "Fixture change", "money"),
        ("eoat_change", "EOAT-Änderung", "EOAT change", "money"),
        ("equipment_change", "Anlagenänderung", "Equipment change", "money"),
        ("line_layout", "Linienlayout", "Line layout", "money"),
        ("spare_part", "Ersatzteil", "Spare part", "money"),
        ("robot_program", "Roboterprogramm", "Robot program", "time"),
        ("work_instruction", "Arbeitsanweisung", "Work instruction", "time"),
        ("setup", "Einrichtung", "Setup", "time"),
    ],
    "Quality": [
        ("gauge_change", "Lehrenänderung", "Gauge change", "money"),
        ("measurement_equipment", "Messmittel", "Measurement equipment", "money"),
        ("supplier_audit", "Lieferantenaudit", "Supplier audit", "money"),
        ("layout_inspection", "Erstmusterprüfung", "Layout inspection", "time"),
        ("capability_study", "Fähigkeitsuntersuchung", "Capability study", "time"),
        ("measurement", "Messung", "Measurement", "time"),
    ],
    "APQP": [
        ("ppap_documentation", "PPAP-Dokumentation", "PPAP documentation", "time"),
        ("control_plan_update", "Control Plan", "Control plan update", "time"),
        ("pfmea_update", "PFMEA", "PFMEA update", "time"),
        ("run_at_rate", "Run at Rate", "Run at rate", "time"),
    ],
    "Development": [
        ("external_design", "Externe Konstruktion", "External design", "money"),
        ("simulation", "Simulation", "Simulation", "money"),
        ("prototyping", "Prototypen", "Prototyping", "money"),
        ("cad_update", "CAD-Anpassung", "CAD update", "time"),
        ("drawing_update", "Zeichnungsanpassung", "Drawing update", "time"),
        ("tolerance_study", "Toleranzstudie", "Tolerance study", "time"),
    ],
    "Packaging Engineer": [
        ("packaging_change", "Verpackungsänderung", "Packaging change", "money"),
        ("dunnage", "Ladungsträger", "Dunnage", "money"),
        ("packaging_trial", "Verpackungsversuch", "Packaging trial", "money"),
        ("freight", "Fracht", "Freight", "money"),
        ("packaging_trial_support", "Versuchsbegleitung Verpackung", "Packaging trial support", "time"),
        ("documentation", "Dokumentation", "Documentation", "time"),
    ],
    "Scheduling": [
        ("storage", "Lagerung", "Storage", "money"),
        ("freight", "Fracht", "Freight", "money"),
        ("bank_build_planning", "Vorproduktionsplanung", "Bank build planning", "time"),
    ],
    "Project Manager": [
        ("project_coordination", "Projektkoordination", "Project coordination", "time"),
    ],
}

# The pre-per-department list, kept so a department nobody configured still
# has words, and so old tags resolve to a label.
LEGACY_CATEGORIES = [
    ("tool_change", "Werkzeugänderung", "Tool change", "money"),
    ("equipment_change", "Anlagenänderung", "Equipment change", "money"),
    ("gauge_change", "Lehrenänderung", "Gauge change", "money"),
    ("external_design", "Externe Konstruktion", "External design", "money"),
    ("moldflow", "Moldflow", "Moldflow", "money"),
    ("testing", "Erprobung", "Testing", "time"),
    ("sampling", "Bemusterung", "Sampling", "time"),
    ("measurement", "Messung", "Measurement", "time"),
    ("prototyping", "Prototypen", "Prototyping", "money"),
    ("packaging_change", "Verpackungsänderung", "Packaging change", "money"),
    ("process_trial", "Prozessversuch", "Process trial", "time"),
    ("automation", "Automatisierung", "Automation", "money"),
    ("documentation", "Dokumentation", "Documentation", "time"),
    ("other", "Sonstiges", "Other", "money"),
]


def _entry(item: tuple, extra: bool) -> dict:
    key, label_de, label_en, entry_type = item
    return {"key": key, "label_de": label_de, "label_en": label_en,
            "extra": extra, "entry_type": entry_type}


def tags_for(department_name: str | None) -> list[dict]:
    """The department's own categories first, then the common two. An
    unknown department gets the legacy list plus the common two."""
    own = DEPARTMENT_CATEGORIES.get(department_name or "")
    if own is None:
        own = LEGACY_CATEGORIES
    return [_entry(i, True) for i in own] + [_entry(i, False) for i in COMMON_CATEGORIES]


def label_for(key: str) -> str | None:
    """English label for any coded key, wherever it lives."""
    for items in (COMMON_CATEGORIES, LEGACY_CATEGORIES, *DEPARTMENT_CATEGORIES.values()):
        for k, _de, en, _t in items:
            if k == key:
                return en
    return None


# ---- department-defined categories (DB) -----------------------------------

import re as _re


def custom_key(department_id: int, label: str) -> str:
    slug = _re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")[:28]
    return f"d{department_id}_{slug or 'category'}"


async def custom_categories_for(session, department_id: int | None) -> list[dict]:
    if department_id is None:
        return []
    from sqlalchemy import select
    from app.models.change_cost import DepartmentCostCategory
    rows = (await session.execute(
        select(DepartmentCostCategory)
        .where(DepartmentCostCategory.department_id == department_id,
               DepartmentCostCategory.deleted_at.is_(None))
        .order_by(DepartmentCostCategory.id))).scalars().all()
    return [{"key": r.key, "label_de": r.label, "label_en": r.label,
             "extra": True, "entry_type": r.entry_type, "custom_id": r.id}
            for r in rows]


async def resolved_tags(session, department) -> list[dict]:
    """Own coded categories, the department's self-defined ones, then the
    common two."""
    base = tags_for(department.name if department is not None else None)
    own = [t for t in base if t["extra"]]
    common = [t for t in base if not t["extra"]]
    custom = await custom_categories_for(session, department.id if department is not None else None)
    return own + custom + common
