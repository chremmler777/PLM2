---
name: sep-forms-engine
description: SEP forms engine (in-app replacements for F-DVS-CORP templates) — six-form batch + engine shipped on feature/sep-forms-engine 2026-09-04, spec updated with implementation decisions
metadata:
  type: project
---

State on 2026-09-04: implementation (tasks 1-10) complete on branch
`feature/sep-forms-engine`, not merged to `main`, not pushed. Spec at
docs/superpowers/specs/2026-09-03-sep-forms-engine-design.md now reflects
what was actually built (task 11 reconciled it against the code).

**What exists:**
- Backend engine: `backend/app/forms/` — `loader.py` (definition loader, run
  at startup and via `scripts/load_form_definitions.py`), `expr.py`/`compute.py`
  (tiny expression language for computed fields), `prefill.py`, `validate.py`,
  `service.py` (create/save/submit/reopen/sign, the SEP-item flip logic),
  `risks.py` (`copy_sep_risks_to_forms`, the legacy risk migration), `pdf.py`
  (reportlab export, all text XML-escaped). Router
  `backend/app/api/v1/timing/forms.py`, prefix `/v1/forms`. Models in
  `backend/app/models/forms.py` (`FormDefinition`, `FormInstance`, `FormEvent`).
- Six form definitions live under `backend/app/data/forms/*.json`:
  risk_assessment, sales_pm_handover, project_legitimization, contact_list,
  lop, deviation_agreement. New versions are picked up at startup or via
  `python scripts/load_form_definitions.py` — never edit a seeded row in
  place, bump `version` in the JSON.
- Frontend: `frontend/src/forms/` — `FormRenderer.tsx`, `FormPanel.tsx` (the
  side panel opened from a SEP item or the Forms tab), `expr.ts` (mirrors the
  Python evaluator), `ProjectFormsTab.tsx` (replaces the old Risks tab).
- Migration `065_sep_forms` creates the three tables and seeds the
  definitions itself. It does **not** copy `sep_risks` — a second DB
  connection can't see the migration's own uncommitted DDL — so that copy
  runs idempotently in `app/main.py`'s `lifespan` at every startup (marker:
  `migrated_from_sep_risk`), with `scripts/migrate_sep_risks.py` as the
  manual fallback.
- `reportlab==4.2.5` is a new backend dependency (`backend/requirements.txt`);
  the backend image needs a rebuild, not just a restart, to pick it up.

**`sep_risks` is dead data.** The old `SepRisk` table and its three
`/risks` endpoints are still in the codebase and still readable, but gate
colour and yellow-gate sign-off now read the `risk_assessment` form instance
instead. Keep `sep_risks` until production (1994A/1994B) has been verified
against the new forms, then remove the table, model and endpoints in a
follow-up commit — do not remove it opportunistically before that check.

**Decisions recorded in the spec during implementation** (see the spec's
"SEP link", "Risk migration and gate logic", section 5 permissions, and
section 7/8 for the full text):
- Reopen only flips a SEP item back to `open` if its remark still reads
  exactly `via form <title>`; an item someone has since ticked done by hand
  is left alone.
- Reopen is open to any authenticated user (not just PM/owner) because the
  project model has no manager field yet to restrict it to.
- An empty `sep_items` list means the form is Forms-tab-only, not reachable
  from any SEP item row (used by `lop` and `deviation_agreement`).
- `/v1/forms/my-forms` lists only draft/reopened instances the caller owns —
  it does not also try to surface "awaiting my signature" instances, because
  signature roles are self-declared at sign time with no role model behind
  them to check against.
- Gate sign-off is refused (409) while the project has unfinished risk rows
  with no gate assigned at all; gate colour itself still only ever reads
  rows assigned to that specific gate.

**Follow-ups (not started):**
- ~30 remaining structured SEP documents, as definition-file-only additions
  (no new engine work expected).
- `gate_items` column exists on `form_definitions` and is stored per
  definition (all currently `false`) but nothing enforces it yet — flipping
  it on should block a linked SEP item from being marked done without a
  submitted form instance; that gating check is unwritten.
- Remove `sep_risks` (table, model, three `/risks` endpoints) and any
  leftover old-risk-tab frontend code, once 1994A/1994B are verified in
  production against the new risk_assessment form.
- No signer role model yet for sign-off attribution or a real My Tasks
  "awaiting your signature" view — same gap noted above for `/my-forms`.

**Why:** user wants forms adapted on the fly during first project 1994A/B.
**How to apply:** production rollout is a separate step (user runs, not
part of this branch): rebuild the backend image, `alembic upgrade head`,
verify 1994A/1994B got a risk_assessment instance carrying their old
`sep_risks` rows, then check the K0/RG1 gate colours match what they were
before. Related: [[brose-award-import-2026-09-02]].
