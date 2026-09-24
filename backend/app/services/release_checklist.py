"""The release checklist (stage 10): what has to be true before a change is
released, and which department answers for each item.

Config in code, like the validation catalog next door: the list is part of the
process definition, reviewed with it, and changing it is a code change on
purpose. The owner is a department NAME, resolved to an id when a change's
rows are seeded, so a database without one of these departments still gets
the item (owned by nobody, answerable by PM, lead and admin).
"""

# (key, label, owner department name)
RELEASE_CHECKS: list[tuple[str, str, str]] = [
    ("index_updated",
     "Part index / revision level updated in drawing and PLM", "Development"),
    ("drawing_released",
     "Drawing and 3D data released and distributed", "Development"),
    ("equipment_updated",
     "Tool and equipment data updated (tool card, equipment list)", "Tool Engineer"),
    ("parts_measured",
     "Parts measured, measurement report on file", "APQP"),
    ("weight_measured",
     "Part weight measured and recorded", "Tool Engineer"),
    ("cycle_time_confirmed",
     "Cycle time confirmed in series production", "Manufacturing Engineer"),
    ("documents_updated",
     "PFMEA, control plan and work instructions updated", "APQP"),
    ("packaging_updated",
     "Packaging instruction updated", "Packaging Engineer"),
    ("customer_approval",
     "Customer approval received (PPAP / ISIR / PSW)", "APQP"),
    ("erp_updated",
     "ERP, BOM and routing updated", "Scheduling"),
    ("stock_handled",
     "Old stock handled as agreed (bank consumed or scrapped)", "Scheduling"),
    ("customer_informed",
     "Customer informed of the implementation date / first shipment", "Sales"),
    ("spare_parts",
     "Spare and service parts considered", "Development"),
]

CHECK_KEYS = [k for k, _, _ in RELEASE_CHECKS]
_BY_KEY = {k: (label, dept) for k, label, dept in RELEASE_CHECKS}


def label_for(key: str) -> str:
    return _BY_KEY.get(key, (key, None))[0]


def owner_for(key: str) -> str | None:
    return _BY_KEY.get(key, (None, None))[1]
