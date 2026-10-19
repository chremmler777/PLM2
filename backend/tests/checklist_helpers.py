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


async def details_in(session, dept_id, **kw):
    """{"impacts": ...} for a department by id, answered in full (all No
    with references unless `yes` says otherwise): what a submit now needs
    under ASSESSMENT_V2 (click-through R38: no bare verdict)."""
    from app.models.workflow import Department
    dept = await session.get(Department, dept_id)
    return {"impacts": answered(dept.name if dept else None, **kw)}


async def details_for(session_factory, dept_id, **kw):
    async with session_factory() as s:
        return await details_in(s, dept_id, **kw)


async def checklist_details(client, dept_id, **kw):
    """The same over HTTP (the served checklist), for tests that only hold
    the client: every row No with its reference."""
    from tests.conftest import login
    auth = await login(client, "admin@test.io")
    res = await client.get("/api/v1/changes/reference/assessment-checklist",
                           params={"department_id": dept_id}, headers=auth)
    assert res.status_code == 200, res.text
    yes = set(kw.get("yes", ()))
    out = []
    for item in res.json():
        k = item["key"]
        e = {"key": k, "answer": "yes" if k in yes else "no", "impacted": k in yes}
        if k in yes:
            e["remark"] = "changes, see DRW-4471 rev C"
        else:
            e["ref"] = "checklist CL-12, DRW-4471"
        out.append(e)
    return {"impacts": out}
