# PLM2 data route: from Brose / to Brose (design)

Date: 2026-10-19 · Status: draft for Christoph's review · Supersedes the open plan in
`memory/revision-update-simplify-2026-10-10.md`

## Why

Nobody knows which button to use. Six entry points create versions today: "+" in the
version panel, "+ Customer data" (Documents tab and part page), "+ Customer package",
the upload dialog's "Next customer data → E2", "+ Proposal" and "Customer adopted"
on the part page. A misclick on "+" on 2026-10-19 created an empty E2.1 on
206.886.197 and mailed the 1994 list. Brose also sends data in several states:
official releases, feasibility drafts (DRAFT_MOD), and data without a drawing. The
current screens can't express that difference.

Success means:
- Anyone filing data picks one of two buttons, answers at most two questions, and
  the right version appears.
- Nothing is created without files and a reason.
- The tree always tells whether a version is confirmed.

## The model

| Tree element | Meaning | Created by |
|---|---|---|
| Folder **E1 · 003, E2 · 005** (later 1, 2 at design freeze) | **Confirmed** data: an official Brose release, or something Brose confirmed | ⬇ "Data from Brose" answered "official", or **Confirm** on an x.x |
| Sub-folder **E1.1, E1.2 …** | **Not confirmed**: needs Brose's confirmation or is our own check | ⬇ "Data from Brose" answered "feasibility / draft", or ⬆ "Data to Brose" |

Every x.x carries a **direction**:
- ⬇ **from Brose**: feasibility / draft / for-information data, e.g. DRAFT_MOD of 2026-05-29.
- ⬆ **to Brose**: our or the toolmaker's modified data, sent and awaiting confirmation, e.g. the FZ E1.1s of 10/15 and 10/19.
- ● **internal**: our own what-if check, never sent.

An x.x ends one of two ways:
- **Confirm**: Brose released or adopted it. It becomes the next folder (E2) and its files go with it.
- **Close**: rejected, replaced or dropped. It stays greyed out, with a reason.

The E-vs-official numbering rule from 2026-10-10 stays: everything is E in the
engineering/DFM phase, and official numbers 1, 2 start at tool start / design freeze.
The project phase decides that, not Brose's wording.

## Screens

### 1. Two buttons on top of the Versions panel

```
┌ Versions ──────────────── « ┐
│ [⬇ Data from Brose] [⬆ Data to Brose] │
│ 📁 E2 · 005  active  …                │
```

These are the only places versions are created. The "+" on a version row is removed.

### 2. ⬇ Data from Brose (one dialog)

1. **Drop files.** PLM2 reads part number, index, document type (PCA/DMU/DRW/KPR)
   and date from the names, using today's `customer_naming` parser.
2. **Question 1: "Is this official / confirmed by Brose?"** PLM2 pre-fills a guess:
   B-RELEASE in the name means official, DRAFT / DRAFT_MOD means feasibility.
   - **Official, new index 005** → new folder E2 · 005, waiting for triage (as today), mail.
   - **Official, more files for E2 · 005** (index matches an existing folder, e.g. the
     drawing arrives later) → files are added to E2 · 005. Mail: "files added".
   - **Feasibility / draft** → E1.x ⬇ under the current folder, "awaiting
     confirmation", mail.
3. **Question 2, only if it can't be read from the files:** received date and channel
   (GlobalX / OpenDXM / mail), plus a one-line note. It goes into the summary.

The same dialog also takes several parts at once (today's "+ Customer package"). A row
per part shows what PLM2 will do. The separate package dialog is removed.

### 3. ⬆ Data to Brose (one dialog)

1. Drop the files.
2. **Based on:** the folder it modifies (default: the active one).
3. **Direction:** sent to Brose (default) / internal only.
4. **Reason, required:** e.g. "FZ per DFM: sharp steel at slide entry … sent via
   GlobalX 19.10. 08:12, requested by Dale".
5. Result: E1.x ⬆ "awaiting Brose" (or ● "internal check"), mail for "sent" only.

### 4. Confirm / Close on an x.x (⋯ menu of the row)

- **Confirm**: asks for Brose's index (e.g. 005) and the date. It creates the next
  folder (E2 · 005) from the x.x, with the **files carried over** (today's promote
  copies only the BOM) and the x.x marked "confirmed → E2". Sibling x.x stay open;
  they are not auto-rejected the way they are today, because a feasibility E1.2 can
  coexist with our E1.1. Goes through triage like any new folder. Mail.
- If Brose later sends their own official files for that index, use ⬇ "Data from Brose"
  → "more files for E2 · 005".
- **Close**: a reason is required, e.g. "replaced by E2 · 005" or "Brose rejected 21.10.".
  Greyed out. Mail.

### 5. Tree markers

The x.x rows show the direction icon and a state:

| Marker | Label |
|---|---|
| ⬇ | awaiting confirmation |
| ⬆ | awaiting Brose |
| ● | internal check |
| (any) | confirmed → E2 |
| (any) | closed: \<reason\> |

The file completeness chips stay as built.

## What is removed or merged

| Today | Becomes |
|---|---|
| "+" on a version (VersionNav) | removed |
| "+ Customer data" (Documents, part page) | ⬇ Data from Brose |
| "+ Customer package" | ⬇ Data from Brose (multi-part) |
| Upload dialog "Next customer data → E2" | removed. The upload dialog only adds files to the selected version; if the names show a new index, it says "this looks like new Brose data" and opens ⬇ |
| "+ Proposal" (part page timeline) | ⬆ Data to Brose |
| "Customer adopted" (part page) | Confirm |
| Reject / Unreject on proposals | Close / Reopen |

The part page's RevisionTimeline shows the same tree, read-only, with a link to the
Documents tab. There's one place to act.

## Data

- `part_revisions.direction`: nullable text, one of `from_customer`,
  `to_customer`, `internal`. Set on minors only; null on majors.
- `part_revisions.close_reason`: text, nullable.
- Backfill of 1994's existing minors:
  - E1.1 on 206.886.197 (DRAFT_MOD investigation) → `from_customer`
  - the five FZ E1.1s → `to_customer`
  - any others → `internal`; I'll list them for your check before running.
- **Migration number:** the ECR branch (feature/ecr-solid) holds the next numbers
  (117+). This design takes the next free number after coordinating with that session.
  Not before.
- Confirm reuses `promote_revision` with two changes: files are copied (the stored
  file is shared, a new row points at it) and siblings are not auto-rejected.
- Mail: unchanged event list. "Close" maps to the existing `rejected` event and
  "Confirm" to `promoted`. Adding files to an already-announced version mails
  "files added" as today, and the dialog has a "don't mail" option (used for the
  Belt exit STEP today).

## Error handling

- Dropping files with no recognisable part number or index: the dialog asks for the
  part, the index and official or not. Nothing is guessed silently.
- A new index while another one still waits for triage: the dialog says so and offers
  "add to pending E2". The silent supersede from 2026-10-10 is no longer possible.
- Confirm on an x.x whose base folder is no longer active: allowed, with a warning
  that names the active folder.

## Testing

- Backend:
  - service tests for the three dialog outcomes, Confirm (files carried, siblings
    untouched), Close (reason required), and the direction backfill.
  - API tests for the new endpoints and the removed paths.
- Frontend:
  - dialog tests for the guess (B-RELEASE / DRAFT_MOD), each route, and multi-part rows.
  - VersionNav tests for markers and the removed "+".
- The 1994 data on prod is the acceptance check: every part's tree reads correctly,
  with direction markers, before and after the backfill.

## Out of scope

- Role-based rights for who may Confirm (later, with role-based mail).
- Worksheet completeness column (separate follow-up).
- Changing how triage works.
