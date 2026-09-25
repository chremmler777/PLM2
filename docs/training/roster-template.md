# ECR training roster: template

Copy this file per session as `roster-<yyyy-mm-dd>.md` and fill one row per
person who attended. It is the paper side of the record. The app side is
**Training** in the sidebar, "Record attendance", filled from these rows by
somebody other than the trainee (four eyes: nobody records their own
attendance).

Who may record attendance in the app: an admin, or a member of Quality or
Project Manager (backend `MANAGE_DEPARTMENTS`).

## Session

| Field | Value |
|---|---|
| Date held | |
| Trainer (name as it should appear on the record) | |
| Location or call | |
| Roles covered | |
| Software version shown (next to the logo) | |
| Sign-off sheet scan (file name) | |

## Attendees

`Training role` is one of the six keys below. A person in two departments
that owe different roles gets one row per role.

| Name | Email | Department(s) | Training role | App user id | Recorded in app (date, by) | Practical check passed |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |

Rules for the rows:

- **App user id is required** before a row is recorded. Take it from the
  person picker on the Training page ("Record attendance"). Never guess it:
  a record against the wrong id says somebody was trained who was not.
- **Record only a role the person's own departments owe.** The app refuses
  anything else, by design.
- **The training date is the day the session was held**, not the day it is
  typed in. It cannot be in the future.
- **Attendance is not the sign-off.** Each person still takes the practical
  check on their own Training page. The last column is filled from the
  Training page or the CSV export once they pass.

## Training roles and the departments that owe them

| Training role | Label | Departments |
|---|---|---|
| `project_management` | Project Management | Project Manager |
| `sales` | Sales | Sales |
| `engineering` | Engineers | Development, Tool Engineer, Manufacturing Engineer, Process Engineer, APQP, Packaging Engineer |
| `scheduling` | Scheduling | Scheduling |
| `quality` | Quality | Quality |
| `finance` | Finance | Finance |

Source of truth: `backend/app/services/training.py`, `CURRICULA`. If a
department is added there, add it here.

## Not yet in the app

People who attended but cannot be recorded yet (no account, no department
membership). Record them here and move them up once their account exists.

| Name as signed | Department | Why not recorded | Who follows up |
|---|---|---|---|
| | | | |

## Export for the file

The Training page "Records" view exports the full history as CSV
(`ecr-training-<date>.csv`), superseded rows included. Attach that export to
this file when the roll-out is complete.
