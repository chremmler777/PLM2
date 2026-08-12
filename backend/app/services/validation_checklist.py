"""The validation checklist: what each implementing department must confirm.

Config, not data — the same call assessment_checklist.py makes. The checks are
the same for every change and every project ("was the tool sampled?", "what
cycle time did you measure?"), so they live in code where a diff shows the
change, rather than in rows somebody can quietly edit for one department.

Every implementing department answers the COMMON checks. Two departments carry
one extra each, and both extras are the reason stage 9 exists at all:

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
    ("cycle_time", "Zykluszeit gemessen", "Measured cycle time", True,
     "seconds"),
]

# Department name -> its extra checks, same tuple shape.
DEPARTMENT_CHECKS = {
    "Tool Engineer": [
        ("weight", "Teilegewicht validiert", "Part weight validated", True,
         "grams"),
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
# minutes-per-part the change was priced on).
CYCLE_TIME_KEY = "cycle_time"


def _entry(item: tuple, extra: bool) -> dict:
    key, label_de, label_en, expects_value, unit = item
    return {"key": key, "label_de": label_de, "label_en": label_en,
            "expects_value": expects_value, "unit": unit, "extra": extra}


def items_for(department_name: str | None) -> list[dict]:
    """The checks one department owns: the common ones, then its own.

    An unknown department still gets the common set — a department nobody
    thought to configure sampled and measured its work like everyone else.
    """
    items = [_entry(i, False) for i in COMMON_CHECKS]
    items += [_entry(i, True)
              for i in DEPARTMENT_CHECKS.get(department_name or "", [])]
    return items


def keys_for(department_name: str | None) -> list[str]:
    return [i["key"] for i in items_for(department_name)]


def item_for(key: str, department_name: str | None) -> dict | None:
    for item in items_for(department_name):
        if item["key"] == key:
            return item
    return None


def label_for(key: str, department_name: str | None) -> str:
    item = item_for(key, department_name)
    return item["label_en"] if item else key
