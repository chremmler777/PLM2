"""Content of TOC-PLM-00..05. Blocks: ("h1", t) ("h2", t) ("p", t) ("b", t) ("img", file, alt)
("table", widths_in, header, rows) ("pb",). **bold** marks bold runs."""

DATE = "09/30/2026"
INTERNAL = "internal working document, not controlled"
DEPT = "Process Development"
AREA = "Engineering / PLM2"
LOP = "TOC-PLM-LOP (KTX LOP F-DVS-CORP-010)"

AUTH = ["C. Demmler, Process Development: owner of PLM2 and of every action in this plan, author, keeps it current",
        "Program Management and APQP: support (specification, tests, pilots on the running projects, evidence)",
        "Departments named per action (IT, Quality, Development, Tooling, HR, department heads): support where their "
        "part is needed",
        "Plant Management: monthly status review"]


def req(rows):
    return ("table", [1.6, 2.75, 2.25], ["Requirement", "How it is met", "What we show"], rows)


def status(rows):
    return ("table", [2.3, 1.1, 3.2], ["Element", "Status", "Evidence in PLM2"], rows)


def tighten(rows):
    return ("table", [1.9, 3.05, 0.65, 1.0], ["Today", "Tightening measure", "Action", "Due"], rows)


def actions(rows):
    return ("table", [0.4, 1.7, 0.95, 0.85, 0.9, 0.8, 1.0], ["No.", "Action", "Phase", "Owner", "Support", "Due", "Done when"], rows)


def kpi(rows):
    return ("table", [2.5, 2.1, 2.0], ["Indicator", "Target", "Source"], rows)


LOP_NOTE = ("p", f"The table is the plan as of the status date above. Progress is tracked in the action plan **{LOP}**; "
                 "a date that moves is changed there with the reason, and this document is updated with it.")

DOCS = []

# ------------------------------------------------------------------ 00
DOCS.append({
    "no": "TOC-PLM-00", "title": "PLM2 Program Overview and Master Timing", "file": "TOC-PLM-00 Program Overview",
    "purpose": "Entry point of the PLM2 implementation program at KTX Toccoa: change management, SEP / project planning, "
               "data management, lessons learned and information security move into one controlled, web-based system. "
               "In an audit this overview is shown first; the stream document of the topic is pulled next to the live system.",
    "blocks": [
        ("h1", "1. Program at a glance"),
        ("table", [1.05, 2.1, 2.1, 1.35], ["Document", "Stream", "State today", "PLM2 only from"], [
            ["TOC-PLM-01", "Change management (ECR)", "**Built.** In test; role model being tightened", "12/21/2026"],
            ["TOC-PLM-02", "SEP / project database", "**Built.** Evidence being uploaded; 1994 is lead project", "01/18/2027 (new projects)"],
            ["TOC-PLM-03", "Data management, traceability", "**Core tight**; remaining functions in development", "03/22/2027"],
            ["TOC-PLM-04", "Lessons learned", "**Built.** Being bound into SEP and ECR", "01/04/2027"],
            ["TOC-PLM-05", "Information security (TISAX)", "**Built** on company SSO and server; three points tightening", "12/11/2026"],
        ]),
        ("h1", "2. From today to target"),
        ("img", "img/flow_overview.png", "System landscape today and target", 6.0),
        ("p", "**Where we come from (brief).** The information is correct today, but it lives in several places: SharePoint lists, "
              "Excel forms (GB-CM-0001, GB-DP-0001), network drives and a read-only legacy system. Not everyone can reach every "
              "source, and the link between a customer change, the part level, the tool and the gauge is kept by hand. "
              "The program closes exactly these points:"),
        ("table", [2.3, 4.3], ["Today", "Target with PLM2"], [
            ["Several tools, no single controlled record", "One system of record per topic; old sources frozen read-only at go-live"],
            ["Access depends on site and SharePoint rights", "Web access for every department with the company account, rights by role"],
            ["Traceability maintained by hand", "Part-tool-gauge-equipment relations and revision history are system data, with where-used and audit trail"],
            ["Timing in separate files, tasks by e-mail", "Gate dates, change plans and deadlines in the record; every person sees their own tasks with due dates"],
        ]),
        ("h1", "3. Master timing"),
        ("p", "Each stream runs through **programming** (close the remaining functions), **testing** (scripted acceptance test and "
              "live pilot on real projects) and **finalisation** (procedure released, training, old source frozen). "
              "Operation and the effectiveness review follow."),
        ("img", "img/gantt_master.png", "Master timing"),
        ("table", [1.3, 5.3], ["Milestone", "Meaning"], [
            ["12/11/2026", "ECR acceptance test and G6X pilot complete; SEP gate enforcement live; TISAX points closed"],
            ["12/21/2026", "**ECR go-live:** every new change at TOC runs in PLM2 only; the SharePoint ECC list becomes read-only"],
            ["01/04/2027", "Lessons learned procedure released; SEP evidence of running projects uploaded"],
            ["01/18/2027", "**SEP go-live:** new projects start in PLM2 only; the Excel SEP matrix is retired for new projects"],
            ["03/22/2027", "**Data management go-live:** network drives read-only for active projects"],
            ["03/2027", "Effectiveness reviews per stream, reported to management review"],
        ]),
        ("h1", "4. Using this in an audit"),
        ("table", [2.4, 1.0, 3.2], ["If the auditor asks about", "Pull", "Show live in PLM2"], [
            ["Control of changes (IATF 8.5.6, 8.3.6)", "TOC-PLM-01", "A change record: stages, hard gates, routing, timing plan, sign-offs, audit trail; G6X changes CR-2026-0001..0003"],
            ["Project planning, APQP, gates (IATF 8.3.2, VDA MLA)", "TOC-PLM-02", "Project 1994: SEP matrix RG1-RG7, items, evidence, dual sign-off"],
            ["Engineering specs, document control, traceability (IATF 7.5.3, 8.5.2)", "TOC-PLM-03", "Part with revision history, where-used, tool and gauge relations"],
            ["Organisational knowledge (IATF 7.1.6, 10.3)", "TOC-PLM-04", "Lessons board: G6X lessons with actions and effectiveness proof"],
            ["Information security, prototype data (TISAX, VDA ISA)", "TOC-PLM-05", "Company sign-in, roles, classification, audit trail"],
            ["Status of all of the above", LOP, "Open actions with owner, due date and status"],
        ]),
        ("p", "**Rule until each go-live:** the existing controlled forms stay valid and are filed on the PLM2 record, so control "
              "never has a gap. Where both exist, the PLM2 record leads."),
        ("h1", "5. How we implement: completed examples"),
        ("p", "PLM2 follows the same method that already brought two systems into daily controlled use at KTX Toccoa. "
              "Both run on the same company server, behind the same company sign-in, and are the record for their process today."),
        ("img", "img/flow_method.png", "Implementation method", 6.2),
        ("table", [1.45, 2.6, 2.55], ["", "TWOS (tooling work orders)", "RFQ2 (quotation system)"], [
            ["Process controlled", "Tool work orders, press calls, repairs, preventive maintenance, tool handover, spare parts", "RFQ costing: BOM, tooling cost, clamping force, cycle time, tool layout and machine choice, quote"],
            ["Replaced", "PowerApps apps on SharePoint lists", "Excel / PowerPoint quoting without revision control"],
            ["Users", "19 users in 6 roles (toolshop, scheduling, process technicians, managers)", "Sales, engineering departments, APQP, project management"],
            ["Live", "On server 07/04/2026; system of record from **08/05/2026** (plant cutover)", "System of record from **06/30/2026**"],
            ["Data migrated", "1,230 work orders, 230 tools, 1,270 history rows, 76 spare parts", "Running RFQs; awarded RFQs frozen (e.g. RFQ 26 on 09/21/2026)"],
            ["Tests", "About 775 automated backend tests", "About 1,880 automated backend tests"],
            ["Training", "Classroom sessions plus training gate with sign-off records", "Per department at introduction"],
            ["Cutover control", "Backup before cutover, written rollback, SharePoint kept as history only", "Backup before every release; local-to-server data push disabled"],
            ["Link to PLM2", "Tool data read by PDB; preventive maintenance status from WinCarat", "Machine picks of RFQ 25 / 26 taken over into PLM2 tools (09/29/2026)"],
        ]),
        ("h1", "6. Program control"),
        ("b", "Monthly status review with Plant Management against this timing and the LOP; minutes filed in PLM2."),
        ("b", "A date moves only with a reason recorded in the LOP; the stream document is updated to the new status."),
        ("b", "Each stream closes with an effectiveness review (indicators in the stream document) reported to management review."),
        ("b", "Software quality: every release passes the automated test suite (about 2,000 backend and 2,900 frontend tests) "
              "before it reaches the production server; the database is backed up before every data operation."),
    ]})

# ------------------------------------------------------------------ 01
DOCS.append({
    "no": "TOC-PLM-01", "title": "Implementation Plan Change Management (ECR)", "file": "TOC-PLM-01 Change Management ECR",
    "purpose": "Timing and action plan to run every product, process, tool and gauge change at KTX Toccoa in PLM2, including "
               "changes controlled by KTX Weissenburg. Standards: IATF 16949 8.5.6, 8.5.6.1, 8.3.6, 7.5.3; VDA 6.3 P2; VDA 2.",
    "blocks": [
        ("h1", "1. Summary"),
        ("p", "The change process is **built and running in PLM2**. What remains is **testing with the departments and tightening "
              "the role model**, so that every step is done by the right function only. Go-live, meaning every new change at TOC "
              "runs in PLM2 only, is **12/21/2026**."),
        ("h1", "2. Requirements and how they are met"),
        req([
            ["Documented change process, risk analysis before implementation (8.5.6, 8.5.6.1)", "Fixed stages; routed departments assess with an impact checklist and typed risks; not feasible stops the change", "Assessment tab of any change"],
            ["Customer approval before implementation (8.3.6.1, 8.5.6.1)", "Hard gate for customer changes: valid offer accepted plus PM and Quality sign-off before approved; internal changes need PM cost approval", "Offer tab, sign-off record"],
            ["Verification / validation of the change (8.5.6)", "Validation stage with department checks, a 16-item release checklist and validation issues (8D, escalation L1-L3)", "Release tab"],
            ["Records and traceability (7.5.3)", "Every action in a hash-chained audit trail; documents filed per stage", "Changelog of the change"],
            ["Changes from the mother plant", "Weissenburg side track: impact lock by Development and read-and-understood receipts before approval", "CR-2026-0001..0003 (G6X)"],
        ]),
        ("h1", "3. Process flow"),
        ("img", "img/flow_ecr.png", "ECR process flow", 6.0),
        ("b", "**Hard gates** cannot be overridden by anyone: impact lock before assessment, customer acceptance with PM and Quality sign-off before approval, and for Weissenburg changes impact lock plus team informed."),
        ("b", "**Soft guards** (kickoff, timing validated, release checklist) can only be passed with a documented, approved deviation."),
        ("b", "**Routing** (R/A/S/C per department) is set at scoping; a department added later needs a reason and a second approver."),
        ("h1", "4. Timing planner and tasks"),
        ("img", "img/timing_tasks.png", "Timing planner and task list"),
        ("b", "**Timing planner:** every approved change gets a detailed plan with blocks per department and vendor. Each responsible team confirms the plan revision; 'timing validated' sets the baseline. Export to MS Project for the customer."),
        ("b", "**Tracking:** progress and actual dates per block, regular progress reports. After the baseline every date move is a deviation with a reason, accepted internally or escalated to the customer through Sales."),
        ("b", "**Tasks:** every person sees their own open tasks (confirm plan, answer assessment, report progress, release check, decide deviation, read and understood) with due dates in 'My tasks' and a next-step checklist on the change."),
        ("b", "**Reminders:** due-soon and overdue tasks and deadlines at risk are notified automatically; the project team has one responsible per role and a backup."),
        ("h1", "5. Where we stand today"),
        status([
            ["Stages captured to closed, internal branch", "Built", "Lifecycle and gates in every change record"],
            ["Assessment, costing, offer, negotiation", "Built", "Assessment, Costing and Offer tabs"],
            ["Timing planner, baseline, deviations, tasks", "Built", "Timing tab, My tasks"],
            ["Release checklist, lessons step, validation issues", "Built", "Release tab"],
            ["Weissenburg side track", "Built, in use", "G6X changes CR-2026-0001..0003 from the ECC list"],
            ["Department rights per function", "**Tightening**", "Actions E1-E3"],
            ["Acceptance test with all departments", "**Testing**", "Actions T1-T2"],
        ]),
        ("h1", "6. Tightening points"),
        tighten([
            ["Edit rights are broad: most editors hold the admin role", "Rights per department from the company directory groups; admin only for IT and the system owner", "E1", "11/13/2026"],
            ["Internal cost approval allows the requester to approve", "Strict four-eyes on every approval and sign-off", "E2", "11/06/2026"],
            ["Training is recorded but not required", "Only trained users can act on a stage (training gate on)", "E3", "11/20/2026"],
            ["Changes also kept in SharePoint ECC list and Excel form", "PLM2 is the record from go-live; list frozen read-only", "F3", "12/21/2026"],
        ]),
        ("h1", "7. Timing and action plan"),
        ("img", "img/gantt_ecr.png", "ECR timing"),
        actions([
            ["E1", "Department rights from directory groups; admin role limited to IT and system owner", "Programming", "C. Demmler", "IT", "11/13/2026", "Rights matrix filed; test log per role"],
            ["E2", "Strict four-eyes on internal cost approval and sign-offs", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/06/2026", "Self-approval rejected in test"],
            ["E3", "Training gate switched on per stage", "Programming", "C. Demmler", "HR", "11/20/2026", "Untrained user blocked in test"],
            ["E4", "Close open flow points (cost carrier re-confirmation, impact edits after quote)", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/27/2026", "Regression suite green"],
            ["T1", "Scripted acceptance test, one script per stage, signed by each department", "Testing", "C. Demmler", "Department heads", "11/27/2026", "Signed test protocols filed"],
            ["T2", "Live pilot: G6X (1748) Weissenburg changes plus the next customer change", "Testing", "C. Demmler", "Program Mgmt., APQP", "12/11/2026", "Pilot changes complete in PLM2"],
            ["KP", "KPIs (open, to be defined): set targets, sources and review cycle for the change process, starting with implementation on time", "Finalisation", "C. Demmler", "Quality, Program Mgmt.", "12/11/2026", "KPI set agreed, shown in the monthly review"],
            ["F1", "Procedure 'Change management with PLM2' released", "Finalisation", "C. Demmler", "Quality", "12/11/2026", "Procedure in document control"],
            ["TR", "Training concept (open, to be defined): which roles need which training per module (ECR, SEP, data, lessons), format, trainer, records", "Finalisation", "C. Demmler", "Program Mgmt., APQP, HR", "11/20/2026", "Concept agreed with department heads"],
            ["F2", "Training of all departments per training concept (TR)", "Finalisation", "C. Demmler", "Program Mgmt., APQP", "12/18/2026", "Training records in PLM2"],
            ["F3", "Go-live: new changes in PLM2 only; ECC list read-only", "Finalisation", "C. Demmler", "Plant Mgmt.", "12/21/2026", "Announcement; list locked"],
            ["F4", "Effectiveness review after three months", "Operation", "C. Demmler", "Quality", "03/26/2027", "Review in management review"],
        ]),
        LOP_NOTE,
        ("h1", "8. Control until go-live"),
        ("p", "Until 12/21/2026 the Weissenburg form GB-CM-0001 and the SharePoint ECC list stay valid. Every change they hold for TOC "
              "is also opened in PLM2 with the form filed on it, so the PLM2 record is complete from the first day of the pilot."),
        ("h1", "9. Effectiveness indicators"),
        kpi([
            ["Changes run outside PLM2 after go-live", "0", "ECC list (read-only) vs PLM2"],
            ["Changes released with open validation issue", "0", "Release tab"],
            ["Changes past release deadline", "Trend down, reviewed monthly", "Change list, deadline state"],
            ["Overdue tasks at monthly review", "Trend down", "My tasks / notifications"],
            ["Changes implemented on time (implementation date met)", "To be defined (action KP)", "Change list, implementation deadline vs actual"],
        ]),
        ("p", "The KPI set beyond these indicators is to be defined (action KP): targets, data source in PLM2 and the review "
              "cycle are agreed with Quality and Program Management before go-live."),
    ]})

# ------------------------------------------------------------------ 02
DOCS.append({
    "no": "TOC-PLM-02", "title": "Implementation Plan SEP / Project Database", "file": "TOC-PLM-02 SEP Project Database",
    "purpose": "Timing and action plan to run project planning with the SEP matrix (maturity gates RG1-RG7) in PLM2 for all "
               "customer projects from RFQ to series. Standards: IATF 16949 8.3.2, 8.3.2.1, 8.3.4, 8.3.4.4; VDA MLA; VDA 6.3 P2-P4.",
    "blocks": [
        ("h1", "1. Summary"),
        ("p", "The SEP matrix is **fully in PLM2**: seven maturity gates with 232 items, the same content as the group template "
              "GB-DP-0001, created for every project. What remains is **uploading the evidence** of the running projects. Project "
              "**1994 (Brose Seat Trim, nominated 09/21/2026)** is the lead project: it runs every gate in PLM2 up to SOP, and the "
              "rules tighten with it. From **01/18/2027** new projects start in PLM2 only."),
        ("h1", "2. Requirements and how they are met"),
        req([
            ["Design and development planning, multidisciplinary (8.3.2, 8.3.2.1)", "SEP matrix per project; every item has a responsible function and a status (open, done, not applicable)", "SEP tab of project 1994"],
            ["Monitoring at defined stages (8.3.4)", "Gates close in order; closing needs PM and Quality sign-off and locks the items", "Gate status, sign-off record"],
            ["Product approval process (8.3.4.4)", "Pre-series gate B/RG6 and series gate A/RG7 carry the approval items", "Gates RG6 / RG7"],
            ["Documented evidence", "Files attached per SEP item; every item change audited field by field", "Documents tab, item history"],
            ["Maturity level logic (VDA MLA)", "Gates K0/RG1 to A/RG7 follow the maturity levels", "SEP matrix"],
        ]),
        ("h1", "3. Process flow"),
        ("img", "img/flow_sep.png", "SEP process flow", 6.0),
        ("b", "A gate opens only after the previous one is closed. Items are done or marked not applicable with a reason; nothing is skipped silently."),
        ("b", "Lessons learned are checked at RG1 and RG2 (TOC-PLM-04); evidence is filed on the item it proves."),
        ("b", "At SOP (A/RG7) the project hands over to series: from then on every change runs through TOC-PLM-01."),
        ("h1", "4. Project overview"),
        ("p", "A **project overview page** (action S1) shows every active project on one screen: current gate, gate target date, "
              "items open and overdue, open changes and open lessons. It is the page used in the monthly review and shown first in an audit. "
              "SEP items with an owner and due date appear in the owner's task list like change tasks (TOC-PLM-01, section 4)."),
        ("h1", "5. Where we stand today"),
        status([
            ["SEP matrix, 7 gates / 232 items per project", "Built", "Projects 1864, 1994, 2141, 2277"],
            ["Dual sign-off and item lock at gate close", "Built", "Gate close dialog"],
            ["File evidence per item, field audit", "Built", "Documents tab, item history"],
            ["Standard forms (risk assessment, handover, legitimisation, contact list, LOP, deviation agreement)", "Built", "Forms tab"],
            ["Evidence of running projects uploaded", "**In progress**", "Actions D1-D2"],
            ["Gate target dates, project overview, item enforcement", "**Programming**", "Actions S1-S3"],
        ]),
        ("h1", "6. Tightening points"),
        tighten([
            ["Evidence still on drives and in the Excel matrix", "Upload per item for running projects; Excel frozen for new projects", "D1, F2", "01/18/2027"],
            ["Gate dates not yet in the system", "Target date per gate with overdue signal, linked to the project timing", "S2", "11/13/2026"],
            ["Required items per gate not enforced", "Gate cannot close while a required item is open; defined signer per item", "S3", "12/11/2026"],
            ["No single view across projects", "Project overview page", "S1", "11/20/2026"],
        ]),
        ("h1", "7. Timing and action plan"),
        ("img", "img/gantt_sep.png", "SEP timing"),
        actions([
            ["S1", "Project overview page (all projects, gates, overdue, open changes and lessons)", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/20/2026", "Page live, used in monthly review"],
            ["S2", "Gate target dates linked to project timing, overdue signal", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/13/2026", "Dates set for all running projects"],
            ["S3", "Required items per gate enforced; signer role per item", "Programming", "C. Demmler", "Quality", "12/11/2026", "Gate close blocked in test"],
            ["D1", "Upload SEP evidence for running projects (1864, 1994, 2141, 2277)", "Documentation", "C. Demmler", "Program Mgmt., APQP", "01/04/2027", "Items done / n.a. with evidence"],
            ["D2", "1994: RG1 evidence complete, gate review with dual sign-off", "Documentation", "C. Demmler", "Quality", "12/04/2026", "RG1 closed in PLM2"],
            ["F1", "Procedure 'Project planning with the SEP matrix in PLM2' released", "Finalisation", "C. Demmler", "Quality", "12/28/2026", "Procedure in document control"],
            ["F2", "Excel SEP matrix retired for new projects", "Finalisation", "C. Demmler", "Plant Mgmt.", "01/18/2027", "First new project started in PLM2"],
            ["R1", "1994 runs RG2 to RG7 in PLM2; gate dates from the Brose customer timing", "Operation", "Program Mgmt.", "to SOP", "Each gate closed with sign-off"],
        ]),
        LOP_NOTE,
        ("h1", "8. Control until go-live"),
        ("p", "Running projects keep their current SEP evidence valid while it is uploaded; the upload is tracked item by item in PLM2, "
              "so the open amount is visible at any time. Project 1994 runs in PLM2 from now on."),
        ("h1", "9. Effectiveness indicators"),
        kpi([
            ["Gates closed on or before target date", "90 %", "Project overview"],
            ["Required items closed without evidence file", "0", "SEP matrix"],
            ["New projects started outside PLM2 after 01/18/2027", "0", "Project list"],
        ]),
    ]})

# ------------------------------------------------------------------ 03
DOCS.append({
    "no": "TOC-PLM-03", "title": "Implementation Plan Data Management and Traceability", "file": "TOC-PLM-03 Data Management",
    "purpose": "Timing and action plan for customer data, engineering levels, revisions and the part-tool-gauge-equipment "
               "relations of all KTX Toccoa projects in PLM2. Standards: IATF 16949 7.5.3, 7.5.3.2.1, 7.5.3.2.2, 8.5.2, 8.5.2.1.",
    "blocks": [
        ("h1", "1. Summary"),
        ("p", "**Traceability, engineering level and the data itself are already tight in PLM2:** every part carries its revision "
              "history with engineering level and customer index, every change is written to a tamper-evident audit trail, and part, "
              "tool, gauge and equipment are linked as system data. The module is **in development** for the remaining functions "
              "below; go-live, meaning network drives become read-only for active projects, is **03/22/2027**."),
        ("h1", "2. Requirements and how they are met"),
        req([
            ["Control of documented information (7.5.3)", "One active revision per part; older revisions stay in the history, read-only", "Part page, revision list"],
            ["Engineering specifications, review of customer changes (7.5.3.2.2)", "Every new customer index enters intake; Development decides: administrative, engineering review or full change", "Intake list, decision with reason"],
            ["Record retention (7.5.3.2.1)", "Revisions are superseded, never overwritten; every data change in the audit trail; database backed up before every data operation", "Revision history, backup log"],
            ["Identification and traceability (8.5.2, 8.5.2.1)", "Part numbers by family, tool and gauge numbering (tool-operation), relations with where-used and BOM", "Where-used of a tool, e.g. 3360"],
        ]),
        ("h1", "3. Process flow"),
        ("img", "img/flow_dm.png", "Data management flow", 6.0),
        ("b", "**Levels:** E1, E2 = customer review data; 1, 2 = official customer data; x.1 = own proposal. Shown as 'E2 · B' (our level · customer index). Counters never reset, so every level is unique."),
        ("b", "**Relations:** a tool produces articles, a gauge checks them, equipment serves the tool; mirror parts are relations, never copies."),
        ("b", "**Legacy data:** the former system (WinCarat) was imported once and is read-only; PLM2 is the master since."),
        ("h1", "4. Where we stand today"),
        status([
            ["Revision and level scheme, customer package receive", "Built, tight", "Part page of any series part"],
            ["Hash-chained audit trail on parts and changes", "Built, tight", "Part changelog"],
            ["Relations part-tool-gauge-equipment, where-used, BOM", "Built, tight", "1,337 tool-article links; 152 gauges and 14 equipment linked"],
            ["3D view of customer data (STEP)", "Built", "Viewer on the revision"],
            ["Review deadline for customer data (10 working days)", "**In development**", "Action M2"],
            ["Completeness: gauges without tool, customer part numbers", "**In development**", "Actions M3-M4"],
            ["Access scope on every list", "**In development**", "Action M1"],
        ]),
        ("h1", "5. Tightening points"),
        tighten([
            ["Drawings and customer data partly still on network drives", "Transfer per active project; drives read-only after go-live", "M6, F2", "03/22/2027"],
            ["Review time of customer data not measured", "Intake timer with overdue signal at 10 working days", "M2", "11/27/2026"],
            ["Some records incomplete (gauges without tool, customer part numbers)", "Completeness list, closed per project", "M3, M4", "01/04/2027"],
            ["Backup before data operations, not yet scheduled", "Scheduled backup with documented restore test", "M5", "11/20/2026"],
        ]),
        ("h1", "6. Timing and action plan"),
        ("img", "img/gantt_dm.png", "Data management timing"),
        actions([
            ["M1", "Access scope closed on all lists (SEP, lessons)", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/06/2026", "Scope test per role passed"],
            ["M2", "Customer data review timer, 10 working days, overdue signal", "Programming", "C. Demmler", "Development", "11/27/2026", "Timer on intake list"],
            ["M3", "Equipment and gauge completeness (tool link, equipment details)", "Programming", "C. Demmler", "Tooling, Quality", "01/04/2027", "0 gauges without tool"],
            ["M4", "Customer part numbers on all series parts; one mirror per part", "Programming", "C. Demmler", "Development", "12/28/2026", "Completeness list empty"],
            ["M5", "Scheduled database backup and restore test", "Programming", "C. Demmler", "IT", "11/20/2026", "Restore test record"],
            ["M6", "Transfer legacy drive data of active projects", "Programming", "C. Demmler", "Development", "02/12/2027", "Per-project checklist signed"],
            ["T1", "Acceptance test and restore drill", "Testing", "C. Demmler", "Quality, IT", "02/26/2027", "Signed test protocol"],
            ["F1", "Procedure 'Engineering data management in PLM2' released, training", "Finalisation", "C. Demmler", "Quality", "03/19/2027", "Procedure; training per concept (TOC-PLM-01 TR)"],
            ["F2", "Network drives read-only for active projects", "Finalisation", "C. Demmler", "IT", "03/22/2027", "Drive rights changed"],
            ["F3", "Effectiveness review", "Operation", "C. Demmler", "Quality", "04/14/2027", "Review in management review"],
        ]),
        LOP_NOTE,
        ("h1", "7. Control until go-live"),
        ("p", "Until 03/22/2027 the valid revision of a part is the one released in PLM2; files still on drives are reference copies. "
              "New customer data is received in PLM2 only."),
        ("h1", "8. Effectiveness indicators"),
        kpi([
            ["Customer data reviewed within 10 working days", "100 %", "Intake list"],
            ["Parts / tools / gauges with incomplete data", "0 for active projects", "Completeness list"],
            ["Successful restore tests", "1 per quarter", "IT backup log"],
        ]),
    ]})

# ------------------------------------------------------------------ 04
DOCS.append({
    "no": "TOC-PLM-04", "title": "Implementation Plan Lessons Learned", "file": "TOC-PLM-04 Lessons Learned",
    "purpose": "Timing and action plan to capture lessons from projects, changes, problem solving, complaints and audits, "
               "prove their effectiveness and feed them into new projects. Standards: IATF 16949 7.1.6, 10.2.3, 10.3; VDA 6.3 P2.",
    "blocks": [
        ("h1", "1. Summary"),
        ("p", "Lessons learned are **built in PLM2** with owner, actions and a required effectiveness proof before closing. The "
              "SharePoint lessons list (LL-0001 to LL-0019, including ten G6X lessons) is already mirrored. The remaining step is to "
              "**bind lessons into the processes**: checked at SEP RG1/RG2, required at every change release and used as input to "
              "risk assessment. Procedure release is **01/04/2027**."),
        ("h1", "2. Requirements and how they are met"),
        req([
            ["Organisational knowledge (7.1.6)", "Central lessons database, filtered by project, category, department and tag", "Lessons board"],
            ["Problem solving uses lessons learned (10.2.3)", "Lessons carry root cause and recommendation and are linked to the change or project they come from", "Lesson with change link"],
            ["Continual improvement (10.3)", "Status flow with actions; closing needs effectiveness note and verifier", "Closed lesson"],
            ["Lessons from previous projects used (VDA 6.3 P2)", "Lessons check recorded per project and gate", "Lesson reference on project 1994"],
        ]),
        ("h1", "3. Process flow"),
        ("img", "img/flow_ll.png", "Lessons learned flow", 6.0),
        ("b", "Status: in review, in work, verification, closed (or rejected with category). A lesson cannot close while an action is open or without an effectiveness note."),
        ("b", "Stale lessons are flagged: 14 days in review, 7 days in verification; actions appear in the owner's task list."),
        ("b", "Closed lessons update standards (checklists, FMEA, templates) and are checked by the next projects at RG1 and RG2."),
        ("h1", "4. Where we stand today"),
        status([
            ["Lessons with owner, actions, files, comments", "Built", "Lessons board and KPI board"],
            ["Effectiveness proof and verifier before closing", "Built", "Close dialog"],
            ["SharePoint list mirrored (LL-0001..0019)", "Done", "Live system, G6X lessons"],
            ["Lessons step at change release", "Built", "Release tab of a change"],
            ["Lessons check at SEP gates, input to risk / FMEA", "**Programming**", "Actions L2, L4"],
        ]),
        ("h1", "5. Tightening points"),
        tighten([
            ["Lessons also kept in the SharePoint list", "List frozen read-only; PLM2 only", "L1", "10/30/2026"],
            ["Reuse in new projects is voluntary", "Lessons check is a required SEP item at RG1 and RG2", "L2", "11/27/2026"],
            ["Release lessons step can be skipped for small changes", "Lessons step required for every change release", "L3", "11/27/2026"],
            ["Lessons not linked to risk assessment", "Relevant lessons listed in the project risk assessment", "L4", "12/11/2026"],
        ]),
        ("h1", "6. Timing and action plan"),
        ("img", "img/gantt_ll.png", "Lessons learned timing"),
        actions([
            ["L1", "SharePoint lessons list frozen read-only; PLM2 only", "Programming", "C. Demmler", "Program Mgmt., APQP", "10/30/2026", "List locked"],
            ["L2", "Lessons check as required SEP item at RG1 / RG2", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/27/2026", "Item enforced in SEP"],
            ["L3", "Lessons step required at every change release", "Programming", "C. Demmler", "Program Mgmt., APQP", "11/27/2026", "Release blocked in test"],
            ["L4", "Relevant lessons shown in project risk assessment", "Programming", "C. Demmler", "Quality", "12/11/2026", "Risk form shows lessons"],
            ["T1", "Run on 1994 RG2 and the G6X changes", "Testing", "C. Demmler", "Program Mgmt., APQP", "12/18/2026", "References recorded"],
            ["KP", "KPIs (open, to be defined): set targets, sources and review cycle for lessons learned, starting with lesson actions implemented on time", "Finalisation", "C. Demmler", "Quality, Program Mgmt.", "12/18/2026", "KPI set agreed, shown in the monthly review"],
            ["F1", "Procedure 'Lessons learned in PLM2' released", "Finalisation", "C. Demmler", "Quality", "01/04/2027", "Procedure in document control"],
            ["F2", "First quarterly lessons review in management review", "Finalisation", "C. Demmler", "Plant Mgmt.", "01/29/2027", "Minutes filed"],
        ]),
        LOP_NOTE,
        ("h1", "7. Control until go-live"),
        ("p", "Lessons are captured in PLM2 from now on. The SharePoint list stays readable as history until it is frozen (L1)."),
        ("h1", "8. Effectiveness indicators"),
        kpi([
            ["Lessons closed with effectiveness proof", "100 %", "Lessons KPI board"],
            ["New projects with lessons check at RG1 / RG2", "100 %", "SEP matrix"],
            ["Lessons stale beyond flag limits", "0 at monthly review", "Lessons KPI board"],
            ["Lesson actions implemented on time (due date met)", "To be defined (action KP)", "Lessons KPI board, due vs closed date"],
        ]),
        ("p", "The KPI set beyond these indicators is to be defined (action KP): targets, data source in PLM2 and the review "
              "cycle are agreed with Quality and Program Management before the procedure is released."),
    ]})

# ------------------------------------------------------------------ 05
DOCS.append({
    "no": "TOC-PLM-05", "title": "Information Security (TISAX) in PLM2", "file": "TOC-PLM-05 Information Security TISAX",
    "purpose": "How PLM2 protects customer and prototype data in line with the VDA ISA catalogue used for TISAX, and what is still "
               "tightened. KTX Toccoa has no TISAX label and no information security officer yet; IT supports the security "
               "actions. This page records PLM2 so it is ready when a TISAX assessment is scoped.",
    "blocks": [
        ("h1", "1. Controls in place"),
        ("table", [1.55, 3.35, 0.8, 0.9], ["VDA ISA topic", "How PLM2 meets it", "Status", "Action"], [
            ["Asset management, classification (1.3)", "Every project, part and change carries a data classification, default 'confidential'", "Built", "I2"],
            ["Identity management (4.1)", "Sign-in only with the company Microsoft account (Entra ID) through the KTX app hub; leavers lose access with their account", "Built", "-"],
            ["Access management (4.2)", "Role-based rights from directory groups; lists limited to the user's organisation", "**Tightening**", "E1, M1"],
            ["Cryptography (5.1)", "All traffic over HTTPS; server certificate currently self-signed; files not yet encrypted at rest", "**Tightening**", "I1, I5"],
            ["Logging, change tracking (5.2)", "Hash-chained audit trail on changes and parts: who, what, when, old and new value", "Built", "-"],
            ["Operations, backup (5.2)", "On-premises company server in the KTX network; database backed up before every data operation; server login by key, repeated failures blocked", "**Tightening**", "M5"],
            ["Prototype protection (8)", "Customer CAD and prototype data stored in PLM2 only, viewed in the browser", "**Tightening**", "I2, I5"],
        ]),
        ("h1", "2. Tightening actions"),
        actions([
            ["I1", "Trusted company certificate on the PLM2 server (replaces self-signed)", "Programming", "C. Demmler", "IT", "11/13/2026", "Browser shows trusted certificate"],
            ["I2", "Classification drives access: prototype / strictly confidential projects visible to the named project team only; downloads logged", "Programming", "C. Demmler", "IT", "12/11/2026", "Access test per classification"],
            ["I3", "Start an asset list with IT and record PLM2 in it as the system holding customer and prototype data (basis for a future TISAX scope)", "Finalisation", "C. Demmler", "IT", "10/30/2026", "Asset list entry"],
            ["I4", "Quarterly access review per department", "Operation", "C. Demmler", "Department heads", "01/29/2027", "Review record in PLM2"],
            ["I5", "Stored customer files encrypted at rest (AES-256), as already done in RFQ2", "Programming", "C. Demmler", "Program Mgmt., APQP", "01/04/2027", "Encryption test, key handling documented"],
            ["E1 / M1 / M5", "Department rights, access scope, scheduled backup with restore test (see TOC-PLM-01 and -03)", "Programming", "C. Demmler", "IT", "11/20/2026", "See stream documents"],
        ]),
        LOP_NOTE,
    ]})


# ------------------------------------------------------------------ 06 (work instruction)
from content_wi import WI  # noqa: E402
DOCS.append(WI)
from content_rs import RS  # noqa: E402
DOCS.append(RS)
