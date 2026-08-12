---
name: morning-summary-2026-08-13
description: "Overnight run result: rule-book build order 1-6 complete on feature/ecr-target-state, verified end to end; parked business calls listed"
metadata:
  type: project
---

# Morning summary — overnight run (branch `feature/ecr-target-state`, 10 commits, NOT pushed)

Good morning. The rule book's build order is COMPLETE and verified. Main is
untouched; everything sits on `feature/ecr-target-state` awaiting your review.

## Shipped tonight (each traced to its rule-book stage)

1. **Weight estimate at costing** (`f06767ba`) — Tool-Engineer-gated field,
   null withdraws with changelog, flagged as estimate in Sales' wrap-up.
2. **Negotiation loop at quoted** (`80cfd99b`) — rounds (channel, note,
   counter price), ONE final result (demote-siblings), negotiated price on
   the detail, card on the commercial tab; go-ahead stays with acceptance.
3. **Scheduling block** (`d36cee45`) — running-change vs planned-scrap
   (scrap REQUIRES the scrap quote: the customer bears the cost),
   Scheduling/PM/lead decide, ONLY Sales publishes; wait states + tasks,
   no hard gate.
4. **No-accept everywhere** (`0f292684`) — your ruling: Accept gone from
   workflow tasks and WorkflowProgress too; completing stamps the owner.
5. **Implementation tracking** (`50f415fe`) — time booking, 84h report
   cadence (silence = visibly owing), at-risk → Sales escalation
   (customer/internal) with resolution, hours laid for the actuals.
6. **Validation checks** (`360a3631`) — per-department catalog (sampled /
   measured / cycle time in seconds; Tool Engineer weight in grams;
   Development revision bump), weight delta → Sales update-quote task with
   acknowledge, released refuses failed/open checks (vacuous for legacy),
   escalation loop back with professional wording; actuals P&L on the
   summation (booked hours × rates, scrap + weight extras vs plan).
7. **Vendor decision** (`46a38596`) — favorite = visible recommendation,
   Sales decides at quoting, divergence REQUIRES a reason and is marked;
   summation quotes the chosen offer, department keeps its own figures.
8. **Costing-gate root fix** (`3050be71`) — found by the E2E walk: engine
   stage-2 activation re-blocked costing after all verdicts (your original
   bug, round two). Now only assessment work gates: first stage +
   deviation-added rows.
9. **Live-render fixes** (`1d4289a6`) — impl-state payload shape crash,
   session-expiry hardening, and the dev proxy: `backend` on the shared
   docker network is the RFQ stack (!), so localhost:5173 could never reach
   the plm2 API before; now proxied by container name.

## Verification (all evidence, no claims)

- Backend full suite: **663 passed** (373 + 290, chunked).
- Frontend full suite: **541 passed** (+ the new tests since).
- **End-to-end walk on the live app** (scratchpad/e2e_walk.py, admin +
  acts-as): captured → … → in_validation, **54/55 steps green** — including
  severity-3 risk not blocking, divergent vendor choice refused without
  reason, 4-eyes sign-offs, scrap-quote enforcement, at-risk → escalate →
  resolve, weight 415 g vs 400 g delta + Sales ack, released refused while
  checks open then validation-clear. The single non-pass is the PRE-EXISTING
  ready-to-go gate (ECN revision check workflow not performed by the walk) —
  correct behavior. Walk change: **CR-2026-0010 (id 16), left in
  in_validation for you to poke**; duplicate iterations cancelled.
- Playwright screenshots verified the implementation tab end state (stepper
  badges incl. Customer, bank-build card, tracking, validation panel).

## Parked business calls — YOUR decisions, with my recommendation

1. **PM booking time for other departments?** Currently own-department only
   (PM may delete, not create). Rec: keep as is — time is a personal claim.
2. **84h as "at least 2×/week"** — never trips a Mon/Thu reporter. Rec: keep;
   make configurable only when somebody actually complains.
3. **A change-wide escalation (no report link) silences every department's
   at-risk flag.** Rec: acceptable; add per-department escalations only if
   Sales asks.
4. **Should open escalations gate in_implementation → in_validation?**
   Currently they don't. Rec: leave open; the register shows them.
5. **Out-of-assumption cycle time**: recorded and compared, does not block
   the pass. Rec: keep informational; the check's pass/fail is the human's.
6. **Cycle time is compared against the costing's lifecycle DELTA (min/part
   added)** — costing never states an absolute cycle time. If you want
   absolute-vs-absolute, that's a new costing field.
7. **Weight delta carries no euro amount** — pricing a gram is negotiation.
8. **Sales' vendor choice moves the MONEY, not the lead time** (dates still
   follow the department favorite). Flag if the choice should move both.
9. **No-favorite positions**: choosing needs no reason (nothing to diverge
   from).

## Housekeeping notes

- Live dev DB is at migration **064**; all migrations additive.
- localhost:5173 now works end to end (dev proxy); the corporate proxy path
  is untouched.
- API smoke access: mint a hub-style JWT inside the backend container
  (jwt_secret + roles[{name: plm2_Admin, system}]) — see e2e_walk.py.
- The auth bridge auto-created user `admin-1-1` during browser testing
  (username collision on re-bridge) — harmless, delete at will.
