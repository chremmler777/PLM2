"""The risk vocabulary, per department.

Same reasoning as the assessment checklist: this is config, not data. A risk
register is only countable across changes if the types are stable, so they
live in code where a change to them is a reviewed diff. Every department gets
the COMMON types; each gets its own on top — a Tool Engineer talks fill and
steel-safety, Quality talks gauges and PPAP. "other" is the escape hatch
everywhere: nobody is forced into a wrong type, the note still says what it is.

Pre-written risks a department wants to reuse are NOT here — those are the
department's own list (DepartmentRiskTemplate), editable in the app.
"""

# key -> (label_de, label_en)
COMMON_TYPES = [
    ("timing", "Termin/Zeitplan", "Timing / schedule"),
    ("cost", "Kosten", "Cost"),
    ("other", "Sonstiges", "Other"),
]

# Department name -> its own types. Names match wf_departments.name.
DEPARTMENT_TYPES = {
    "Tool Engineer": [
        ("fill_issue", "Füllprobleme", "Fill issue"),
        ("dimensional_issue", "Maßabweichung", "Dimensional issue"),
        ("visual_surface", "Oberfläche/Optik", "Visual / surface"),
        ("not_steel_safe", "Nicht stahlsicher", "Not steel-safe"),
        ("tool_damage_lifetime", "Werkzeugschaden/Standzeit", "Tool damage / lifetime"),
        ("hot_runner", "Heißkanal", "Hot runner"),
    ],
    "Process Engineer": [
        ("process_capability", "Prozessfähigkeit", "Process capability"),
        ("cycle_time", "Zykluszeit", "Cycle time"),
        ("warpage_shrinkage", "Verzug/Schwindung", "Warpage / shrinkage"),
        ("material_behaviour", "Materialverhalten", "Material behaviour"),
        ("automation_eoat", "Automation/EOAT", "Automation / EOAT"),
    ],
    "Manufacturing Engineer": [
        ("assembly_fit", "Montage/Passung", "Assembly fit"),
        ("equipment_capacity", "Anlagenkapazität", "Equipment capacity"),
        ("automation_eoat", "Automation/EOAT", "Automation / EOAT"),
        ("work_instruction", "Arbeitsanweisung", "Work instruction"),
    ],
    "Quality": [
        ("measurement_capability", "Messmittelfähigkeit", "Measurement capability (gauge)"),
        ("capability_proof", "Fähigkeitsnachweis (Cpk)", "Capability proof (Cpk)"),
        ("customer_approval", "Kundenfreigabe (PPAP)", "Customer approval (PPAP)"),
        ("inspection_effort", "Prüfaufwand", "Inspection effort"),
    ],
    "APQP": [
        ("pfmea_control_plan", "PFMEA/Control Plan", "PFMEA / control plan"),
        ("run_at_rate", "Run at Rate", "Run at rate"),
        ("sample_timing", "Bemusterungstermin", "Sample timing"),
    ],
    "Development": [
        ("design_feasibility", "Konstruktive Machbarkeit", "Design feasibility"),
        ("tolerance_stack", "Toleranzkette", "Tolerance stack"),
        ("function_requirement", "Funktion/Anforderung", "Function / requirement"),
        ("cad_data", "CAD-Daten", "CAD data"),
    ],
    "Packaging Engineer": [
        ("packaging_fit", "Verpackungspassung", "Packaging fit"),
        ("dunnage_change", "Ladungsträgeränderung", "Dunnage change"),
        ("transport_damage", "Transportschaden", "Transport damage"),
    ],
    "Sales": [
        ("customer_acceptance", "Kundenakzeptanz", "Customer acceptance"),
        ("pricing", "Preis", "Pricing"),
        ("contract", "Vertrag", "Contract"),
    ],
    "Project Manager": [
        ("resources", "Ressourcen", "Resources"),
        ("timeline", "Zeitplan", "Timeline"),
        ("budget", "Budget", "Budget"),
    ],
    "Scheduling": [
        ("capacity", "Kapazität", "Capacity"),
        ("bank_build", "Vorproduktion (Bank Build)", "Bank build"),
        ("material_availability", "Materialverfügbarkeit", "Material availability"),
    ],
}

# The pre-per-department vocabulary. Rows raised under it stay valid, and a
# department nobody configured can still raise them — the old list was the
# moulding view of the world and it is still true.
LEGACY_TYPES = [
    ("fill_issue", "Füllprobleme", "Fill issue"),
    ("dimensional_issue", "Maßabweichung", "Dimensional issue"),
    ("visual_surface", "Oberfläche/Optik", "Visual / surface"),
    ("process_capability", "Prozessfähigkeit", "Process capability"),
]


def _entry(item: tuple, extra: bool) -> dict:
    key, label_de, label_en = item
    return {"key": key, "label_de": label_de, "label_en": label_en, "extra": extra}


def types_for(department_name: str | None) -> list[dict]:
    """The department's own types first (they are what it came for), then
    the common ones with "other" last. Unknown or no department: the legacy
    moulding list plus the common set."""
    own = DEPARTMENT_TYPES.get(department_name or "")
    if own is None:
        own = LEGACY_TYPES
    return [_entry(i, True) for i in own] + [_entry(i, False) for i in COMMON_TYPES]


def keys_for(department_name: str | None) -> set:
    """What a raise for this department is validated against: its list, plus
    the legacy keys so old vocabulary never turns into a refusal."""
    return ({i["key"] for i in types_for(department_name)}
            | {k for k, _, _ in LEGACY_TYPES})


def all_keys() -> set:
    keys = {k for k, _, _ in COMMON_TYPES} | {k for k, _, _ in LEGACY_TYPES}
    for items in DEPARTMENT_TYPES.values():
        keys |= {k for k, _, _ in items}
    return keys


# ---- department-defined types (DB) -----------------------------------------

import re as _re


def custom_key(department_id: int, label: str) -> str:
    """A stable, namespaced key for a department's own type: 'd<id>_<slug>'.
    Namespacing keeps two departments' identical labels apart in the register."""
    slug = _re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")[:28]
    return f"d{department_id}_{slug or 'type'}"


async def custom_types_for(session, department_id: int | None) -> list[dict]:
    """The department's live self-defined types, in the dropdown's shape."""
    if department_id is None:
        return []
    from sqlalchemy import select
    from app.models.change import DepartmentRiskType
    rows = (await session.execute(
        select(DepartmentRiskType)
        .where(DepartmentRiskType.department_id == department_id,
               DepartmentRiskType.deleted_at.is_(None))
        .order_by(DepartmentRiskType.id))).scalars().all()
    return [{"key": r.key, "label_de": r.label, "label_en": r.label,
             "extra": True, "custom_id": r.id} for r in rows]


async def resolved_types(session, department) -> list[dict]:
    """Own coded types, then the department's self-defined ones, then the
    common set with 'other' last."""
    base = types_for(department.name if department is not None else None)
    own = [t for t in base if t["extra"]]
    common = [t for t in base if not t["extra"]]
    custom = await custom_types_for(session, department.id if department is not None else None)
    return own + custom + common


async def allowed_keys(session, department) -> set:
    """What a raise or a template for this department is validated against."""
    keys = keys_for(department.name if department is not None else None)
    if department is not None:
        # Deleted custom types stay valid: rows raised under them are history,
        # and re-saving such a row must not turn into a refusal.
        from sqlalchemy import select
        from app.models.change import DepartmentRiskType
        rows = (await session.execute(
            select(DepartmentRiskType.key)
            .where(DepartmentRiskType.department_id == department.id))).all()
        keys |= {k for (k,) in rows}
    return keys
