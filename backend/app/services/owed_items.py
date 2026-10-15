"""The computed My Tasks rows under the one escalation rule (ECR-solid spec
§0, C20/C27), read per change and independent of who looks:

- costing_input: a department that called the change feasible still owes
  its finalized costing (from its own submit on);
- sign_off: the PM or Quality signature for the latest offer, where the
  gate is live (quoted after the customer's yes, in_validation);
- internal_approval: an internal change's finalized costing waits on the
  engineering approver (HARD #8);
- deviation_decision: an override waits on its deciders.

Each item has a due date by the task rule (due_rules.task_due from
due_rules.start_of), the people who owe it (reminded on the due date) and
the words for the lead's "Overdue" group and the digests. The sweep
(notification_sweep), the lead's group (ChangeService.lead_escalations)
and the overdue digest read them from here, so the three agree with each
other and with the rows' Late chip (same start, same due, same lateness).

Under ASSESSMENT_V2 only (the one rule); with it off nothing is computed."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeChangelog
from app.models.workflow import Department
from app.services import cm_switches, due_rules

#: The computed kinds the one escalation rule watches.
WATCHED_KINDS = frozenset({"costing_input", "sign_off", "internal_approval",
                           "deviation_decision"})


async def owed_items(session: AsyncSession, changes: list,
                     now: Optional[datetime] = None, *,
                     with_owners: bool = True) -> list[dict]:
    """Every watched computed item on these changes: {change, kind, key,
    label, owner, owner_ids, due}. `owner` names who owes it in words,
    `owner_ids` the people reminded on the due date (read only
    with_owners: the lead's group and the digest need the words only)."""
    if not cm_switches.on("ASSESSMENT_V2") or not changes:
        return []
    from app.services import mother_plants as mp
    from app.services.change_people import department_members_of_change_org
    from app.services.change_service import ChangeService
    now = now or datetime.utcnow()
    ids = [c.id for c in changes]
    entered = dict((await session.execute(
        select(ChangeChangelog.change_id, func.max(ChangeChangelog.performed_at))
        .where(ChangeChangelog.change_id.in_(ids),
               ChangeChangelog.field_name == "status")
        .group_by(ChangeChangelog.change_id))).all())
    depts = dict((await session.execute(
        select(Department.name, Department.id).where(Department.is_active.is_(True)))).all())
    names = {i: n for n, i in depts.items()}
    out: list[dict] = []

    async def add(c, kind: str, key: str, label: str, owner: str, owners,
                  own: Optional[datetime], until: Optional[datetime] = None) -> None:
        """owners: a coroutine function for the owner ids, run only
        with_owners. until: a supplier wait's expected-by (spec §0: it
        pauses the late clock, the item is due then at the earliest)."""
        start = due_rules.start_of(kind, own, entered.get(c.id), c.created_at, now)
        due = due_rules.task_due(start, c, kind)
        out.append({"change": c, "kind": kind, "key": key, "label": label,
                    "owner": owner,
                    "owner_ids": sorted(set(await owners())) if with_owners else [],
                    "due": max(due, until) if until is not None else due})

    from app.services import supplier_wait_service as _sw
    waits = await _sw.open_by_department(
        session, [c.id for c in changes if c.status in ("in_assessment", "costing")],
        "costing")

    release_rule = cm_switches.on("RELEASE_V2")
    bound = cm_switches.on("COMMERCIAL_V2")
    for c in changes:
        # costing a department owes (same list as the costing_input rows)
        for did in await ChangeService.costing_pending_department_ids(session, c):
            submitted = [a.submitted_at for a in c.assessments
                         if a.department_id == did and a.submitted_at]
            dept = names.get(did, "A department")
            wait = waits.get((c.id, did))
            await add(c, "costing_input", f"chg:{c.id}:costing:{did}",
                      f"Costing input: {dept}", dept,
                      lambda c=c, did=did: department_members_of_change_org(
                          session, c, [did]),
                      max(submitted, default=None),
                      datetime.combine(wait.expected_by, datetime.min.time())
                      if wait else None)

        # sign-offs where the gate is live (the sign_off rows' rule)
        signable = (c.customer_relevant and not mp.is_mother_plant(c)
                    and getattr(c, "origin", None) != "engineering_review"
                    and ((c.status == "quoted" and c.customer_response == "accepted")
                         or (release_rule and c.status == "in_validation")))
        if signable:
            if bound or c.status != "quoted":
                sides, latest = await ChangeService.signoff_sides_missing(session, c)
            else:
                sides, latest = [s for s, by in (("pm", c.pm_signed_by),
                                                 ("quality", c.quality_signed_by))
                                 if by is None], None
            for side in sides:
                dept = "Project Manager" if side == "pm" else "Quality"
                other = c.quality_signed_by if side == "pm" else c.pm_signed_by

                async def who(c=c, dept=dept, other=other):
                    # 4-eyes: never the other side's signer
                    return [u for u in await department_members_of_change_org(
                        session, c, [depts[dept]] if dept in depts else [])
                        if u != other]
                version = latest.version if latest is not None else 0
                own = max((t for t in (c.customer_response_at,
                                       getattr(latest, "sent_at", None)) if t),
                          default=None)
                await add(c, "sign_off", f"chg:{c.id}:sign:{side}:{version}",
                          f"{'PM' if side == 'pm' else 'Quality'} sign-off",
                          "Project Management" if side == "pm" else "Quality", who, own)

        # the internal approval (the internal_approval rows' rule)
        if (not c.customer_relevant and c.status in ("costing", "quoted")
                and c.internal_approved_at is None
                and not (c.status == "costing"
                         and await ChangeService.costing_pending_department_ids(
                             session, c))):
            await add(c, "internal_approval", f"chg:{c.id}:internal_approval",
                      "Internal cost approval",
                      await ChangeService.internal_approver_text(session, c),
                      lambda c=c: ChangeService.internal_approver_ids(session, c),
                      ChangeService._last_costing_finalized(c))

        # overrides waiting on their deciders
        for dev in c.transition_deviations:
            if dev.status != "pending":
                continue
            await add(c, "deviation_decision", f"dev:{dev.id}",
                      ChangeService.deviation_label(dev), "its deciders",
                      lambda c=c, dev=dev: ChangeService.override_decider_ids(
                          session, c, dev, dev.proposed_by),
                      dev.proposed_at)
    return out


def late_items(items: list[dict], now: datetime) -> list[dict]:
    """The items past due + 1 working day (the sweep's own test)."""
    from app.services.notification_sweep import escalated
    return [i for i in items if escalated(i["due"], now)]
