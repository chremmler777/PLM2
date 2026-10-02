"""TOC-PLM-06: work instruction for the ECR simulations by Project Management.
Same block format as content.py. Facts checked against the PLM2 code on 10/01/2026
(labels are the exact English UI texts)."""

SIM_FROM, SIM_TO, FINDINGS_DUE, REVIEW = "10/05/2026", "10/16/2026", "10/16/2026", "10/20/2026"
LOG = "TOC-PLM-06 ECR Simulation Findings Log.xlsx"


def steps(rows):
    return ("table", [0.45, 1.05, 2.95, 2.15], ["No.", "Act as", "Where / what you do", "Expected result (check)"], rows)


AUTH = [
    "C. Demmler, Process Development: owner of PLM2 and of this instruction; prepares the test project and accounts, "
    "collects and answers every finding",
    "Project Management: run the simulations in pairs and record every finding in the findings log",
    "Department members (Sales, Development, Quality, Scheduling, Tool Engineer, APQP): informed that simulations run "
    "and that test notifications marked SIM can be ignored",
]

WI = {
    "no": "TOC-PLM-06", "title": "Work Instruction: ECR Simulation in PLM2", "file": "TOC-PLM-06 Work Instruction ECR Simulation",
    "auth": AUTH,
    "purpose": "Project Managers run engineering changes (ECR) end to end in PLM2 as a simulation, before the go-live on "
               "12/21/2026. The instruction shows how to play every department with the admin picker (\"Act as\"), how to "
               "start both types of change, how to run the timing, and how to check the Process Flow page against what "
               "the system really does. Every bug, missing function or wrong text goes into the findings log, so that "
               f"it is fixed before go-live. Simulation window {SIM_FROM} to {SIM_TO}; findings due {FINDINGS_DUE}.",
    "blocks": [
        # ------------------------------------------------------------ 1
        ("h1", "1. Before you start"),
        ("h2", "1.1 What is prepared"),
        ("table", [0.45, 4.25, 1.9], ["No.", "Preparation", "Status"], [
            ["P1", "Every PLM2 editor signs in through the hub as plm2_Admin, so every tester has the admin picker "
                   "(sidebar, above \"Notifications\")", "In place"],
            ["P2", "**Test Project** (test-project, plant USA Toccoa) holds 13 SIM items: tools 9901 to 9904, molded "
                   "parts 20-9901-001-0 to 20-9904-002-0 (door trim carrier LH/RH, map pocket LH/RH, grille carrier, "
                   "bracket 40/60) and the door trim assemblies 10-9901-001-0 / -002-0 with their BOM. All in series, "
                   "revision 1", "Done 10/01/2026"],
            ["P3", "Test Project has no project PM on purpose: you set yourself as change lead (step A2). No real "
                   "person is a department member in PLM2, so SIM tasks and notifications reach nobody else",
             "In place"],
            ["P4", "Fixes F-01 to F-04 (internal changes), the corrected Process Flow page and the ECR KPI board on "
                   "the live system. F-06 (ECN check departments) is already live",
             "With the next deployment, before " + SIM_FROM],
            ["P5", f"Findings log **{LOG}** in the shared folder", "Link sent to the testers"],
        ]),
        ("h2", "1.2 Rules for every simulation"),
        ("b", "**Work in pairs.** The admin picker changes your department, never your person. Steps that need two "
              "different people (approving a deviation, PM sign-off plus Quality sign-off) refuse the same account. "
              "Person A runs the change, person B approves and signs the second signature."),
        ("b", "**Only in Test Project.** Never simulate on a real project: the change, its notifications and its "
              "deadlines are real records."),
        ("b", "**Two impacted items per change.** Every impacted item gets its own check workflow at implementation "
              "(4 stages, about 18 tasks per item). Two items show everything; four double the clicking."),
        ("b", "**Short description starts with SIM and your initials**, for example \"SIM-CD-1 grille carrier rib "
              "change\". Then everybody can see it is a test."),
        ("b", "**One browser tab per change.** The picker is remembered per tab. After opening a new tab, check the "
              "purple \"Acting as\" banner before you click anything."),
        ("b", "**Record as you go.** Write a finding the moment something is wrong, unclear or slow (section 9). "
              "Take a screenshot (Windows: Win+Shift+S) and note the change number and step number."),
        ("b", "**Finish or cancel.** At the end every SIM change is closed, or cancelled with \"Cancel change…\" "
              "and the reason \"Simulation\", so that it does not stay in anybody's task list."),
        ("p", "This document is the reference for the simulations. You can act without a training sign-off."),

        # ------------------------------------------------------------ 2
        ("h1", "2. The admin picker (\"Act as\")"),
        ("p", "With the picker an admin works as a member of one department, for example Sales to capture a change and "
              "Development to confirm the impact. This lets one person walk a change through every stage."),
        ("img", "img/wi_actsas.png", "Admin picker in the sidebar", 1.9),
        ("table", [1.7, 4.9], ["", "How it works"], [
            ["Where", "Bottom of the left sidebar, above \"Notifications\". Only admins see it."],
            ["Pick a department", "Open the dropdown, choose the department. The page reloads and a purple banner reads "
                                  "\"Acting as: <department>\"."],
            ["Back to yourself", "Click the ✕ on the banner (\"Stop acting as\") or choose \"Myself (admin)\". The page reloads."],
            ["What you can pick", "Departments only, never a person."],
            ["What changes", "You have exactly the rights of a member of that department: the admin rights and your own "
                             "department memberships are switched off, and so are your rights as change lead. \"My "
                             "Tasks\" and \"Your actions\" show what that department owes."],
            ["What does not change", "You stay the same person. Two-person rules still see you (section 1.2). "
                                     "Notifications to a department reach its real members, not you."],
            ["Audit trail", "Every action records both: your name and the department you acted as."],
        ]),
        ("h2", "2.1 Who does what: the department to pick per step"),
        ("table", [2.6, 4.0], ["Step", "Act as"], [
            ["Start a customer change, quote deadline, offer, customer answer, publish plan", "Sales"],
            ["Start a change from KTX Weissenburg / Solingen", "Project Manager"],
            ["Pick the change lead (Status card \"Pick a lead\"), scoping meeting, close assessment / costing, PM "
             "sign-off, internal approval, release, close", "Project Manager"],
            ["Priority (only the change lead sets it)", "**Myself (admin)**: acting drops the lead right"],
            ["Pick and confirm the impacted items (\"Confirm impact (Development)\")", "Development (no admin shortcut)"],
            ["Assessment, cost input, timing confirmation of a department", "That department (each R or A department)"],
            ["Part weight estimate (costing) and measured weight (validation)", "Tool Engineer"],
            ["Quality sign-off", "Quality (**person B**, the PM sign-off is person A)"],
            ["Bank build decision (running change or planned scrap)", "Scheduling"],
            ["Approve a deviation someone else asked for", "**Person B**, as \"Myself (admin)\""],
            ["D1 gate \"Technical release?\" before implementation", "**Myself (admin)**: while acting the D1 tab "
             "shows the gates read-only and says so"],
            ["ECN check tasks at implementation: \"Design review\" (stage 2)", "The other person of the pair: the "
             "stage before was decided by you (four eyes)"],
            ["ECN check stage 3: \"Implement tool change\" / \"Update master data & logistics\"", "Process "
             "Engineer (Tool Engineer accountable) / Scheduling (PM accountable)"],
        ]),

        # ------------------------------------------------------------ 3
        ("h1", "3. The two types of engineering change"),
        ("p", "Changes are started on the Changes page with **\"New Change Request\"** (Sales or Project Manager), or with "
              "\"Start change request\" on a part, tool or project page. Under \"Who carries the cost?\" the form offers "
              "the type."),
        ("img", "img/wi_newchange.png", "New change request form", 2.9),
        ("table", [1.25, 2.7, 2.65], ["", "Type 1: Customer change", "Type 2: Change from KTX Weissenburg / Solingen"], [
            ["Who starts it", "Sales or Project Manager", "Project Manager only (Sales sees \"started by Project Management\")"],
            ["Stages", "Captured, Scoping, In assessment, Costing, Quote creation, Quoted, Timing (approved), "
                       "Implementing, Validation, Released, Closed",
             "Captured, Scoping, Timing (approved), Implementing, Validation, Released, Closed: **no assessment, "
             "no costing, no offer**"],
            ["Deadline 1", "**Quote deadline**: when the customer expects the offer (RFQ submission date). Needed "
                           "before scoping and again before the assessment", "none"],
            ["Deadline 2", "**Release deadline**: entered with \"Customer accepted\"",
             "The plant's **SOP date** becomes the release deadline at approval"],
            ["Approval", "Customer accepted + PM sign-off + Quality sign-off (two different people)",
             "Impacted set locked, the team informed (\"Send information to the team\"), SOP date set"],
            ["Timing", "Quote plan in the offer, then the detailed plan", "Detailed plan from the plant's MS Project "
                                                                        "file (.xml), or starting from the SOP"],
            ["Customer", "\"Publish plan to customer\" (Sales)", "\"Inform <plant>\" after validating the timing"],
        ]),
        ("p", "**Internal change** (the plant pays, no customer) is the third choice in the form, switched on 10/01/2026 "
              "(F-04). It runs like a customer change up to costing; then the Project Manager approves the internal "
              "costs with the release deadline (tab \"Approval\", \"Approve internal costs\") instead of an offer. No "
              "quote deadline, no offer, no publish to the customer. The scoping meeting can still turn a change "
              "internal or customer through the cost carrier. Simulation C1."),

        # ------------------------------------------------------------ 4
        ("h1", "4. Simulation A: customer change, start to close"),
        ("p", "Scenario: the customer asks for an additional rib on a part of Test Project and expects the quote in 10 days. "
              "Person A runs it, person B signs Quality and approves deviations. Work through the steps in order; tick "
              "each check. The cockpit at the top of the change (\"Your actions\", \"Status\", \"Blocked by\", \"Next "
              "step\") always says what is missing, compare it with this table."),
        ("img", "img/wi_overview.png", "Change cockpit", 5.2),
        ("h2", "4.1 Capture and scoping"),
        steps([
            ["A1", "Sales", "Changes → \"New Change Request\". Project \"test-project · Test Project\". Affected items: "
                            "search and pick 2 parts of the same tool (the first is the lead item). Short description "
                            "\"SIM-<initials>-A additional rib\". \"Customer change\". Description. Quote deadline today + 10 "
                            "days. Drop one file (any PDF) as customer document. \"Create change\".",
             "Change CR-… in Captured. Title built automatically from the lead item, e.g. \"20-9901-001-0 +1 - "
             "SIM.867.011 - SIM DOOR TRIM CARRIER LH\". \"No lead assigned\" (Test Project has no PM). The "
             "orange \"Not ready…\" box was empty before creating"],
            ["A2", "Project Manager, then Sales", "Try \"Hand over to scoping\" as Sales first. Then, as Project "
                                                  "Manager, Status card: \"Pick a lead\" → yourself. Then, as Sales, "
                                                  "\"Hand over to scoping\" again.",
             "Without a lead the hand-over is refused (\"missing change lead before scoping\"). With it: status "
             "Scoping, stage owner PM, \"Quote in 10 d\" on the Status card"],
            ["A3", "Myself (admin), then Project Manager", "As change lead: \"Priority\" High (Status card). Then "
                                                           "as Project Manager: \"Push back\" on the quote deadline "
                                                           "by 2 days, first without a reason.",
             "Acting as Project Manager the priority is refused: only the lead or an admin sets it. Push back is "
             "refused without a reason; with it the reason shows under the chip and on the Audit tab"],
            ["A4", "Development", "Tab \"Impacted\": the two carriers are listed. The tree suggests the two door "
                                  "trim assemblies: leave them out (rule in 1.2). \"Confirm impact (Development)\".",
             "\"Impact confirmation pending\" disappears from \"Blocked by\""],
            ["A5", "Project Manager", "Tab \"Scoping\": \"+ Record a meeting\". Channel Meeting, date today, "
                                      "participants. Departments: Tool Engineer R, Development A, APQP S, Manufacturing "
                                      "Engineer C, Packaging not involved. Cost carrier \"Customer (customer relevant)\". "
                                      "\"Save meeting\".", "Meeting listed with the letters"],
            ["A6", "Project Manager", "On the meeting row \"Proceed & start assessment\" → \"Start assessment\".",
             "Status In assessment. Tool Engineer and Development get an assessment task in My Tasks"],
        ]),
        ("img", "img/wi_scoping.png", "Scoping tab with the meeting decision", 5.0),
        ("h2", "4.2 Assessment and costing"),
        steps([
            ["A7", "Tool Engineer", "My Tasks → \"Assess\". Checklist, verdict \"Feasible with conditions\", effort "
                                    "8 h, a condition. \"Submit assessment\".", "Assessment shows submitted; cockpit "
                                                                               "\"Waiting on 1 department\""],
            ["A8", "Development", "Same, verdict \"Feasible\". In your department's block on the Assessments tab: "
                                  "\"+ Flag\", kind Risk, with type and severity (risks are raised during the "
                                  "assessment only).",
             "Risk visible in the risk register; it does not block"],
            ["A9", "Project Manager", "\"Close assessment\". Read the confirm dialog.", "Status Costing; dialog lists "
                                                                                       "every verdict and the open risk"],
            ["A10", "Tool Engineer", "Tab \"Costing\", own block: \"+ Activity\" 8 h, \"Lead time (days)\" 15, "
                                     "\"Part weight (g)\" estimate. One costing position (vendor quote) with an amount.",
             "Block shows Filled; cost summary updates"],
            ["A11", "Development, APQP", "Price their blocks the same way (a department that has no cost enters 0 h "
                                         "with a note).", "Header counter of departments still to cost matches the "
                                                          "list on the Costing tab (see finding F-01)"],
            ["A12", "Project Manager", "\"Close costing\".", "Status Quote creation (Quoting)"],
        ]),
        ("img", "img/wi_costing.png", "Costing tab", 4.4),
        ("h2", "4.3 Offer, customer answer and approval"),
        steps([
            ["A13", "Sales", "Tab \"Offer\": \"Start the offer\". Timing: the quote plan (section 6.1), \"Include in "
                             "offer\". Price, risks, document. \"Send offer\", \"Received by the customer on\" today.",
             "Status Quoted. Status card: quoted on time"],
            ["A14", "Sales", "Negotiation: \"Customer accepted\", Release deadline today + 60 days, \"Confirm "
                             "acceptance\".", "Status card switches from the quote deadline to the release deadline"],
            ["A15", "Project Manager (A)", "\"PM sign-off\".", "PM sign-off ✓"],
            ["A16", "Quality (**B**)", "\"Quality sign-off\". Test first: person A acting as Quality must be refused.",
             "A refused with a clear message; B accepted"],
            ["A17", "Project Manager", "\"Record approval\".", "Status Timing (approved); Timing tab unlocked"],
        ]),
        ("h2", "4.4 Timing, implementation, validation, release"),
        steps([
            ["A18", "PM / departments", "Detailed plan, team confirmation and \"Validate timing\" as in section 6.2.",
             "Timing validated; baseline set"],
            ["A19", "Scheduling", "\"Bank build plan\": \"Running change\", plan note, save.", "Decision shown"],
            ["A20", "Sales", "\"Publish plan to customer\".", "Published stamp with name and date"],
            ["A21", "Myself (admin)", "Tab \"D1\" → \"Final assessment\" → \"Technical release?\" = Yes. Look at "
                                     "the tab once while acting as a department first.",
             "Gate answered. While acting the gates show read-only with the hint \"Stop acting as a department to "
             "decide\" (F-03)"],
            ["A22", "Project Manager", "\"Start implementation\".", "Status Implementing; revision 1.1 created "
                                                                  "for each impacted item, each with its check "
                                                                  "workflow (My Tasks: \"View part\")"],
            ["A23", "Project Manager", "Move one plan block by 3 days with a reason (section 6.3) and leave the "
                                      "deviation open.", "One deviation group: the moved block and every block it "
                                                        "pushed, status open. The work goes on"],
            ["A24", "Development, then the pair", "Each revision's check workflow, 4 stages. Stage 1 (Development): "
                                                  "on the part page give revision 1.1 its 3D evidence: upload the CAD, "
                                                  "or \"No geometry change\" with a reason; then approve both steps. "
                                                  "Stage 2 \"Design review\" (Development, Quality): the other person. "
                                                  "Stage 3 (Manufacturing Engineer, Process Engineer, Project Manager, "
                                                  "Quality, Scheduling, Tool Engineer). Stage 4 (Project Manager, "
                                                  "Quality).",
             "Without 3D evidence stage 1 refuses: \"3D evidence required\". The same person on stage 2 is "
             "refused (four eyes). Afterwards every revision completed"],
            ["A25", "Project Manager", "\"Finish implementation\".", "Status Validation even with the open "
                                                                   "deviation of A23; Release tab unlocked"],
            ["A26", "Tool Engineer, Development", "Release tab, validation checks \"Pass\": Tool Engineer: tool "
                                                 "sampled, part measured, measured cycle time (s), \"Measured weight "
                                                 "(g)\" 5 % above the estimate; Development: revision level raised.",
             "\"Quote update required…\" appears for Sales"],
            ["A27", "Sales", "\"Acknowledge\" the weight delta with a note.", "Note stored with name"],
            ["A28", "Departments, then Project Manager", "Release checklist: each department marks its rows "
                                                        "Done or N.a. with a note (Development, Tool Engineer, APQP, "
                                                        "Packaging Engineer, Scheduling, Sales; cycle time: changed or "
                                                        "unchanged). \"+ Add lesson\", \"Complete lessons step\". "
                                                        "\"Release change\". Then lock the deviation (6.3) and release "
                                                        "again.",
             "First release refused: \"plan deviations still open: lock or escalate them first\". After Lock: "
             "status Released"],
            ["A29", "Project Manager", "Read the summary (plan against actual, offer against cost), then \"Close change\".",
             "Status Closed; everything read-only"],
        ]),

        # ------------------------------------------------------------ 5
        ("h1", "5. Simulation B: change from KTX Weissenburg / Solingen"),
        ("p", "Scenario: KTX Weissenburg changed a tool on their side; we take over the change for our parts and follow "
              "their timing. Use any MS Project file (.xml) you have, or leave it empty (then the plan starts from the SOP)."),
        ("img", "img/wi_newchange_mp.png", "Fields of a change from Weissenburg / Solingen", 3.3),
        steps([
            ["B1", "Project Manager", "\"New Change Request\", Test Project, 1 to 2 parts, short description "
                                      "\"SIM-<initials>-B …\", **\"Change from KTX Weissenburg / Solingen\"**. Plant WUG, "
                                      "their reference, SOP date today + 45 days, their timing (.xml) and documents, "
                                      "description. \"Create change\".", "Change in Captured; tab \"KTX Weissenburg\" "
                                                                        "instead of Assessments / Costing / Offer"],
            ["B2", "Sales", "Try \"New Change Request\" as Sales.", "The plant option is not offered (only PM)"],
            ["B3", "Project Manager", "Status card: \"Pick a lead\" → yourself, then \"Hand over to scoping\".",
             "Status Scoping. Without a lead the hand-over is refused (\"missing change lead before scoping\")"],
            ["B4", "Development", "Impacted: \"Apply selection\", \"Confirm impact (Development)\".", "Impact confirmed"],
            ["B5", "Project Manager", "Scoping meeting with \"Departments to inform\" (no RASIC letters, no cost carrier).",
             "Meeting saved"],
            ["B6", "Project Manager", "Tab \"KTX Weissenburg\": tick the departments, write what each has to do, "
                                      "\"Send information to N departments\".", "Departments get the information task; "
                                                                               "\"Blocked by\" clears"],
            ["B7", "Each informed department", "Acknowledge the information (My Tasks).", "Receipts shown on the tab"],
            ["B8", "Project Manager", "\"Record approval\" (cockpit). Read the confirm dialog.",
             "Status Timing (approved). Release deadline = SOP date. Detailed plan seeded from their file"],
            ["B9", "PM / departments", "Timing as in section 6.2 (confirmation by informed departments + Scheduling), "
                                       "then \"Inform KTX Weissenburg\".", "Inform stamp; no \"Publish to customer\""],
            ["B10", "", "Implementation, validation, release, close as A21 to A29.", "Same as Simulation A"],
        ]),
        ("img", "img/wi_mp.png", "Plant tab: inform the team", 4.6),

        # ------------------------------------------------------------ 6
        ("h1", "6. Timing in detail"),
        ("h2", "6.1 Quote plan (customer change, from costing until the customer accepts)"),
        ("b", "Offer tab, section \"Timing\". An empty plan offers **\"Seed from costing\"** (takes every department's "
              "lead time and hours), \"+ Add a task\" or \"Import MS Project\"."),
        ("b", "Toolbar: \"+ Buffer\", \"+ Bank build idea\", \"Align\", \"Lanes\". Menu \"More\": \"Auto-schedule now\", "
              "\"Calendar…\", \"Open in new window\", \"Seed again from costing\"."),
        ("b", "\"Plan calendar\": working days or calendar days, holidays, automatic scheduling. Check that a block "
              "over a weekend gets longer in working-day mode."),
        ("b", "An offer that includes timing cannot be sent while the plan is empty or shows errors."),
        ("b", "Check: \"Weeks from order\" in the offer matches the end of the plan."),
        ("h2", "6.2 Detailed plan (after approval)"),
        ("table", [0.45, 1.25, 2.85, 2.05], ["No.", "Act as", "Where / what you do", "Expected result (check)"], [
            ["T1", "Project Manager", "Tab \"Timing\": \"Create detailed plan from quote plan\".",
             "Every block of the quote plan copied, links included"],
            ["T2", "Project Manager", "Refine: real durations, owners, links. \"Open in new window\" and edit there.",
             "Main window follows the pop-out without reload"],
            ["T3", "Every department in the panel", "\"Team confirmation\" → \"Confirm timing\" for every "
                                                    "department the panel lists (here Development, Tool Engineer, "
                                                    "Project Manager, Sales, Scheduling). One of them: \"Raise "
                                                    "concern\" with a note.",
             "Counter \"n of m confirmed\"; the concern blocks validation"],
            ["T4", "Project Manager", "Fix the plan for the concern, ask again; that department confirms.",
             "Earlier confirmations marked \"Plan changed after this confirmation\""],
            ["T5", "Everyone stale", "Confirm the current plan again.", "All current"],
            ["T6", "Project Manager", "\"Validate timing\". Before: try it with one confirmation missing.",
             "Refused with the departments still missing; afterwards baseline set. A warning that the plan ends "
             "after the release deadline is information, not a block"],
        ]),
        ("h2", "6.3 After the baseline: tracking and deviations"),
        ("b", "Every date move becomes a deviation with reason, slip and effect on the finish. Blocks pushed along "
              "by a move form one group and take one decision."),
        ("b", "**\"Lock\"** / **\"Lock all N\"**: accepted internally (no customer impact). **\"Escalate to customer\"**: "
              "Sales tells the customer."),
        ("b", "**An open deviation blocks the release.** Test it: leave one open, try \"Release change\" (expected: "
              "blocked, \"Release with a deviation\")."),
        ("b", "Moving the release deadline itself: Status card \"Move\". It asks why, and refuses without a reason "
              "(F-02, fixed): it is the date the customer was promised and the KPI \"implemented on time\" uses it."),
        ("b", "Timing tab buttons \"Export to MS Project\" and \"Export as CSV\": open the XML in MS Project and compare."),

        # ------------------------------------------------------------ 7
        ("h1", "7. Simulation C: variants (one each, short)"),
        ("table", [0.45, 2.1, 2.3, 1.75], ["No.", "Variant", "How", "Expected"], [
            ["C1", "Internal change", "\"New Change Request\" → \"Internal change\" (no quote deadline). After "
                                      "costing, tab \"Approval\": \"Approve internal costs\" with the release deadline "
                                      "(Project Manager), then \"Record approval\". Also try: a customer change turned "
                                      "internal at the scoping meeting.",
             "No quote, no offer; costing goes to approved. Sales is refused the approval"],
            ["C2", "Needs more info", "Scoping meeting decision \"Needs more info\" with a question. Sales answers with "
                                      "a customer mail.", "Sales task \"Obtain info from customer\"; change stays in "
                                                          "scoping"],
            ["C3", "Not feasible", "One department submits \"Not feasible\" (needs the change PPT).",
             "Cockpit offers \"Reject change\", \"Back to scoping\", \"Override with a reason\""],
            ["C4", "Rejection", "\"Reject change\" with reason. Sales \"Send rejection letter\".",
             "Cannot close without letter; closes after \"sent\""],
            ["C5", "Reopen", "On a rejected change \"Reopen change\" with reason.", "Back in scoping"],
            ["C6", "On hold", "\"Put on hold\" in costing, then \"Resume\".", "Returns to costing only"],
            ["C7", "Deviation four-eyes", "Hand over to scoping without description. \"Request deviation\" (A); A tries to "
                                          "approve; B approves; A \"Retry transition\".", "A refused, B accepted, "
                                                                                         "transition done"],
            ["C8", "Late RFQ", "Quote deadline yesterday, then send the offer today.", "Status card shows the quote deadline overdue (red) before; quoted late after"],
            ["C9", "Reopen costing", "In quoting \"Reopen costing\" with reason.", "Back in costing, numbers editable"],
            ["C10", "Cancel", "\"More actions\" → \"Cancel change…\" with reason.", "Cancelled, gone from task lists"],
        ]),

        # ------------------------------------------------------------ 8
        ("h1", "8. Process Flow check"),
        ("p", "The Process Flow page (sidebar \"Process Flow\", views \"Detailed\" and \"Overview\") is drawn by hand, "
              "not generated from the system. A desk check against the program on 10/01/2026 found 18 differences; "
              "the page was corrected the same day (F-05). These are the rules the page now shows and PLM2 enforces "
              "(soft = an approved deviation lifts it, hard = nothing lifts it). Keep the page open in a second window "
              "during each simulation and confirm every rule you pass in the sheet \"Process Flow check\" of the "
              "findings log: Yes, or what you saw instead."),
        ("img", "img/wi_processmap.png", "Process Flow page, detailed view", 4.6),
        ("table", [0.45, 5.05, 1.1], ["No.", "Rule (Process Flow page and system, since 10/01/2026)", "Check in"], [
            ["M1", "Hand-over to scoping (soft): description, at least one attachment, quote deadline (customer "
                   "change) and a change lead", "A1-A2"],
            ["M2", "Into assessment: \"Proceed\" needs at least one R or A department, no open question or cancel "
                   "vote, and the cost carrier. Soft: impacted items, lead, quote deadline. Hard: the impacted set "
                   "confirmed by Development", "A4-A6"],
            ["M3", "The cost carrier is fixed at the scoping meeting and cannot change after scoping", "A5, C1"],
            ["M4", "Into costing (soft): every R/A assessment submitted, no \"not feasible\", no routing change "
                   "pending", "A9"],
            ["M5", "\"Not feasible\" does not reject: it holds costing and offers \"Reject change\", \"Back to "
                   "scoping\" (reason) or \"Override with a reason\" (four eyes)", "C3"],
            ["M6", "Moves back, each with a reason: reopen costing (from quote creation), reopen a rejected change, "
                   "back from validation to implementation", "C5, C9"],
            ["M7", "\"Customer declined\" records the answer only; rejecting is its own step, and a rejected customer "
                   "change closes only after the rejection letter is attached and marked sent", "C4"],
            ["M8", "Approval of a customer change (hard): customer accepted, PM sign-off and Quality sign-off by two "
                   "different people; then \"Record approval\"", "A14-A17"],
            ["M9", "Publishing the plan is not a gate. It needs the validated timing and the bank build decision "
                   "(running change, or planned scrap with a scrap price)", "A19-A20"],
            ["M10", "Into implementation (soft): timing validated, impact confirmed, a check workflow for every item "
                    "category, D1 \"Technical release?\" = Yes", "A21-A22"],
            ["M11", "Into validation (soft): every impacted item has its revision. Open plan deviations do not stop "
                    "this step", "A25"],
            ["M12", "Release (soft): validation checks passed, no open validation issue, every revision through its "
                    "check workflow, release checklist complete, lessons step done, **no open plan deviation**", "A28"],
            ["M13", "Release deadline: set with \"Customer accepted\" (internal: \"Approve internal costs\"; "
                    "Weissenburg / Solingen: their SOP), moved only with a reason", "A14, 6.3"],
            ["M14", "Quote deadline: needed at the hand-over and again into assessment (customer change); after "
                    "capture only \"Push back\" with a reason; active until the offer is sent", "A1-A3"],
            ["M15", "On hold: \"Resume\" goes back to the stage it was held in, nowhere else", "C6"],
            ["M16", "Back to scoping (recall) only while no assessment has started, or after a \"not feasible\"", "C3"],
            ["M17", "Timing: confirmed by every department in the Team confirmation panel, validated by Sales, PM, "
                    "Scheduling or the lead; it can be validated again during implementation (new baseline)", "T3-T6"],
            ["M18", "The engineering review lane and the intake are owned by Development", "-"],
        ]),

        # ------------------------------------------------------------ 9
        ("h1", "9. Recording findings"),
        ("p", f"Every finding goes into **{LOG}**, one row each, the same day. Sheet \"Findings\" for bugs and wishes, "
              "sheet \"Process Flow check\" for M1 to M18."),
        ("table", [1.6, 5.0], ["Column", "What to write"], [
            ["Type", "**Bug** (wrong result, error message, crash) · **Change** (works, but should work differently) · "
                     "**Missing** (function needed and not there) · **Text** (label or message unclear) · "
                     "**Process Flow** (page and system differ)"],
            ["Severity", "**A** blocks go-live (wrong data, a step that cannot be done, a gate that does not hold) · "
                         "**B** must be fixed, a workaround exists · **C** improvement"],
            ["Where", "Simulation and step number (e.g. A16), change number, the department you acted as"],
            ["What I did / what happened / what I expected", "One sentence each. Exact message text in quotes"],
            ["Screenshot", "File name of the screenshot, saved next to the log"],
        ]),
        ("p", f"Findings due **{FINDINGS_DUE}**. Review of all findings with Project Management on **{REVIEW}**: each "
              "gets a decision (fix before go-live, after go-live, no change) and becomes an action in the LOP where "
              "needed."),
        ("h2", "9.1 Already known (check them, add what you see)"),
        ("table", [0.5, 4.6, 1.5], ["No.", "Finding", "Where"], [
            ["F-01", "Costing: header \"Waiting on cost input from 2 departments\" while the Costing tab said \"4 of 7 "
                     "departments have not costed yet\". **Fixed 10/01**: both name the departments that still owe "
                     "an input", "A11"],
            ["F-02", "Release deadline could be moved without a reason. **Fixed 10/01**: \"Move\" asks why, the "
                     "reason is required and audited", "6.3"],
            ["F-03", "D1 tab showed the gate buttons to an admin acting as a department, then refused. **Fixed "
                     "10/01**: read-only while acting, with a hint", "A21"],
            ["F-04", "\"Internal change\" was greyed in the start form. **Fixed 10/01**: internal changes can be "
                     "started; walked end to end before switching on", "C1"],
            ["F-05", "Process Flow page differed from the system in 18 points. **Fixed 10/01**: page aligned (section 8)",
             "8"],
            ["F-06", "ECN check workflows, stage 3: \"Implement tool change\" went to Production and \"Update master "
                     "data & logistics\" to Logistics, both retired: nobody got these tasks. **Fixed 10/01 (live)**: "
                     "Process Engineer (Tool Engineer accountable) and Scheduling, along the role remap", "A24"],
        ]),

        # ------------------------------------------------------------ 10
        ("h1", "10. Help while testing"),
        ("img", "img/wi_mytasks.png", "My Tasks", 3.6),
        ("b", "**My Tasks** (sidebar) lists everything the department you act as owes, with the button that opens the "
              "right tab."),
        ("b", "**\"Transition blocked\"** banner: the yellow list says what is missing. Fill it in, or \"Request "
              "deviation\" with a reason; person B approves; then \"Retry transition\"."),
        ("b", "**KPI board** (Changes → \"KPI board\"): RFQ and implementation on time. Test Project is left out on "
              "purpose, so SIM changes never show there."),
        ("b", "Stuck or unsure: write the finding, note where you stopped, and contact C. Demmler."),
    ],
}
