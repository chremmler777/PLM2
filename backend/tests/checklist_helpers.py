"""Build a fully answered checklist, the way the app now sends it."""
from app.services import assessment_checklist as checklist


def answered(dept_name, yes=(), remarks=None, choices=None, refs=True):
    """Every checklist key for the department, 'yes' for those in `yes`,
    'no' for the rest. ECR-solid §4 (ASSESSMENT_V2): a Yes says what
    changes and its evidence (remark), and with no Yes every No carries its
    reference; `refs=False` leaves both out (to test the refusal)."""
    remarks = remarks or {}
    choices = choices or {}
    out = []
    for item in checklist.items_for(dept_name):
        k = item["key"]
        e = {"key": k, "answer": "yes" if k in yes else "no", "impacted": k in yes}
        if k in remarks:
            e["remark"] = remarks[k]
        elif refs and k in yes:
            e["remark"] = "changes, see DRW-4471 rev C"
        if refs and k not in yes:
            e["ref"] = "checklist CL-12, DRW-4471"
        if k in choices:
            e["choice"] = choices[k]
        out.append(e)
    return out
