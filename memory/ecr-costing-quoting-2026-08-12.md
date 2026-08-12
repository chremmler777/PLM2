---
name: ecr-costing-quoting-2026-08-12
description: "Aug 12 session: costing positions/vendor quotes, quoting stage, process-flow chart in-app, gate semantics; what is open"
metadata:
  type: project
---

# ECR session 2026-08-12 — costing, quoting, process flow

Shipped to main (all suites green at push):
- **Assessment rework finished live**: scoped board (member sees own bucket
  only; acts-as drops admin AND change-lead privileges), typed risks 1–3
  (register-only, severity 3 on the quote basis), Change PPT / RFQ /
  customer-mail slots per bucket + change-level mail log, no accept step
  anywhere (submit stamps owner via task relationship), team wait banner,
  stage-scoped board/banner (Sales exempt).
- **Costing positions**: standing spent/estimated-time fields (kind-bound,
  create-on-first-save), external positions with vendor offers (shipping
  separate/included, lead-time units business/calendar, one favorite whose
  price AND lead time are the effective figures, vendor_quote uploads),
  hours valued at the department rate into one_time_internal (unrated_hours
  flagged, never invented), nothing-impacted departments skip the queue.
- **Quoting stage**: costing → quoting → quoted, Sales-gated, create_quote
  task, wrap-up + timeline placeholder on commercial tab.
- **Process Flow page** (/process-map, sidebar link): audit-grade hand-built
  SVG — diamonds, hard gates, question/deviation/recall/on-hold/escalation
  loops, guard-condition edge labels, artifact gutter, task annotations,
  deadline rail, cross-flow arrows; full-window mode (solid bg, Escape);
  verified with Playwright screenshots (NaN-key stacking, nested scrollbox,
  gate overflow, recall-through-box all found only by looking).

**Gate semantics (blocking_complete)**: first stage always gates; later
stages gate only once the engine activated them (multi-stage assessment
templates still block; dormant summation/customer rows never do).

Open / next (rule book = docs/ECR_PROCESS_MAP.md build order):
1. Weight estimate at costing (Tool Engineer) → validated at validation →
   quote delta to Sales.
2. Negotiation loop at quoted (entries, final result, go-ahead).
3. Scheduling block (bank-build plan, scrap decision + scrap quote,
   publish-to-customer stamp).
4. Implementation tracking (time booking, 2×/week reports, at-risk flag,
   Sales escalation records).
5. Validation checks (per-department, weight validation, revision bump,
   actuals P&L).
6. Sales' binding vendor choice at quoting.
7. USER QUESTION OPEN: does no-accept also apply to generic workflow tasks
   (part-revision checks) on My Tasks? Button still there.

Lessons: [[working-agreements]] lean mode held (two Opus executors, targeted
tests, one batched suite). Screenshots beat test assertions for SVG layout.
The user's messages are the rule book — audit them verbatim before claiming
"under control"; two details ("Sales chooses later", "we order them later")
were only recovered on re-read.
