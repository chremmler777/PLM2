# Project timing from standard blocks: trace

Living trace for **TOC-PLM-07 Requirements: Project Timing from Standard Blocks**
(`docs/audit-plans/TOC-PLM-07 Requirements Project Timing.docx`, source `docs/audit-plans/build/content_rs.py`).
This file is the working copy: update it with every finding, decision and implementation step, then carry the
status into section 8 of TOC-PLM-07 at its next revision.

Rules
- Every implementation commit names its requirement: `feat(timing): ... (TR-05)`.
- A requirement is **Done** only when its acceptance test in TOC-PLM-07 section 4 passed; put the evidence (commit,
  test, screenshot) in the matrix.
- New findings get the next TF number, new decisions the next D number, here first.

Status: Open = nothing yet; Partial = PLM2 has the basis, the timing function is missing;
Pilot = proven in the Excel / MS Project pilot, not in PLM2; Done = in PLM2 and acceptance passed.

## Traceability matrix

| No. | Requirement (short) | From | PLM2 basis | Status | Evidence |
|---|---|---|---|---|---|
| TR-01 | Blocks as master data (steps, role, duration, links, checklist, SEP ref) | TF-08, pilot | - | Pilot | `G6x Timing Template.xlsx` Blocks, `generate.py` BLOCKS |
| TR-02 | Block owner, version, draft/released, plan keeps its version | Concept | SEP item audit pattern | Open | |
| TR-03 | Roles not persons; role list = project team roles (+D-01) | TF-07 | `project_responsibles` | Partial | Team sheet |
| TR-04 | Checklists instead of rows; from data (TR-16, TR-17) | TF-08 | - | Pilot | Checklist column (text only) |
| TR-05 | Apply block to items (LAUNCH per tool, PPAP per part family, MOLDCHG per ECR) | Pilot | items, produces relation, `tool_machine` | Pilot | Plan sheet: 9 tools -> 99 tasks |
| TR-06 | Only anchor dates entered, rest calculated on working calendar | TF-01 | `plan_engine` calendar | Pilot | 99/99 Excel dates = generator, 10/02/2026 |
| TR-07 | Project-specific tasks next to generated ones, linkable | Section 1 | change plan free tasks | Open | |
| TR-08 | Add / drop items later (drop = cancel with reason) | Concept | - | Open | |
| TR-09 | Project plans on the Gantt 2.0 engine; successors move | TF-01 | `plan_engine` (change plans only) | Partial | MS Project XML: 72 links |
| TR-10 | Logic checks: impossible order, missing mandatory step | TF-02..04 | `plan_engine` validation warnings | Partial | Pilot plans TH1 after gauge |
| TR-11 | Baseline at release, progress, actuals, slip | TF-01 | `plan_engine` baseline/progress | Partial | |
| TR-12 | Date move after baseline needs reason, audited | Concept | release deadline move (F-02) | Partial | |
| TR-13 | Block step -> SEP work item; SEP item shows progress, close proposed | Concept | `sep_work_items` | Partial | Mapping proposal TOC-PLM-07 s.5 |
| TR-14 | SEP gate target vs block milestones, flag late | Concept | `sep_gates.target_date` | Partial | |
| TR-15 | Mold changes as ECR, MOLDCHG = change plan template, project shows milestones | TF-09 | ECR change plan | Partial | MOLDCHG block defined |
| TR-16 | Control plan characteristics per article in the PDB | TF-08 | - | Open | |
| TR-17 | PPAP checklist = submission elements, set per customer (AIAG / VDA iPQ) | TF-08 | `ppap_submissions` (AIAG 18) | Partial | iPQ list in PPAP block |
| TR-18 | My tasks per person, 2-3 weeks, main/backup | TF-10 | My Tasks (ECR) | Partial | |
| TR-19 | PM view: Gantt, filters, exception list | TF-10 | Gantt 2.0 UI (change plans) | Partial | |
| TR-20 | MS Project XML export with links and resources | Pilot | - | Pilot | `G67 Timeline (from template).xml` |
| TR-21 | Milestone on-time KPIs, calendar-day rule | Concept | ECR KPI board | Partial | |
| TR-22 | Rights: PM edits plan, block owners edit blocks, members report progress | Concept | project team rights | Partial | |

## Findings (from G6x Project Timeline (2026-09-30).mpp, 10/02/2026)

| No. | Finding |
|---|---|
| TF-01 | 0 of 239 tasks linked, no constraints, no baseline |
| TF-02 | Molds 3362, 3343, 3352: unpack (08/31-09/03) before delivery (09/03) |
| TF-03 | Mold 3376: no TH1; TH2 on gauge validation day |
| TF-04 | Mold 3362: TH1 on gauge validation day |
| TF-05 | Mold 3377: press 1300-2 vs 1300-3 |
| TF-06 | Task 5.9.11 named "TH2", is the 30-pc Cpk |
| TF-07 | Duplicate resources (holmes x3, Rautzenberg x3), a task text as resource |
| TF-08 | Cpk + iPQ as single rows (39 rows) |
| TF-09 | Mold changes 3360/3349/3369 as project tasks (~55 rows) |
| TF-10 | One 239-line Gantt for everybody |

## Decisions

| No. | Decision | Who | Status |
|---|---|---|---|
| D-01 | Role list: extend project team (Metrology, CMM lab, trial lead, plant layout, toolshop, production planning) or map | Program Mgmt., Quality | Open |
| D-02 | Mandatory block steps | Workshop S2 | Open |
| D-03 | SEP item closing: proposed (default) or automatic | Quality | Open |
| D-04 | Owner of the block library | Program Mgmt. | Open |
| D-05 | MS Project after go-live: export only or also import | PM 1748 | Open |

## Log

| Date | What | Ref |
|---|---|---|
| 10/02/2026 | G6x timeline analysed (239 tasks); pilot built: Excel template, MS Project XML, generator; 99/99 dates verified; 38/53 PM dates identical, 15 explained by TF-02..04 and hand-picked unpack days | `docs/project-timing/` |
| 10/02/2026 | TOC-PLM-07 Rev. 01 written (22 requirements, SEP mapping, timing S1-S7, decisions D-01..05) | `docs/audit-plans/build/content_rs.py` |
| 10/05/2026 | Tool shrinkage decision record (input for block step L09 "6-pc dimensional": verify the shrinkage there). PLM2: `tool_shrink_decisions` (migration 112), tool page card "Shrinkage" (candidates from MaterialDB with source, decide with reason, verify after trial, report back); MaterialDB: `shrink_experiences` + service PUT. Not deployed | `backend/app/services/tool_shrink_service.py`, MaterialDB `c3e4f5a6b7d8` |
