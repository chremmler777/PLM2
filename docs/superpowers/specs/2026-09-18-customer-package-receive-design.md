# Customer package receive and chosen E number — design

Date: 2026-09-18
Status: approved in chat, pending spec review
Builds on: `2026-09-17-customer-data-index-design.md`

## Problem

Customer data arrives as a package: the assembly file plus one file per
single part. Not every part changes with every delivery. Today each part
needs its own "+ Customer data" click, the E number is always auto-assigned
(a part whose first saved delivery is the customer's second one still becomes
E1), and the customer index is visible only on the timeline and part header.
Uploading the unchanged parts again duplicates data that has not changed.

## Decisions

1. **If the data did not change, the E does not change.** Sameness is decided
   by the customer index, entered per file or read from the filename, with a
   manual override. No hash comparison in the decision.
2. **The E number is yours to choose**, as long as it is higher than every
   existing major of the same kind. Gaps are allowed; a part may start at E2.
3. **No change process for customer data**, review or official. Existing
   rules stay: review after official is refused.
4. **The customer index is shown wherever a revision name is shown.**

## 1. Chosen major number

`receive_customer_data` gets an optional `major: int`. When absent, behaviour
is unchanged (highest + 1). When present:

- must be `>` the highest existing major of the same kind (E or bare), else
  `409` with the highest existing name in the message;
- the name is `E<major>` or `<major>` per statement.

`next_major_name(existing, statement, requested=None)` in
`revision_naming.py` carries the rule. `CustomerDataDialog` gets a
"Revision" field prefilled with the next free number, editable.

## 2. Package receive

### Flow

1. On an assembly (project page or part page): **+ Customer package**.
2. Dialog step 1: statement (review/official), received date, package
   customer index (optional default for every row), files (multi-select or
   drop, same extension rules as single upload).
3. `POST /parts/{assembly_id}/revisions/customer-package/preview` (multipart,
   files not yet stored) returns one row per file:
   - `filename`
   - `part_id` / `part_number` / `customer_part_number` — matched, or null
   - `customer_index` — from the filename if parsable, else the package index
   - `current_revision` — the part's active revision name and its
     customer index
   - `action` — `new_major | unchanged | unmatched`
   - `suggested_name` — the next major name for `new_major` rows
4. Dialog step 2: the table. Per row the user can change the part (dropdown
   of the assembly's BOM parts plus the assembly itself, then any project
   part), the customer index, the action, and the major number. Rows left
   `unmatched` are skipped.
5. `POST /parts/{assembly_id}/revisions/customer-package` (multipart, files
   plus the confirmed rows as JSON) does, in one transaction:
   - for every `new_major` row: `receive_customer_data` on that part with the
     row's statement, date, index and major, then the file upload path
     already used by `upload_revision_file` (same storage, hash, glTF
     conversion);
   - for every `unchanged` row: nothing stored; a changelog line on the part
     "Customer package <date>: <filename> unchanged, kept <rev>".
   - the assembly itself is a row like any other; its new major copies the
     BOM from the previous major as today, so lines keep pointing at the
     children's active revisions. Children that got a new major are already
     active there.
   - returns `{created: [...], kept: [...], skipped: [...]}`.

Preview and confirm share one service function so the confirm re-derives
nothing; the confirm trusts the rows.

### Matching a file to a part

In order, first hit wins, over the assembly and every part of its BOM tree
(all levels), then the rest of the project:

1. `customer_part_number` without dots, case-insensitive, contained in the
   filename with dots, spaces, hyphens and underscores removed;
2. our `part_number` the same way.

Customer index from the filename: when the filename contains the matched
customer part number followed by a single index token (`.B`, `_B`, `-B`,
`B`), that token is the row's index. Otherwise the package index applies.

### Deciding `action`

- no part matched → `unmatched`
- part has an active revision whose `customer_index` equals the row's index
  (case-insensitive, trimmed, both non-empty) → `unchanged`
- otherwise → `new_major`

A row's index may be empty. Then the decision cannot be made and the row is
`new_major` with a warning "no index, will create"; the user can switch it.

### Errors

- Review statement on a part that already has official data → that row is
  reported as `error` in the preview with the reason, and the confirm refuses
  the whole package while any `error` row is left in.
- Unsupported extension → row `error`.
- Chosen major not above the existing one → row `error`.
- Nothing is stored on any failure; single transaction, files written to
  disk only after the DB flush succeeds, deleted on rollback.

## 3. Customer index everywhere

One `RevisionBadge` component: `E2 · B` when the revision has a customer
index, `E2` otherwise. Used in: revision timeline, part header, revision
dropdown on the project page, BOM tree nodes, assemblies list, project items
table, change forms that show a revision name. The API responses that feed
these lists carry `customer_index` next to `revision_name` where they do not
already (bom-tree, assemblies, project items).

## 4. Out of scope

- Pinning a child revision on a BOM line.
- Hash-based sameness. The hash stays stored on the file for later use.
- The U drive mirror.

## 5. Testing

- `revision_naming`: requested major above/at/below the existing one, first
  major with a gap, per kind.
- Package service: matching by customer number, by our number, index parsed
  from filename, package index fallback, `unchanged` when index equal,
  `new_major` when different or empty, assembly row copies BOM, rollback on
  an `error` row.
- Frontend: badge with and without index; package dialog table renders
  actions and lets a row's part and action change.
