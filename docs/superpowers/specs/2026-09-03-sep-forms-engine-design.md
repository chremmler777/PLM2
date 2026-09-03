# SEP Forms Engine — Design

Date: 2026-09-03
Status: approved in conversation, pending written review
Scope: first batch of six forms plus the engine; further forms are JSON-only follow-ups

## 1. Goal

Replace the corporate Excel/Word templates that accompany the SEP matrix
(F-DVS-CORP-002) with in-app forms. A form is opened from the SEP work item it
belongs to, filled per project, submitted, and its submission marks the linked
work items done. No document control numbers in daily use; the corporate form
each definition implements is recorded as metadata for traceability.

Decisions taken with the user:

- Form layouts are JSON definitions in the repo, changed by the developer on
  request ("option 1"). No in-app form builder.
- Submitting a form completes its linked SEP items; reopening reopens them
  ("form drives the item"). A per-definition `gate_items` flag exists for a
  later switch to "item cannot be done without the form" and defaults to off.
- The existing SEP risk tab is replaced by the risk assessment form; existing
  rows migrate.
- English only. German labels from the originals are dropped.
- First batch: risk assessment (005), sales-to-PM handover (001), project
  legitimization (013), contact list (004), open points list / LOP (010),
  deviation agreement (011). Remaining ~30 structured documents follow as
  definition files only. Prose documents (kick-off manual, work package
  descriptions, specifications) become reference links on SEP items, not forms.

Sources: `Documents/SEP/global-forms/` (corporate, English) and
`Documents/SEP/weissenburg-ep-docs/` (plant Weißenburg, mostly German). Toccoa
has no own versions on Q.wiki; the global set applies.

## 2. Data model

Three new tables (Alembic migration `065_sep_forms`, revises `064`).

### form_definitions

| column | type | notes |
|---|---|---|
| id | int PK | |
| key | str(60) | e.g. `risk_assessment`, stable across versions |
| version | int | bumped in the JSON file; (key, version) unique |
| title | str(200) | |
| implements | str(60) nullable | corporate form, e.g. `F-DVS-CORP-005 rev 01` |
| cardinality | str(10) | `single` or `multi` per project |
| gate_items | bool | when true, linked items cannot be set done unless a submitted instance exists (off for all first-batch forms) |
| body | JSON | the full definition (section 3) |
| created_at | datetime | |

Rows are immutable. A new version is a new row. Loader inserts missing
(key, version) pairs and never updates existing rows.

### form_instances

| column | type | notes |
|---|---|---|
| id | int PK | |
| project_id | FK projects | index |
| definition_id | FK form_definitions | the version it was created against |
| status | str(20) | `draft`, `submitted`, `reopened` |
| data | JSON | field values, tables as lists of row objects |
| owner_id | FK users nullable | assigned owner, shown in My Tasks |
| created_by / created_at | | |
| updated_by / updated_at | | |
| submitted_by / submitted_at | nullable | last submit |

`reopened` behaves like `draft` for editing; it exists so the UI and audit
show that a submitted form was taken back.

### form_events

| column | type | notes |
|---|---|---|
| id | int PK | |
| instance_id | FK form_instances | index |
| user_id | FK users | |
| event | str(20) | `created`, `saved`, `submitted`, `reopened`, `signed` |
| role | str(20) nullable | for `signed`: the signature role from the definition |
| diff | JSON nullable | for `saved`: `{path: [old, new]}` for changed leaf values |
| created_at | datetime | |

Signatures are events, not columns. A form "has all signatures" when, since
the most recent `submitted` or `reopened` event, every role in the
definition's `signatures` list has a `signed` event.

### SEP link

SEP item numbers restart at 1 in every gate, so `sep_items` entries are
`"<gate code>:<item_no>"`, e.g. `"K0/RG1:2"`.

On `submitted`: every `SepWorkItem` in the project matched by the
definition's `sep_items` and whose status is `open` flips to `done`, with a
`SepItemAudit` row (`field="status"`, `old="open"`, `new="done"`,
`user_id=submitting user`) and the remark set to `via form <title>` if the
remark is empty. On `reopened`: items set done by this form flip back to
`open` with a matching audit row. Items on a closed gate are not touched (gate
lock wins). Items set `not_applicable` are not touched.

### Risk migration and gate logic

The migration creates one `risk_assessment` instance per project that has SEP
gates, and copies each `SepRisk` into the `risks` table section (see section
4). The risk table has a `gate` column (gate code) so a risk stays attached
to the gate it was raised in. Gate colour (red when a high or very high risk
is unfinished) and yellow-gate sign-off (open items need risks with complete
action plans due within 14 days) read the risk rows of the project's
risk-assessment instance instead of `sep_risks`. `sep_risks` and its three
endpoints stay as dead data until production has been verified; removal is a
follow-up commit.

## 3. Definition format

One file per form under `backend/app/data/forms/<key>.json`.

```json
{
  "key": "risk_assessment",
  "version": 1,
  "title": "Risk Assessment",
  "implements": "F-DVS-CORP-005 rev 01",
  "cardinality": "single",
  "gate_items": false,
  "sep_items": ["K0/RG1:2"],
  "signatures": [],
  "required_for_submit": ["header.project_manager", "risks"],
  "sections": [ ... ]
}
```

### Sections

Two kinds.

`fields` section:

```json
{"id": "header", "title": "Project", "kind": "fields",
 "fields": [
   {"id": "project_no", "label": "Project No.", "type": "text", "prefill": "project.code", "readonly": true},
   {"id": "sop", "label": "SOP", "type": "date"},
   {"id": "classification", "label": "Classification", "type": "choice",
    "options": ["Strictly confidential", "Confidential", "Internal", "Public"]}
 ]}
```

`table` section:

```json
{"id": "risks", "title": "Risks", "kind": "table", "min_rows": 0,
 "columns": [
   {"id": "risk", "label": "Risk", "type": "multiline", "width": 3},
   {"id": "q", "label": "Q", "type": "number", "min": 0, "max": 1},
   {"id": "c", "label": "C", "type": "number", "min": 0, "max": 1},
   {"id": "s", "label": "S", "type": "number", "min": 0, "max": 1},
   {"id": "p", "label": "PoC", "type": "number", "min": 0, "max": 1},
   {"id": "rkz", "label": "RI", "type": "computed", "expr": "(q + c + s) * p"},
   {"id": "prio", "label": "Priority", "type": "computed", "expr": "band(rkz, [0.4,'low'],[0.8,'medium'],[1.0,'high'],'very high')"}
 ],
 "footer": [{"label": "Open", "expr": "count(status == 'open')"}]}
```

### Field types

`text`, `multiline`, `number` (`min`, `max`, `step`), `date`, `checkbox`,
`choice` (`options`), `multichoice`, `user` (user picker, stores user id),
`computed` (`expr`).

Computed expressions are evaluated both in the browser (live) and on the
server (on save, values are recomputed and stored, so exports and queries do
not depend on client math). The expression language is deliberately tiny:
arithmetic, comparison, `and`/`or`/`not`, field references by id within the
same row or section, and the helpers `band`, `count`, `sum`, `today`,
`days_between`. Implemented once in Python and once in TypeScript with a
shared test vector file.

### Prefill

`prefill` is a dotted path resolved on instance creation only; the value is
then ordinary data. Supported roots for the first batch:

- `project.` — `code`, `name`, `plant` (plant name)
- `user.` — `me` (current user id), `me_name`
- `date.` — `today`
- `team.` — for the contact list: `members` expands to one table row per
  distinct user assigned as responsible on any SEP item of the project

RFQ data lives in a separate database and the project model has no customer,
manager or SOP fields, so those header fields are typed by hand in this batch.

Unknown paths fail the definition validation test, not the runtime.

### Validation

`required` on a field or column applies on submit only. `required_for_submit`
lists section ids or `section.field` paths that must be non-empty on submit;
for a table section it means at least `min_rows` rows (default 1 when listed).
Drafts save anything.

### Signatures

`signatures` is a list of role keys (`md`, `pm`, `quality`, `dt`). The app
has no role model for these; as with SEP gate sign-off, the signer states the
role and the rule enforced is that each role is signed by a different user.
Submit is allowed without signatures; the instance shows "awaiting
signatures" until all are present. For the first
batch: legitimization requires `md` and `pm`; deviation agreement requires
`md`, `dt`, `pm`; the rest require none.

### Reference documents

A definition may carry `references`: a list of `{title, path}` pointing at
files under `Documents/SEP/` that the UI shows as download links on the form
(e.g. the kick-off process manual on the sales handover form). Prose-only
documents that have no form get an entry in `backend/app/data/sep_references.json`
keyed by SEP item number, rendered the same way on the work item row.

## 4. First-batch definitions

| key | implements | cardinality | signatures | sep items (K0/RG1, K/RG2) | notes |
|---|---|---|---|---|---|
| risk_assessment | F-DVS-CORP-005 rev 01 | single | — | K0/RG1:2 | header + risks table (Q/C/S/PoC, RI, priority, countermeasure, responsible, due, status, post-measure Q/C/S/PoC/RI) + ISMS table (C/I/V) + environment table (ND/D/HD). Replaces risk tab. |
| sales_pm_handover | F-DVS-CORP-001 | single | — | K/RG2:10 | customer & scope, volumes, pricing & one-time payments, tooling amortization, milestones, checks done (feasibility, capacity, risk, lessons learned) |
| project_legitimization | F-DVS-CORP-013 | single | md, pm | K0/RG1:39, K/RG2:7 | header, budget table (development, tooling, gauge, gripper, packaging, assembly equipment, CTM transport, BARA, other), savings block, remark |
| contact_list | F-DVS-CORP-004 | single | — | K/RG2:8 | table: name, department, position, phone, email; prefilled from project members |
| lop | F-DVS-CORP-010 | single | — | none (reachable from the Forms tab) | table: pos, entry date, process, task, description, internal/external, responsible, due, status, comments; footer counts complete / on track / at risk / overdue |
| deviation_agreement | F-DVS-CORP-011 | multi | md, dt, pm | none (reachable from the Forms tab) | header, reason, budget / deviation table, remark |

Item references are checked against `sep_template.json` by the definition test.

## 5. API

New router `backend/app/api/v1/timing/forms.py`, prefix `/v1/forms`.

| method | path | purpose |
|---|---|---|
| GET | `/definitions` | latest version of every definition (key, version, title, cardinality, sep_items) |
| GET | `/definitions/{key}` | latest body |
| GET | `/projects/{project_id}` | instances for the project, grouped by definition, with status, owner, updated |
| POST | `/projects/{project_id}/instances` | body `{key}`; creates against latest version, runs prefill; 409 if `single` and one exists |
| GET | `/instances/{id}` | instance + its definition body + events |
| PATCH | `/instances/{id}` | save draft: `{data, owner_id?}`; recomputes computed fields; writes `saved` event with diff; 409 if submitted and not reopened |
| POST | `/instances/{id}/submit` | validates, recomputes, flips linked SEP items, `submitted` event |
| POST | `/instances/{id}/reopen` | PM or owner; flips items back, `reopened` event |
| POST | `/instances/{id}/sign` | body `{role}`; role must be in the definition, not yet signed since last submit, and by a user who has not signed another role on it; `signed` event |
| GET | `/instances/{id}/export.pdf` | PDF (section 7) |
| GET | `/my-forms` | drafts owned by me + submitted instances awaiting my signature role |

SEP endpoints: `GET /v1/sep/projects/{id}` gains per item `form: {key, title, instance_id|null, status|null}` and `references: [...]`. The three `/risks` endpoints remain until the follow-up removal.

Permissions follow the SEP module: any project member can create, save and submit; reopen is the project manager or the instance owner; sign follows the four-eyes rule above.

## 6. Frontend

- `frontend/src/forms/` — `FormRenderer.tsx` (definition + data → fields, sections, tables, computed cells), `expr.ts` (expression evaluator, mirrors Python), `types.ts`.
- `FormPanel.tsx` — side panel opened from a SEP item or the forms tab; header with status, owner, version; save / submit / reopen / sign / export buttons by state and role; read-only rendering when submitted.
- `ProjectSepSection.tsx` — item rows show a form button with status chip and reference links; a new **Forms** tab replaces the **Risks** tab and lists instances grouped by gate.
- `MyTasksPage.tsx` — new **Forms** section from `/my-forms`.
- Uses the existing react-hook-form and zod; zod schema is generated from the definition at runtime.
- Dashboard SEP widget unchanged.

## 7. Export

PDF per submitted instance: title, project header, version and `implements`,
sections and tables in definition order, then an event history page. Rendered
server-side with `reportlab` (new dependency in `backend/requirements.txt`),
landscape for table-heavy forms. No Excel export in this batch.

## 8. Migration and rollout

1. Alembic `065_sep_forms`: create the three tables; data step creates a
   `risk_assessment` instance for each project with SEP gates and copies
   `sep_risks` rows into `data.risks` (mapping: effect→risk, q/c/s/probability
   →q/c/s/p, countermeasure, due_date, responsible_id, status; rkz and priority
   recomputed).
2. Definition loader runs at app startup and via
   `backend/scripts/load_form_definitions.py`.
3. Production deploy as usual; verify 1994A/1994B risk instances, then remove
   `sep_risks` and the risk tab in a follow-up.

## 9. Testing

- `tests/test_form_definitions.py`: every JSON file parses; only known field
  types and prefill roots; `sep_items` exist in the template; expressions
  reference known ids; shared expression test vectors pass in Python.
- `tests/test_forms.py` (pattern of `test_sep.py`): create single/multi rules,
  prefill from project and RFQ, save with diff event, computed recompute on
  server, submit validation, submit flips items with audit rows and respects
  closed gates and `not_applicable`, reopen flips back, signatures by role,
  `/my-forms`, PDF export returns a PDF, risk migration mapping.
- Frontend: `expr.test.ts` against the shared vectors; `FormRenderer.test.tsx`
  with one definition covering every field type.
- Manual check on project 1994A in the dev stack before deploy.

## 10. Out of scope

In-app form builder; Excel export; German labels; gating of SEP items (flag
present, off); removal of `sep_risks` (follow-up); the remaining ~30 forms
(follow-up definition files); Toccoa-specific variants (none exist on Q.wiki).
