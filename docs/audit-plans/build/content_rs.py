"""TOC-PLM-07: requirements for project timing from standard blocks (PLM2 + SEP project database).
Same block format as content.py. Findings from G6x Project Timeline (2026-09-30).mpp, read 10/02/2026;
PLM2 facts checked against the code on 10/02/2026. The living trace is docs/project-timing/TRACE.md."""

PILOT = "docs/project-timing/"


def req(rows):
    return ("table", [0.55, 3.35, 2.7], ["No.", "Requirement", "Acceptance (how we test it)"], rows)


AUTH = [
    "C. Demmler, Process Development: owner of PLM2 and of this specification, keeps the trace current",
    "Project Manager of project 1748 (author of the G6x timeline): reviews the blocks, pilot user",
    "Program Management: users of the project timing, sign off the requirements",
    "Quality / APQP: PPAP and capability steps, SEP gate content",
    "Process Engineering, Metrology, Packaging, Toolshop, Production Planning: owners of the steps in the blocks",
]

RS = {
    "no": "TOC-PLM-07", "title": "Requirements: Project Timing from Standard Blocks", "date": "10/02/2026",
    "file": "TOC-PLM-07 Requirements Project Timing", "auth": AUTH,
    "purpose": "Project timelines are built today by copying tasks in MS Project. This specification defines how PLM2 "
               "and the SEP project database generate the timing for project members from standard blocks instead: "
               "the standard steps are defined once, the project only enters its molds, parts, team and anchor dates, "
               "and only project-specific work is planned by hand. It records what the analysis of the G6x timeline "
               "found, the requirements with their acceptance test, what PLM2 already has, and a traceability matrix "
               "from every requirement to its implementation.",
    "blocks": [
        # ------------------------------------------------------------ 1
        ("h1", "1. Starting point: the G6x timeline (analysed 10/02/2026)"),
        ("p", "File: G6x Project Timeline (2026-09-30).mpp, MS Project, 239 tasks, 29 resources, 04/06 to 11/11/2026. "
              "It covers the G45 WHL transfer, three mold engineering changes (3360, 3349, 3369) and ten G67 mold "
              "launches."),
        ("table", [3.2, 0.8, 2.6], ["Pattern", "Rows", "What it really is"], [
            ["G67 mold launch: 9 molds x the same 11 steps (+1 partial)", "~104", "One standard block, applied 9 times"],
            ["Cpk split per characteristic (weight, thickness, SPC 1-6)", "24", "A checklist on one task"],
            ["iPQ elements 0.1 to 5.6, identical dates and owner", "15", "The PPAP / iPQ element checklist"],
            ["ISIR documents (CP, WI, gauge WI, part history, cover sheet)", "~8", "Same checklist"],
            ["Mold changes 3360 / 3349 / 3369", "~55", "Engineering changes (ECR), planned in the project file"],
            ["Really project-specific (BMW vehicle trial, Baxter payment, Hall 52 downtime...)", "~30",
             "The only part that needs hand planning"],
        ]),
        ("h2", "1.1 Findings"),
        ("table", [0.55, 3.4, 2.65], ["No.", "Found in the file", "Consequence"], [
            ["TF-01", "0 of 239 tasks linked, no constraints, no baseline", "Every date typed by hand; a slip moves "
                                                                            "nothing and cannot be measured"],
            ["TF-02", "Molds 3362, 3343, 3352: unpack (08/31 to 09/03) before delivery (09/03)", "Impossible order, "
                                                                                                 "not visible"],
            ["TF-03", "Mold 3376: no TH1; TH2 on the day of gauge validation", "Missing standard step"],
            ["TF-04", "Mold 3362: TH1 on the day of gauge validation", "Dependency not respected"],
            ["TF-05", "Mold 3377: press 1300-2 in some lines, 1300-3 in others", "Copy error"],
            ["TF-06", "Task 5.9.11 named \"TH2\" but is the 30-pc Cpk", "Copy error"],
            ["TF-07", "Same person as 3 resources (holmes / Chrisopher.holmes / christopher.holmes), Rautzenberg 3x, "
                      "a resource named \"Mold 3345: Verify correct AI Level...\"", "Workload per person not usable"],
            ["TF-08", "Cpk and iPQ elements as single rows (39 rows)", "Plan unreadable for the team"],
            ["TF-09", "Mold changes planned as project tasks (~55 rows)", "Duplicates the ECR process in PLM2"],
            ["TF-10", "One 239-line Gantt for everybody", "Team members cannot see their own next tasks"],
        ]),
        ("h2", "1.2 Pilot (built 10/02/2026)"),
        ("p", f"In {PILOT}: **G6x Timing Template.xlsx** (block library, team, inputs, formula-driven plan, findings), "
              "**G67 Timeline (from template).xml** (MS Project, 99 tasks, 72 links, 14 resources) and "
              "**generate.py** (rebuilds both). Per mold only press, part numbers, delivery, gauge validation date "
              "and TH1 trial slot are entered. All 99 Excel dates were checked against the generator: 0 differences. "
              "Against the PM's hand-typed dates 38 of 53 are identical; the 15 others are TF-02, TF-03 and TF-04 "
              "and hand-picked unpack days."),

        # ------------------------------------------------------------ 2
        ("h1", "2. Target concept"),
        ("table", [1.45, 2.6, 2.55], ["Layer", "Content", "Where"], [
            ["What (per gate)", "SEP matrix GB-DP-0001: 7 gates, 232 work items, PM + Quality sign-off",
             "SEP project database (in place)"],
            ["How and when (per mold / part)", "Standard blocks: steps, roles, durations, links, checklists",
             "PLM2 block library (new)"],
            ["Project", "Molds and parts from the PDB, team (role -> person), anchor dates, project-specific tasks",
             "PLM2 project (partly in place)"],
            ["Changes", "Mold engineering changes as ECR with their own plan; the project shows the milestones",
             "PLM2 ECR (in place)"],
        ]),
        ("p", "Principle: nobody copies a task. A standard step exists once in a block; a project gets it by "
              "applying the block to its molds or parts. Improving a block improves every new project."),

        # ------------------------------------------------------------ 3
        ("h1", "3. What PLM2 already has"),
        ("table", [1.6, 2.6, 2.4], ["Component", "Today", "Gap for project timing"], [
            ["Gantt 2.0 engine (plan_engine)", "Links FS/SS/FF/SF with lag, constraints, working calendar, critical "
                                                "path, baseline, progress, idea blocks (bank build)",
             "Runs on change plans only, not on project plans"],
            ["SEP project database", "Template copied per project: 7 gates, 232 items with department, responsible, "
                                     "status, audit trail; gate target date linked to a milestone",
             "Items have no dates, durations or links; no per-mold breakdown"],
            ["Project milestones", "Name, due date, status per project", "No link to tasks"],
            ["Project team (project_responsibles)", "One responsible per role per project, main / backup counting",
             "Roles for Metrology, CMM lab, trial lead, plant layout, toolshop, production planning missing"],
            ["Items (parts)", "Tools, articles, gauges; tool produces article, gauge checks article; planned press "
                              "(tool_machine), cavities, toolmaker", "Tool delivery date not held"],
            ["PPAP submission", "Per part revision: level, customer, 18 elements with status and file",
             "Only the AIAG element set; VDA iPQ set missing"],
            ["ECR change plan", "Stages 4-8 timing per change with the same engine", "No standard plan template"],
            ["Control plan characteristics", "Not in PLM2", "Needed for the Cpk checklist"],
        ]),

        # ------------------------------------------------------------ 4
        ("h1", "4. Requirements"),
        ("h2", "4.1 Block library"),
        req([
            ["TR-01", "A block is master data: steps with ID, name, role, duration in workdays, dependency (FS/SS/FF, "
                      "lag), mandatory/optional, checklist and SEP item reference. Blocks are created and edited in "
                      "PLM2 without code changes.",
             "The three pilot blocks LAUNCH, MOLDCHG, PPAP are entered in PLM2 and match the Excel pilot"],
            ["TR-02", "Each block has an owner, a version and a status (draft / released). Changes are audited. A "
                      "plan keeps the block version it was generated from; a new version reaches a running plan only "
                      "when the PM applies it.", "Release v2 of LAUNCH: existing G67 plan unchanged until applied"],
            ["TR-03", "Steps name roles, never persons. The role list is the project-team role list, extended by the "
                      "roles the blocks need (decision D-01).", "No person is stored in any block"],
            ["TR-04", "A step carries a checklist instead of extra rows. A checklist can be fixed text or come from "
                      "data: control plan characteristics (TR-16), customer PPAP element set (TR-15).",
             "G67 Cpk task shows weight, thickness, SPC 1-n of that part; 0 rows per characteristic"],
        ]),
        ("h2", "4.2 Generating the plan from the PDB"),
        req([
            ["TR-05", "A block is applied to items of a project: LAUNCH per tool, PPAP per part family, MOLDCHG per "
                      "ECR. Task names come from the block and the item (press from the planned press, part numbers "
                      "from the produces relation).", "Select the 9 G67 tools -> 99 tasks, names as in the pilot"],
            ["TR-06", "Per item only anchor dates are entered (e.g. delivery, gauge validation, trial slot). All other "
                      "dates are calculated on the plant's working calendar with holidays.",
             "G67 dates equal the Excel pilot (99 of 99)"],
            ["TR-07", "Project-specific tasks are added by hand next to the generated ones and can be linked to them.",
             "BMW vehicle trial linked after TH2 of mold 3349 moves with it"],
            ["TR-08", "Items can be added or dropped later: a new tool gets its block without touching the others; a "
                      "dropped one is cancelled with a reason, not deleted.", "Add a 10th tool to G67: 11 new tasks, "
                                                                              "others unchanged"],
        ]),
        ("h2", "4.3 Scheduling and tracking"),
        req([
            ["TR-09", "Project plans use the Gantt 2.0 engine: links, constraints, critical path. A moved date moves "
                      "its successors; nobody types successor dates.", "Delay one delivery by 5 workdays: every "
                                                                        "successor moves 5 workdays"],
            ["TR-10", "Logic checks warn about impossible order (unpack before delivery, trial before gauge) and "
                      "missing mandatory steps; dropping a mandatory step needs a reason.",
             "TF-02, TF-03, TF-04 are flagged when the G6x data is entered"],
            ["TR-11", "A baseline is set when the plan is released. Progress and actual dates are recorded per task; "
                      "slip against the baseline is visible per task and item.", "Baseline + one late task shows its "
                                                                                 "slip in workdays"],
            ["TR-12", "After the baseline, moving a date asks for a reason; the change is audited (who, when, old, "
                      "new, reason).", "Audit list shows the move with reason"],
        ]),
        ("h2", "4.4 Integration with SEP, ECR and PPAP"),
        req([
            ["TR-13", "Each block step references one or more SEP work items (proposal in section 5). The SEP item "
                      "shows the progress of its tasks over all items of the project; when all are done, closing the "
                      "item is proposed to its responsible.", "SEP item \"Assessment of short-term capabilities CP "
                                                               "and CPK\" shows 9 of 9 Cpk tasks"],
            ["TR-14", "SEP gate target dates are checked against the block milestones; a block milestone after its "
                      "gate target is flagged.", "Move gate B/RG6 before the last Cpk: warning"],
            ["TR-15", "Mold engineering changes run as ECR; MOLDCHG is the standard template of the change plan. The "
                      "project timing shows only the ECR milestones, read-only, linked to the change.",
             "G6x sections 2-4 = 3 ECRs and 0 copied rows in the project plan"],
            ["TR-16", "Control plan characteristics per article are held in the PDB (characteristic, type: weight / "
                      "thickness / SPC, special characteristic flag) and feed the Cpk checklists.",
             "Article 5A65DF8 shows its characteristics; its Cpk task lists them"],
            ["TR-17", "The PPAP block's checklist is the PPAP submission's element list; the element set follows the "
                      "customer (AIAG 18 elements or VDA iPQ).", "BMW part shows the iPQ list of the G45 file"],
        ]),
        ("h2", "4.5 Views and output"),
        req([
            ["TR-18", "\"My tasks\" per person: tasks of the roles they hold on each project team, next 2-3 weeks, "
                      "with main / backup counting as for ECR tasks.", "Metrology sees only gauge tasks, by date"],
            ["TR-19", "PM view: Gantt per project, filters by item, role, block; exception list (late, at risk, "
                      "missing person for a role).", "G67 filtered to mold 3355 shows its 11 steps"],
            ["TR-20", "Exchange with MS Project: export as MS Project XML with links and resources (as the pilot).",
             "Export opens in MS Project with links intact"],
            ["TR-21", "KPIs: milestones on time (e.g. TH1, mold ready for PPAP, PPAP approval) with the calendar-day "
                      "rule of the ECR KPI board.", "KPI board shows on-time rate per milestone type"],
        ]),
        ("h2", "4.6 Rights"),
        req([
            ["TR-22", "The project PM edits the project plan; block library editing only by block owners and admins; "
                      "team members report progress on their own tasks.", "Team member cannot move another role's task"],
        ]),

        # ------------------------------------------------------------ 5
        ("h1", "5. Block steps against SEP work items (proposal, to confirm in the workshop)"),
        ("table", [0.55, 2.2, 3.85], ["Step", "Block step", "SEP work item (gate, no.)"], [
            ["L01", "Assign location in plant layout", "Determine space requirements including layout (K/RG2 31, "
                                                       "D/RG4 10, D/RG4 14)"],
            ["L04", "Gauge validation", "Create and release specifications (gauges) (E/RG3 25)"],
            ["L06", "Complete work instructions", "Create / revise test and work instructions (K/RG2 24, E/RG3 26)"],
            ["L08", "Packaging trial / instruction", "Determining and implementing the packaging and logistics concept "
                                                     "(K/RG2 33)"],
            ["L09", "6-pc dimensional (CMM)", "Create measurement orders, evaluate measurement reports (C/RG5 17)"],
            ["L10", "30-pc Cpk", "Start capabilities (C/RG5 15); assessment of short-term capabilities CP and CPK "
                                 "(B/RG6 18)"],
            ["L11", "Mold ready for PPAP", "Start handover of series tools to the production plant (B/RG6 27)"],
            ["P02", "ISIR / iPQ package", "Initial sampling customer grade 3 (B/RG6 21); grade 1 (A/RG7 6)"],
            ["P04", "Full PPAP approval", "Assessment of long-term capabilities (A/RG7 7)"],
            ["E01-E13", "Mold engineering change", "Change management items (Sales, every gate) -> runs as ECR"],
        ]),

        # ------------------------------------------------------------ 6
        ("h1", "6. Steps and timing (proposal)"),
        ("table", [0.5, 3.4, 1.4, 1.3], ["No.", "Step", "Who", "Due"], [
            ["S1", "Pilot: use the Excel / MS Project template for the open G67 launches", "C. Demmler, PM 1748",
             "10/16/2026"],
            ["S2", "Block workshop: steps, durations, roles, SEP mapping (section 5), decisions D-01 to D-05",
             "PM 1748, Quality, Process Eng.", "10/30/2026"],
            ["S3", "Review and sign-off of this specification", "Program Mgmt., Quality", "11/13/2026"],
            ["S4", "Phase 1: block library, generation, engine on project plans, baseline (TR-01..12, TR-22)",
             "C. Demmler", "02/26/2027"],
            ["S5", "Phase 2: SEP link, ECR milestones, control plan characteristics, PPAP element sets, my tasks "
                   "(TR-13..18)", "C. Demmler", "04/30/2027"],
            ["S6", "Phase 3: PM view and exceptions, MS Project export, KPIs (TR-19..21)", "C. Demmler", "06/25/2027"],
            ["S7", "Acceptance: rebuild G67 in PLM2 and compare with the pilot; first new project planned only in "
                   "PLM2", "PM 1748, C. Demmler", "07/30/2027"],
        ]),
        ("p", "Phase 1 starts after the ECR go-live on 12/21/2026, so the ECR rollout is not delayed."),

        # ------------------------------------------------------------ 7
        ("h1", "7. Open decisions"),
        ("table", [0.55, 4.3, 1.75], ["No.", "Decision", "Who"], [
            ["D-01", "Role list: extend the project team by Metrology, CMM lab, trial lead, plant layout, toolshop, "
                     "production planning, or map them to existing roles", "Program Mgmt., Quality"],
            ["D-02", "Which block steps are mandatory (cannot be dropped without a reason)", "Workshop S2"],
            ["D-03", "SEP item closing: proposed to the responsible (default) or automatic", "Quality"],
            ["D-04", "Owner of the block library: Program Management or Process Development", "Program Mgmt."],
            ["D-05", "MS Project after go-live: export only, or also import", "PM 1748"],
        ]),

        # ------------------------------------------------------------ 8
        ("h1", "8. Traceability matrix (status 10/02/2026)"),
        ("p", "Every requirement is traced to where it comes from, what PLM2 already has and the evidence of its "
              "implementation. Every implementation commit names its TR number; the living copy is "
              "docs/project-timing/TRACE.md and this table is updated from it at each revision."),
        ("table", [0.55, 1.1, 2.15, 0.9, 1.9], ["No.", "From", "PLM2 basis", "Status", "Evidence"], [
            ["TR-01", "TF-08, pilot", "-", "Pilot", "Blocks sheet, generate.py"],
            ["TR-02", "Concept", "Audit pattern of SEP items", "Open", ""],
            ["TR-03", "TF-07", "project_responsibles", "Partial", "Team sheet; D-01 open"],
            ["TR-04", "TF-08", "-", "Pilot", "Checklist column (text)"],
            ["TR-05", "Pilot", "Items, produces relation, tool_machine", "Pilot", "Plan sheet, 99 tasks"],
            ["TR-06", "TF-01", "plan_engine calendar", "Pilot", "99 of 99 dates verified 10/02"],
            ["TR-07", "Section 1", "Change plan free tasks", "Open", ""],
            ["TR-08", "Concept", "-", "Open", ""],
            ["TR-09", "TF-01", "plan_engine (change plans)", "Partial", "MS Project XML: 72 links"],
            ["TR-10", "TF-02..04", "plan_engine validation warnings", "Partial", "Pilot plans TH1 after gauge"],
            ["TR-11", "TF-01", "plan_engine baseline, progress", "Partial", ""],
            ["TR-12", "Concept", "Release deadline move with reason (F-02)", "Partial", ""],
            ["TR-13", "Concept", "SEP work items", "Partial", "Mapping proposal, section 5"],
            ["TR-14", "Concept", "SEP gate target date", "Partial", ""],
            ["TR-15", "TF-09", "ECR change plan", "Partial", "MOLDCHG block defined"],
            ["TR-16", "TF-08", "-", "Open", ""],
            ["TR-17", "TF-08", "PPAP submission (AIAG)", "Partial", "iPQ list in PPAP block"],
            ["TR-18", "TF-10", "My Tasks (ECR), main/backup", "Partial", ""],
            ["TR-19", "TF-10", "Gantt 2.0 UI (change plans)", "Partial", ""],
            ["TR-20", "Pilot", "-", "Pilot", "G67 Timeline (from template).xml"],
            ["TR-21", "Concept", "ECR KPI board", "Partial", ""],
            ["TR-22", "Concept", "Project team rights", "Partial", ""],
        ]),
        ("p", "Status: Open = nothing yet; Partial = PLM2 has the basis, the timing function is missing; Pilot = "
              "proven in the Excel / MS Project pilot, not in PLM2; Done = in PLM2 and the acceptance test passed."),
    ],
}
