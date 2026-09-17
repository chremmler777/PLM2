# Customer data index (E1 / 1) — design

Date: 2026-09-17
Status: approved in chat, pending spec review

## Problem

Parts for nominated projects (1994, 2077 backpanel) arrive as customer data
before anything is released. The current revision names (RFQ1, ENG1, IND1,
ECR1.1) encode an internal phase choice; they do not say whether the data is
binding. The customer, not us, decides that.

## Decisions

1. **The major number is always a customer-stated data state; the minor
   number is always our internal iteration on it.**
2. **Review data is E-prefixed, official data is a bare number.** The E-to-
   number jump happens only when the customer states the data is official.
   We record that statement; we never decide it.
3. **Counters never reset.** Nomination is a part phase, not a new counter.
4. **RFQ stays visible as a phase, not as a name prefix.**

## 1. Revision naming

| Shape | Meaning | Created by |
|---|---|---|
| `E1`, `E2`, ... | Review data as received from the customer | "customer data received" action, statement = review |
| `E1.1`, `E1.2` | Our internal proposal on top of E1 | "create proposal" (existing) |
| `1`, `2`, ... | Official data as released by the customer | "customer data received" action, statement = official |
| `1.1`, `1.2` | Our internal proposal (ECR work) on top of 1 | "create proposal" (existing), and the change engine on ECN release |

Numbering rule: the next major of a review revision is `E<n+1>`; the next
major of an official revision is `<n+1>`; the first official revision after
any number of E revisions is `1`. E and numeric counters are independent.

Promotion keeps the current behaviour: promoting proposal `1.2` creates the
next major (`2`) as a new record, marks `1.2` approved, rejects its sibling
proposals, and the changelog keeps the history. Promotion
requires the same customer evidence as a new major (index, statement, date),
because a promoted proposal is by definition a customer-adopted state.

### Model changes (`PartRevision`)

- `phase` enum becomes `review | official`. Existing values migrate:
  `rfq_phase`, `engineering` → `review`; `freeze`, `ecn` → `official`.
- New: `customer_index: str | None` — the customer's own index letter or
  number (e.g. `B` for 3CR.807.425.B).
- New: `customer_statement: str | None` — `review | official`, what the
  customer said about this data. Required on majors, null on minors.
- New: `customer_received_at: date | None` — date the data arrived.
- New: `source: str` — `customer | internal`. Majors are `customer`, minors
  are `internal`.
- New: `part_phase_at_receipt: str` — the part phase (see §2) when the
  revision was created, so lists can show "E2 (rfq)".
- `RevisionPhase`, `RevisionStatus`, `TestDataStatus` enums stay in place;
  only `RevisionPhase` members change. Statuses (draft, in_review, approved,
  frozen, ...) are untouched.

### Name migration

One Alembic migration, per part, in `created_at` order:

- `RFQn`, `ENGn` → `E1..Ek` in creation order (majors), their `.m` proposals
  follow their parent.
- `INDn` → `n`, `ECRn.m` → `n.m`.
- `active_revision_id` and all foreign keys are untouched (ids do not change).

Naming helpers in `part_service.py` (`get_next_major_version_name`,
`create_rfq_revision`, `transition_to_engineering`, `promote_to_major`) are
replaced by two: `next_major_name(part, statement)` and
`next_minor_name(parent)`. `transition_to_engineering` and the RFQ-specific
endpoints are removed; their callers route through "customer data received".

## 2. Part phase

New on `Part`:

- `lifecycle_phase: str` — `rfq | nominated | series`, default `rfq`.
- `nominated_at: date | None`, `sop_at: date | None`.

Transitions are manual (PM or admin): `rfq → nominated` sets `nominated_at`,
`nominated → series` sets `sop_at`. Both are logged in the changelog.
Existing parts default to `rfq`; 1994 and 2077 are set to `nominated` by hand
after deploy.

## 3. "Customer data received" action

New endpoint `POST /parts/{id}/revisions/customer-data` with body:

```
{ "statement": "review" | "official",
  "customer_index": "B",           # optional
  "received_at": "2026-09-17",
  "summary": "..." }
```

Creates the next major per §1, `source=customer`, `status=approved`
(customer data is not a draft on our side), `part_phase_at_receipt` from the
part. Guard: `official` on a part whose latest major is official is fine
(next number); `review` after an official major is rejected with 409, because
the customer cannot un-release data. Files are then uploaded to the new
revision through the existing file endpoint.

## 4. Frontend

- Revision list shows `E2 (rfq)` style badges: name, phase-at-receipt,
  customer index, "official" tag for numeric majors.
- "Customer data received" dialog on the part page: statement radio,
  customer index, date, summary.
- Part header shows lifecycle phase with a change button (PM/admin).
- RFQ/ENG specific buttons ("create RFQ revision", "award to engineering")
  go away.

## 5. Testing

- Naming: E1 → E1.1 → E2; E2 → 1 on official; 1 → 1.1 → 2 via promote;
  review-after-official rejected; counters independent.
- Migration: fixture with RFQ1, RFQ1.1, ENG1, IND1, ECR1.1 maps to E1, E1.1,
  E2, 1, 1.1.
- Change engine: ECN release still creates `n.m` on the impacted part.

## Out of scope

- Any copy of uploaded files outside the server store.
- Automatic parsing of the customer index from filenames.
