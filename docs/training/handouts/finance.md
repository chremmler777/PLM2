# ECR handout: Finance

One page for the session and the desk. The full chapter is in PLM2 under
**Training**, "Manual", chapter 08. Address: https://apps.ad.us.ktx.group/plm2/

**Your job:** own the cost sheet. Every hour, machine hour and sampling
trial on a change is priced from it.

## The cost sheet

Sidebar, Setup, "Cost sheet" (Setup shows for the admin and engineer
roles; everybody else opens the address ending in /cost-sheet). Four tabs:

| Tab | Holds |
|---|---|
| "Positions" | Hourly rate per department, position and plant; effective rate includes overhead |
| "Machines" | Hourly rate per machine class |
| "Sampling" | Price of one trial per machine class |
| "Overheads" | Personnel overhead, percent or per hour |

To change a rate: "New draft" (a copy of the latest published version), edit,
check "Changes vs previous", "Publish version" with "Valid from" (after the
latest published version's) and a note. Published versions are frozen.

## What your rates do

- **Costing** shows "Priced from cost sheet v{v} ({plant}, {cur})" and stores the rate and version on each line.
- **"No rate in the cost sheet"** on a line: it is not counted. Add the row and publish.
- **Offers** warn when costing used an older version than the current one.
- **P&L actuals** use the rate valid on the booking date. Prices on a change are shown to Sales, Project Management, the change lead and admins: unless you lead a change, Finance sees none of them. That is intended: you own the rates, not the offers.
- **Currency** comes from the plant. No conversion.

## Review and currencies

- **"Review every {n} months".** When due: "Cost sheet review due" banner on the cost sheet, a stale note in costing, and "Review the cost sheet" in "My Tasks".
- **"Plant currencies":** "Confirm" each one, or "Change" it if the location guessed wrong.

## Rules to remember

- **A rate takes effect from its date.** Publish before, not after.
- **Backdating** ("Publish backdated anyway"): time booked since then, and lines that had no rate, are priced with the new version. Lines already priced keep their rate.
- **Nothing to publish without a difference.** Publishing an unchanged draft is refused.
- **Rates are public, edits are Finance's.** Only Finance or an admin change the sheet.

## Your practical check

1. Publish a new Tool Engineer rate.
2. Price a line that has no rate.
3. Confirm the plant currencies.

Training is recorded, not blocking. Confirm your session on the Training
page ("Confirm your training"), then take the check.
