---
name: change-flow-rework-2026-07-23
description: "Change-management flow rework session (Jul 22-23): UI/lifecycle fixes, department rename, technical-assessment routing, Outlook attendee autofill — plus the role matrix to encode from the assessment stage on"
metadata:
  type: project
---

Change Management flow rework, worked interactively Jul 22–23 2026. Work is committed on **`main`** — this is intentional and fine (user confirmed). Another actor (adminpanel chat) also commits here. **AdminPanel is updated and rolled out; the hub `/contacts` endpoint works on prod too** — the whole Outlook attendee-autofill chain is live end-to-end (confirmed Jul 23). Live stack: docker `claude-plm2-backend-1` (Postgres `plm2-db`, port 8000), frontend :5173, hub at http://localhost/plm2/. Backend tests run **on host from `backend/`** via `python3 -m pytest` (NOT in container — no aiosqlite); baseline **365 pass**, frontend **158 pass**.

## Done this session (commits 59b1e73b..be854914)
- **Audit timeline**: reads as prose (who · action · plain-language change), no raw JSON; `AuditLog.user_name` added.
- **Attachments**: drag-drop dropzone + the 3 upload bugfixes (axios multipart Content-Type; FastAPI 422 detail-array crash → `apiErrorMessage` helper; window-level stray-drop guard in App.tsx). Delete buttons. **Baseline/post-scoping phase split** — baseline docs freeze once scoping ends (VDA/IATF). `ChangeAttachment.phase`.
- **Start Change modal**: number-first project; change type moved below project, limited to `physical_part`; item picker filtered to physical prefixes 10/11/20/22 (hidden-count note); tools collapsed.
- **Deadline gate**: `required_by_date` is a scoping-exit soft guard (captured→in_assessment blocked without it). Deadline card in Scoping tab.
- **Priority** inline editor; **active-phase** dot on the tab matching current status.
- **Scoping decision channel**: meeting | chat | email (`change_meetings.channel`); no evidence attachment needed.
- **Attendee autofill**: `/api/v1/contacts` (PLM2 proxies hub, forwards cookie, local-users fallback). Picked names render as **removable chips**; **Enter/Tab confirm best match** (exact>prefix>contains). Hub `/contacts` endpoint delivered by the **adminpanel chat** ("email name puller working"); spec at `docs/handoff/adminpanel-contacts-endpoint.md` (delegated People.Read, live fetch no 24h cache — decided against MSAL.js). Handoff copy left in `adminpanel/docs/`.
- **Migrations 032–035 applied**: 032 dept merge/retire + can_start_change (permission-guard code was reverted per user, column kept); 033 attachment.phase + meeting.channel; 034 technical-assessment routing + create Process Engineer + reactivate APQP; 035 rename **Tool design→Tooling Engineer, IE→Manufacturing Engineer** (+ dropped orphan shells; cleaned 3 auto-reload duplicate depts by hand).

## Active departments (13): APQP, Sales, Project Manager, Planner/Scheduler, R&D, Tooling Engineer, Manufacturing Engineer, Quality, Logistics, Production, Purchasing, Production control, Process Engineer.

## Technical-assessment routing NOW (template 116 stage-1, `ECM_BEWERTUNG` seed)
R: R&D, Tooling Engineer, Manufacturing Engineer, Process Engineer, APQP, Quality. I: Logistics, Project Manager, Sales. Scoping picker pre-marks the R depts (★) via `GET /changes/{id}/recommended-departments`; meeting `selected_department_ids` narrows the fan-out.

## Role matrix to ENCODE FROM THE ASSESSMENT STAGE ON (user spec Jul 23 — do NOT migrate yet, "we change it anyways")
- **Tooling Engineer** R — all tool decisions; tool changes to change the article.
- **R&D (Development)** R — the article + article feasibility (article designer).
- **APQP** R — PPAP, quality oversight, **gauge** changes + gauge feasibility.
- **Manufacturing Engineer** R — equipment (injection molding, EOAT, assembly stations); feasibility + implementation.
- **Quality** → **I** (change from current R; APQP does the main job).
- **Project Manager** I — controls flow, raises escalations when stuck.
- **Sales** R (commercial) — finalize + send quotations; informs PM/team on implementation.
- **Logistics** R (timing) — bank-build scheduling, machine-availability windows, no run-outs.
- **Process Engineer** — user didn't mention this round; assume folds into Manufacturing Engineer unless clarified.
→ Net changes when we encode: Quality R→I; technical R narrows to 4 domains (Tooling, R&D, APQP, Mfg Eng); confirm Process Engineer's fate.

## Walkthrough state
Test change **CR-2026-0002** "Add Support pads" in **scoping**, customer_relevant=true, lead set, 1 impacted item, no deadline, no proceed meeting, 1 baseline attachment (real .msg). To advance: set deadline + record a proceed decision (picker pre-marks the 6 R) → **→ In Assessment**. That's where we iron out the role matrix above.

## Parked (see [[change-management-roadmap]])
- Duplicate template: two "ECM Assessment" templates (116 live, 119 dup) — 035 rewrote both stage-1s but the dup should be removed.
- change_type still maps only physical_part meaningfully (others deferred).
- Stages 2–3 (Summation & Budget, Customer activities) routing untouched — separate commercial conversation.
- DB was wiped of all 113 backfilled changes early in the session (backup `backend/plm-before-change-wipe.dump`); restore+re-import when done testing.
