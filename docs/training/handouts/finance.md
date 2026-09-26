# ECR handout: Finance

For Finance. One page for the session and the desk; the full chapter is in PLM2 under **Training**, "Manual", chapter 08. Address: https://apps.ad.us.ktx.group/plm2/

**Your job:** check the cost sheet Sales keeps; you may change it too. Every hour, machine hour and sampling trial on a change is priced from it.

## The cost sheet

| Tab | Holds |
|---|---|
| "Rates" | One hourly rate per department and plant; an empty rate is no rate; the effective rate includes the overhead |
| "Machines" | Hourly rate per machine class (by tonnage); the presses from MachineDB ("Sync from MachineDB"), each with an optional rate of its own |
| "Sampling" | Price of one trial per machine class |
| "Overheads" | Personnel overhead, percent or per hour |

## Changing a rate

Sidebar, Setup, "Cost sheet" (Setup shows for the admin and engineer roles; everybody else opens the address ending in /cost-sheet). "New draft" (a copy of the latest published version), edit, check "Changes vs previous", "Publish version" with "Valid from" (after the latest published version's) and a note. Published versions are frozen. Sales, Finance and admins may edit.

## What the rates do

- **A change is priced with the rates valid on the day it was created.** Costing shows the version; each line stores its rate and version. A later version never changes an existing change.
- **"No rate in the cost sheet"** on a line: it is not counted. Fill the rate in a version valid on the change's creation date.
- **P&L actuals** use the rate valid on the booking date. Prices on a change are shown to Sales, Project Management, the change lead and admins: unless you lead a change, Finance sees none. That is intended: you check the rates, not the offers.
- **Currency** comes from the plant. Silao quotes in USD and pays in MXN: the version's USD/MXN exchange rate converts MXN rates and actual costs, and every conversion names its rate. Other currencies are not converted.

## Rules to remember

- **A rate takes effect from its date.** Publish before, not after.
- **Backdating** ("Publish backdated anyway"): changes created since then (lines without a rate) and time booked since then are priced with the new version. Lines already priced keep their rate.
- **Nothing to publish without a difference.** Publishing an unchanged draft is refused.
- **"Review every {n} months".** When due: "Cost sheet review due" on the cost sheet and "Review the cost sheet" in "My Tasks", for Sales and for you.
- **"Plant currencies":** "Confirm" each one, or "Change" it if the location guessed wrong.

## Your practical check

1. Answer a checklist row.

Coming, once the training copy can run them:

- Publish a new Tool Engineer rate.
- Price a line that has no rate.
- Confirm the plant currencies.

Training is recorded, not blocking. Confirm your session on the Training page ("Confirm your training"), then take the check.
