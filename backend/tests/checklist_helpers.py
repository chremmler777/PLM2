"""Build a fully answered checklist, the way the app now sends it."""
from app.services import assessment_checklist as checklist


def answered(dept_name, yes=(), remarks=None, choices=None):
    """Every checklist key for the department, 'yes' for those in `yes`,
    'no' for the rest."""
    remarks = remarks or {}
    choices = choices or {}
    out = []
    for item in checklist.items_for(dept_name):
        k = item["key"]
        e = {"key": k, "answer": "yes" if k in yes else "no", "impacted": k in yes}
        if k in remarks:
            e["remark"] = remarks[k]
        if k in choices:
            e["choice"] = choices[k]
        out.append(e)
    return out
