---
name: ecr-buildout-2026-08-11
description: "2026-08-11 marathon: two-phase deadlines, capture/scoping/assessment/costing rework all shipped; what's open and where the truth lives"
metadata:
  type: project
---

# ECR buildout status (as of 2026-08-11, end of session)

**The single source of truth for the flow is `docs/CHANGE_MANAGEMENT_FLOW.md`** —
every rule shipped this session is recorded there with its enforcing code. The
user wants a **flowchart generated from that doc when ECR is done** (mermaid in
the doc + artifact).

## Shipped and live (main pushed, live Postgres at alembic 055)

- Two-phase deadlines (quote-by/release-by), pushback with reason, phase-aware
  everything. Capture: Sales/PM-only start, kickoff gate (description +
  attachment + date), tabs unlock per phase. Scoping: Now/History layout,
  question container cards (answer=Sales comment, settle=asking side/PM),
  wait-state banner theme, needs-info and rejection closure loops (letter →
  confirmed send → closed). Assessment: per-department buckets from the
  meeting-authoritative routing (physical part = Development, Tool Engineer,
  Manufacturing Engineer, APQP, Packaging), domain objects via two-hop serves
  links, 13-item impact checklist + extras (config endpoint), evidence/RFQ
  attachments, risk framing (department concerns = per-change risk register,
  mitigation proposals need doc + confirmation). Costing: workbook-mask matrix
  (activity × plant, internal/external, lifecycle ± min/part), lead time per
  department (roll-up = max), summation + quote basis (Sales prices manually),
  visibility: departments see only their own figures, PM/Sales/lead/admin all.
  My Tasks drives every hop (kickoff, scoping wrap-up, impact confirm, obtain
  info, close question, costing input, customer response, send rejection) +
  sidebar counter. Acts-as role switch (backend-enforced, admin bypass dropped
  while acting). ECR roles cleaned (9 + Quality; catalogs remapped).

## Open items / decisions parked

- **Internal changes blocked at creation** (endpoint-only; service capable).
  Omitted `customer_relevant` in raw API still defaults internal — sealed only
  in UI. Revisit when internal volume comes (doc has the note).
- **Bank build**: post-acceptance implementation planning, explicitly not in
  costing.
- **Process responsibles per project**: planned, not built (doc note; pickers
  preselect nothing except Development for multi-role users).
- **APQP documents as assessment objects**: no controlled-document entity
  exists; APQP gets gauges only. User may want attachments counted later.
- **Duplicate routing templates** named "ECM Assessment" exist in live DB
  (rename leftovers) — cleanup pass worth queueing.
- **Piece-price entry at quoting**: departments give min/part deltas; whether
  quoting UI needs a dedicated piece-price-delta field is unverified.
- `test_costing_contract.py::seed_admin` hardcodes raiser id 1 — brittle.
- Old test change CR-2026-0002 carries mixed old/new routing rows (UI dedupes;
  recall→proceed cleans fully). Change data was wiped once this session
  (backup: /tmp/plm-before-change-wipe-20260811.dump in db container).

## Hard-won operational lessons (also in [[live-db-is-postgres-2026-08-06]])

- Migrations MUST be dialect-neutral (sa.true()/sa.false(), Core expressions);
  SQLite tests don't catch Postgres boolean breakage — 041 took prod down.
- Hot reload swaps ORM code without running migrations → apply explicitly:
  `docker exec claude-plm2-backend-1 alembic upgrade head` after every
  migration commit, verify `alembic current`.
- Frontend = vite HMR in docker, no rebuild ever needed; backend suite ~3s/test
  → bucket testing (implement all, one targeted run at end), full suite only
  as pre-ship gate.

## Working setup that produced ~40 commits today

Two persistent Opus subagents (backend/frontend split, disjoint files,
frontend never runs git — supervisor commits/pushes), user live-tests and
fires findings, supervisor translates each into scoped dispatches with exact
contracts. See [[working-agreements]] for lean mode.
