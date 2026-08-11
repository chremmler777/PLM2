"""The assessment checklist: a fixed set of questions every department answers.

This is config, not data. The questions are the same for every change and every
project — "does this change alter the cycle time?", "is a 3D change needed?" —
so they live in code where they can be reviewed in a diff, rather than in rows
somebody can quietly edit per department. The activity CATALOG
(AssessmentActivity) stays what it always was: the costing selection list.

Every routed department answers the COMMON items. A few departments answer
extra ones that only make sense for them. `GET
/changes/reference/assessment-checklist?department_id=N` serves the resolved
set so the frontend renders from here instead of hardcoding the same list a
second time.
"""

# key -> (label_de, label_en, choices)
# `choices` is None for a plain yes/no item, or a list of options when the
# answer needs a sub-choice as well.
COMMON_ITEMS = [
    ("cycle_time_change", "Zykluszeitänderung", "Cycle time change", None),
    ("scrap_increase", "Ausschusserhöhung", "Scrap increase", None),
    ("maintenance_increase", "Erhöhter Wartungsaufwand",
     "Increased maintenance", None),
    ("threed_change", "3D-Änderung erforderlich", "3D change necessary", None),
    ("dimensional_risk", "Maßliches Risiko", "Dimensional risk", None),
    ("visual_risk", "Optisches Risiko", "Visual risk", None),
    ("work_instruction_update", "Arbeitsanweisung aktualisieren",
     "Work instruction update", None),
    ("new_process", "Neuer Prozess", "New process", None),
    ("sparepart_required", "Ersatzteil erforderlich", "Spare part required", None),
    # Two independent ticks, not a choice: a change can rebuild something in
    # house AND send work to a supplier.
    ("modification_internal", "Interne Änderung/Umbau",
     "Internal modification", None),
    ("modification_external", "Externe Änderung/Umbau (Lieferant)",
     "External modification (supplier)", None),
    ("prototyping_required", "Prototypen/Musterbau erforderlich",
     "Prototyping required", None),
    ("matching_required", "Abmusterung/Matching erforderlich",
     "Matching/sampling required", None),
]

# Checking this is a promise to ask a supplier what it costs and how long it
# takes, so an RFQ document is expected against the assessment. Expected, not
# enforced: the department may still be writing it when they submit, and a
# submit gate here would just teach people to attach an empty file.
RFQ_EXPECTED_KEYS = {"modification_external"}

_DESIGN_CHOICES = [
    {"value": "internal", "label_de": "Intern", "label_en": "Internal"},
    {"value": "customer_given", "label_de": "Kundenvorgabe",
     "label_en": "Customer given"},
]

# Department name -> its extra items, in the same tuple shape.
DEPARTMENT_ITEMS = {
    "APQP": [
        ("pfmea_update", "PFMEA aktualisieren", "PFMEA update", None),
        ("control_plan_update", "Control Plan aktualisieren",
         "Control plan update", None),
    ],
    "Development": [
        ("article_design_update", "Artikelkonstruktion anpassen",
         "Article design update", _DESIGN_CHOICES),
    ],
}

# The one item whose cost is per part for the life of the programme; every
# other checked item seeds a one-off line. See CostService.seed_from_checklist.
LIFECYCLE_KEYS = {"cycle_time_change"}


def _entry(item: tuple, extra: bool) -> dict:
    key, label_de, label_en, choices = item
    out = {"key": key, "label_de": label_de, "label_en": label_en,
           "extra": extra}
    if choices:
        out["choices"] = choices
    return out


def items_for(department_name: str | None) -> list[dict]:
    """The full checklist a department answers: the common items, then its own.

    An unknown department still gets the common set — a department nobody
    thought to configure has questions to answer just like everyone else.
    """
    items = [_entry(i, False) for i in COMMON_ITEMS]
    items += [_entry(i, True)
              for i in DEPARTMENT_ITEMS.get(department_name or "", [])]
    return items


def keys_for(department_name: str | None) -> set:
    return {i["key"] for i in items_for(department_name)}


def label_for(key: str, department_name: str | None) -> str | None:
    """English label, used when a checked item becomes a cost line."""
    for item in items_for(department_name):
        if item["key"] == key:
            return item["label_en"]
    return None


def choices_for(key: str, department_name: str | None) -> list:
    for item in items_for(department_name):
        if item["key"] == key:
            return [c["value"] for c in item.get("choices", [])]
    return []
