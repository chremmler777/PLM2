"""The validation checklist: what each implementing department must confirm.

Config, not data — the same call assessment_checklist.py makes. The checks are
the same for every change and every project ("was the tool sampled?", "what
cycle time did you measure?"), so they live in code where a diff shows the
change, rather than in rows somebody can quietly edit for one department.

The departments working on the tool and the line (Tool Engineer,
Manufacturing Engineer, Process Engineer) answer the COMMON checks. The
cycle time is measured by the Tool Engineer alone (decision 2026-09-26): a
cycle time Manufacturing or Process Engineer recorded under the older
catalog stays on the record, read-only and not counted. APQP answers for
the measured parts, Packaging for the packaging with the changed part, and
two checks are the reason stage 9 exists at all:

  Tool Engineer  weight — the sampled part goes on a scale and the number is
                 compared to the weight the QUOTE was built on. The delta is a
                 commercial event, not a technical one: Sales updates the
                 quote with it.
  Development    revision_bump — the revision levels were raised the way the
                 customer's statement said they would be, and somebody looked
                 to confirm it. A change whose paperwork says rev C while the
                 customer was promised rev D is released wrong.

`expects_value` marks the checks that are a MEASUREMENT rather than a yes: a
cycle time nobody wrote down cannot be compared against the lifecycle
assumption the costing was built on, and a weight nobody wrote down cannot
produce a delta. Passing one of those without a number is refused.

The unit lives here too, next to the key, because the storage column
(ValidationCheck.value) is deliberately one untyped Numeric and this file is
what tells a reader what the number means.
"""

# key -> (label_de, label_en, expects_value, unit)
COMMON_CHECKS = [
    ("sampled", "Werkzeug abgemustert", "Tool sampled", False, None),
    ("measured", "Teil vermessen", "Part measured", False, None),
]

# The departments whose work is on the tool and the line: they sample and
# measure it (the Tool Engineer also times it, below). Everyone else answers only for their own scope below
# (or owes no validation check at all).
COMMON_DEPARTMENTS = ("Tool Engineer", "Manufacturing Engineer",
                      "Process Engineer")

# Department name -> its own checks, same tuple shape.
DEPARTMENT_CHECKS = {
    "Tool Engineer": [
        ("cycle_time", "Zykluszeit gemessen", "Measured cycle time", True,
         "seconds"),
        ("weight", "Teilegewicht validiert", "Part weight validated", True,
         "grams"),
    ],
    "APQP": [
        ("measured", "Teile vermessen", "Parts measured", False, None),
    ],
    "Packaging Engineer": [
        ("packaging_validated", "Verpackung mit geändertem Teil validiert",
         "Packaging validated with the changed part", False, None),
    ],
    "Development": [
        ("revision_bump", "Änderungsstände gemäß Kundenaussage angehoben",
         "Revision levels raised per customer statement and verified",
         False, None),
    ],
}

# The check whose passing number is a commercial fact rather than a technical
# one: it stamps the change's validated weight and can raise a Sales task.
WEIGHT_KEY = "weight"
# The check compared against the costing's lifecycle assumption (the
# minutes-per-part the change was priced on). Measured by one department.
CYCLE_TIME_KEY = "cycle_time"
CYCLE_TIME_DEPARTMENT = "Tool Engineer"


def _entry(item: tuple, extra: bool) -> dict:
    key, label_de, label_en, expects_value, unit = item
    return {"key": key, "label_de": label_de, "label_en": label_en,
            "expects_value": expects_value, "unit": unit, "extra": extra}


def items_for(department_name: str | None) -> list[dict]:
    """The checks one department owns: the common ones when it works on the
    tool or the line, then its own. A department in neither list owes no
    validation check (its rows, if an older catalog seeded some, stay on
    the record but no longer count; see ValidationService)."""
    name = department_name or ""
    items = ([_entry(i, False) for i in COMMON_CHECKS]
             if name in COMMON_DEPARTMENTS else [])
    have = {i["key"] for i in items}
    items += [_entry(i, True) for i in DEPARTMENT_CHECKS.get(name, [])
              if i[0] not in have]
    return items


def any_item_for(key: str) -> dict | None:
    """The label of a key from ANY catalog entry: a retired row (seeded by an
    older catalog) still reads with its words, not its key."""
    for item in COMMON_CHECKS:
        if item[0] == key:
            return _entry(item, False)
    for items in DEPARTMENT_CHECKS.values():
        for item in items:
            if item[0] == key:
                return _entry(item, True)
    return None


def keys_for(department_name: str | None) -> list[str]:
    return [i["key"] for i in items_for(department_name)]


def item_for(key: str, department_name: str | None) -> dict | None:
    for item in items_for(department_name):
        if item["key"] == key:
            return item
    return None


def label_for(key: str, department_name: str | None) -> str:
    item = item_for(key, department_name) or any_item_for(key)
    return item["label_en"] if item else key
