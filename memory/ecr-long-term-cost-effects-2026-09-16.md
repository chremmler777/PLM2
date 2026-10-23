---
name: ecr-long-term-cost-effects
description: ECR costing must capture long-term per-piece effects on article price, not just one-off action costs (noted 2026-09-16)
metadata:
  type: project
---

The ECR costing/assessment needs a second cost dimension besides the one-off
action (tool change, fixture, trial): the **long-term effect on the article
price**. Examples the user named on 2026-09-16:

- cycle time increase
- part weight increase (material cost)
- higher preventive-maintenance cycle on the tool
- higher scrap rate
- added refurbishment costs

These recur per piece or per year for the rest of the program and belong in
the quote to the customer, separate from the single-action cost lines in the
costing table (see [[ecr-costing-quoting-2026-08-12]] and
[[ecr-assessment-routing-2026-09-16]]).

**Why:** a change can be cheap to implement and expensive to live with; the
current costing table only sums actions.

**How to apply:** when the costing stage is next touched, model these as
recurring effects (delta per piece or per year, with a driver such as
seconds of cycle time or grams of material) that roll into the article price,
not as more one-off lines. Status: noted, not yet designed or built.

## Department cost sheet (added 2026-09-16)

The calculation base is a **public cost sheet per department**: the rates
(hourly rate, machine rate, overheads, etc.) every costing line is priced
from. Visible to everyone in the PLM, not hidden inside the costing table.
**Finance owns it and updates it yearly**; the sheet should carry a validity
year and the system should flag a stale sheet at the turn of the year.
Related: hours-as-money in [[ecr-costing-quoting-2026-08-12]] already prices
department hours; that rate should come from this sheet rather than a
hardcoded or per-line value.

## Update 2026-09-25
User confirmed: hourly costs need a **per-position cost sheet, updated regularly, Finance-controlled, separate module**. Specified as spec §15 in docs/superpowers/specs/2026-09-25-ecr-costing-to-close.md (branch feature/ecr-costing-to-close): versioned sheet (department x position x plant, valid_from), Finance/admin publish, stale banner, rate lookup by date, costing snapshots the version. Queued after the mother-plant side track.
