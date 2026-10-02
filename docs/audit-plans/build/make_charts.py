"""Builds every figure used by the TOC-PLM-00..04 plans into ./img."""
import os
from charts import flow, gantt

os.makedirs("img", exist_ok=True)
TODAY = "2026-09-30"
S, E = "2026-09-21", "2027-04-30"

# ---------------------------------------------------------------- flows
flow({"w": 10, "h": 4.75, "lanes": [[0.3, 4.55, "TODAY", 0.05, 2.65], [0.3, 4.55, "TARGET: PLM2 MODULES", 7.05, 9.65]],
      "nodes": {
          "a": [1.35, 3.75, "ECC SharePoint list\n+ GB-CM-0001 Excel", "end", 2.3],
          "b": [1.35, 3.0, "SEP matrix\nGB-DP-0001 Excel", "end", 2.3],
          "c": [1.35, 2.25, "Network drives\ndrawings, customer data", "end", 2.3],
          "d": [1.35, 1.5, "SharePoint lessons list", "end", 2.3],
          "e": [1.35, 0.75, "WinCarat\nread-only since import", "end", 2.3],
          "p": [4.9, 2.25, "PLM2\none controlled system\nweb, role-based, audited", "stage", 2.2, 1.3],
          "m1": [8.35, 3.6, "Change management\nTOC-PLM-01", "side", 2.3],
          "m2": [8.35, 2.7, "SEP / project\nTOC-PLM-02", "side", 2.3],
          "m3": [8.35, 1.8, "Data management\nTOC-PLM-03", "side", 2.3],
          "m4": [8.35, 0.9, "Lessons learned\nTOC-PLM-04", "side", 2.3]},
      "edges": [["a", "p", None, "dashed"], ["b", "p", None, "dashed"], ["c", "p", None, "dashed"],
                ["d", "p", None, "dashed"], ["e", "p", None, "dashed"],
                ["p", "m1"], ["p", "m2"], ["p", "m3"], ["p", "m4"]]},
     "img/flow_overview.png")

flow({"w": 10.2, "h": 5.0,
      "lanes": [[1.6, 4.95, "MAIN PATH: customer and internal changes"],
                [0.1, 1.5, "SIDE TRACK: changes controlled by KTX Weissenburg (mother plant)"]],
      "nodes": {
          "in": [0.95, 4.2, "Intake\nDevelopment triages", "stage", 1.45],
          "ca": [2.6, 4.2, "Captured\nSales / PM, kickoff", "stage", 1.45],
          "sc": [4.25, 4.2, "Scoping\nimpact lock (HARD)", "stage", 1.45],
          "as": [5.9, 4.2, "Assessment\nRASIC-routed depts", "stage", 1.45],
          "co": [7.55, 4.2, "Costing\ndepartments", "stage", 1.45],
          "qu": [9.2, 4.2, "Quote / approval\nPM + Quality sign-off", "stage", 1.45],
          "ap": [9.2, 2.85, "Approved\ntiming baseline", "gate", 1.45],
          "im": [7.55, 2.85, "Implementation\ntracker, deviations", "stage", 1.45],
          "va": [5.9, 2.85, "Validation\nchecks, checklist, lessons", "stage", 1.6],
          "re": [4.25, 2.85, "Released\nPM", "stage", 1.45],
          "cl": [2.6, 2.85, "Closed\nsummary, P&L", "end", 1.45],
          "vi": [6.75, 1.95, "Validation issue\n8D, escalation L1-L3", "risk", 1.7, 0.55],
          "w1": [3.3, 0.8, "Weissenburg change\nECC form + BMW data", "side", 1.75],
          "w2": [5.7, 0.8, "Scoping\nimpact lock, Development", "side", 1.75],
          "w3": [8.3, 0.8, "Inform team\nreceipts, then HARD gate", "side", 1.75]},
      "edges": [["in", "ca"], ["ca", "sc"], ["sc", "as"], ["as", "co"],
                ["co", "qu"], ["qu", "ap", "HARD"], ["ap", "im"], ["im", "va"], ["va", "re"],
                ["re", "cl"], ["va", "vi", None, "dashed"], ["vi", "im", "fix route", "dashed"],
                ["w1", "w2"], ["w2", "w3"], ["w3", "ap"]]},
     "img/flow_ecr.png")

gates = ["K0/RG1\nRFQ, nomination", "K/RG2\nproject start", "E/RG3\nproduct design",
         "D/RG4\nprocess design", "C/RG5\nimplementation", "B/RG6\npre-series", "A/RG7\nseries"]
nodes = {f"g{i}": [0.75 + i * 1.38, 2.35, g, "stage", 1.22] for i, g in enumerate(gates)}
nodes.update({
    "ll": [1.45, 3.75, "Lessons learned check\nTOC-PLM-04", "side", 2.0],
    "ev": [4.9, 3.75, "Evidence per item\nfile upload, audited", "side", 2.0],
    "ti": [8.0, 3.75, "Project timing\ngate target dates", "side", 2.0],
    "gr": [3.5, 0.85, "Gate review\nPM + Quality sign-off", "gate", 2.0],
    "lk": [6.2, 0.85, "Gate closed\nitems locked, next opens", "gate", 2.0],
    "ecr": [8.75, 0.85, "SOP: series changes\nvia ECR, TOC-PLM-01", "end", 1.9]})
edges = [[f"g{i}", f"g{i+1}"] for i in range(6)]
edges += [["ll", "g0", None, "dashed"], ["ll", "g1", None, "dashed"], ["ev", "g3", None, "dashed"],
          ["ti", "g5", None, "dashed"], ["g2", "gr", "each gate", "dashed"], ["gr", "lk"],
          ["g6", "ecr", "handover"]]
flow({"w": 10, "h": 4.4, "nodes": nodes, "edges": edges}, "img/flow_sep.png")

flow({"w": 10.65, "h": 4.6,
      "nodes": {
          "pk": [0.95, 3.2, "Customer data\npackage received", "stage", 1.55],
          "tr": [2.95, 3.2, "Intake triage\nDevelopment", "gate", 1.55],
          "ad": [5.1, 4.2, "Administrative\nindex active, reason", "stage", 1.75],
          "er": [5.1, 3.2, "Engineering review\ndepartments answer", "stage", 1.75],
          "ec": [5.1, 2.2, "Full change\nECR, TOC-PLM-01", "stage", 1.75],
          "rv": [7.35, 3.2, "Revision released\nE-level / official index", "stage", 1.85],
          "fi": [9.45, 3.2, "Files + 3D view\none valid revision", "side", 1.7],
          "au": [7.55, 0.85, "Hash-chained\naudit trail", "side", 1.8],
          "wu": [5.35, 0.85, "Traceability\nwhere-used, BOM,\ntool / gauge relations", "side", 2.1, 0.75],
          "ac": [9.55, 0.85, "Role-based access\nevery department, every site", "side", 2.0]},
      "edges": [["pk", "tr"], ["tr", "ad"], ["tr", "er"], ["tr", "ec"], ["ad", "rv"], ["er", "rv"],
                ["ec", "rv"], ["rv", "fi"], ["rv", "au", None, "dashed"], ["rv", "wu", None, "dashed"],
                ["rv", "ac", None, "dashed"]]},
     "img/flow_dm.png")

flow({"w": 10.2, "h": 4.4,
      "nodes": {
          "s1": [1.25, 3.8, "ECR release step", "side", 2.15],
          "s2": [1.25, 3.05, "SEP gate / project", "side", 2.15],
          "s3": [1.25, 2.3, "Validation issue / 8D", "side", 2.15],
          "s4": [1.25, 1.55, "Complaint, audit, launch", "side", 2.15],
          "c": [3.55, 2.7, "Lesson captured\nin_review, owner", "stage", 1.6],
          "w": [5.4, 2.7, "Actions\nin_work, due dates", "stage", 1.6],
          "v": [7.25, 2.7, "Verification\neffective? else back\nto actions", "gate", 1.6, 0.75],
          "cl": [9.1, 2.7, "Closed\nverifier recorded", "end", 1.5],
          "st": [7.25, 0.8, "Standards updated\nchecklists, FMEA, templates", "side", 2.3],
          "np": [3.9, 0.8, "New projects\nlessons check at RG1 / RG2", "side", 2.3]},
      "edges": [["s1", "c"], ["s2", "c"], ["s3", "c"], ["s4", "c"], ["c", "w"], ["w", "v"],
                ["v", "cl"], ["cl", "st", None, "dashed"],
                ["st", "np", "feeds", "dashed"]]},
     "img/flow_ll.png")

flow({"w": 10, "h": 3.0,
      "nodes": {
          "a": [1.15, 2.2, "1 Specification\nprocess walk with owner", "stage", 2.0],
          "b": [3.65, 2.2, "2 Programming\nautomated tests per change", "stage", 2.1],
          "c": [6.2, 2.2, "3 Acceptance test\npilot on real data", "test" if False else "gate", 2.0],
          "d": [8.75, 2.2, "4 Data migration\nbackup, rollback, counts", "stage", 2.1],
          "e": [8.75, 0.75, "5 Training\ntraining gate in the app", "side", 2.1],
          "f": [5.6, 0.75, "6 Cutover\nold source = history", "gate", 2.1],
          "g": [2.45, 0.75, "7 Controlled releases\nbackup + record per deploy", "end", 2.3]},
      "edges": [["a", "b"], ["b", "c"], ["c", "d"], ["d", "e"], ["e", "f"], ["f", "g"]]},
     "img/flow_method.png")

# ---------------------------------------------------------------- timing
ECR = [
    ["Role model tightening", "2026-10-19", "2026-11-27", "group"],
    ["E1 Department rights per hub group", "2026-10-19", "2026-11-13", "program"],
    ["E2 Strict 4-eyes on approvals", "2026-10-26", "2026-11-06", "program"],
    ["E3 Training gate switched on", "2026-11-16", "2026-11-20", "program"],
    ["E4 Close open flow points", "2026-11-02", "2026-11-27", "program"],
    ["Testing", "2026-10-19", "2026-12-11", "group"],
    ["T1 Scripted acceptance test per stage", "2026-11-02", "2026-11-27", "test"],
    ["T2 Live pilot G6X (1748) changes", "2026-10-19", "2026-12-11", "test"],
    ["Finalisation", "2026-11-02", "2026-12-21", "group"],
    ["TR Training concept (to be defined)", "2026-11-02", "2026-11-20", "final"],
    ["KP KPIs (to be defined)", "2026-11-23", "2026-12-11", "final"],
    ["F1 Procedure released", "2026-11-30", "2026-12-11", "final"],
    ["F2 Training all departments", "2026-11-30", "2026-12-18", "final"],
    ["F3 Go-live: PLM2 only", "2026-12-21", "2026-12-22", "final"],
    ["F4 Effectiveness review", "2027-03-15", "2027-03-26", "run"],
]
SEP = [
    ["Programming", "2026-10-19", "2026-12-11", "group"],
    ["S1 Project overview (portfolio + gates)", "2026-10-19", "2026-11-20", "program"],
    ["S2 Gate dates linked to project timing", "2026-10-26", "2026-11-13", "program"],
    ["S3 Gate item enforcement + signer roles", "2026-11-16", "2026-12-11", "program"],
    ["Documentation", "2026-10-19", "2027-01-04", "group"],
    ["D1 Upload SEP evidence, running projects", "2026-10-19", "2027-01-04", "test"],
    ["D2 1994 RG1 evidence complete, gate review", "2026-10-19", "2026-12-04", "test"],
    ["Finalisation", "2026-12-14", "2027-01-22", "group"],
    ["F1 Procedure released", "2026-12-14", "2026-12-28", "final"],
    ["F2 Excel SEP matrix retired for new projects", "2027-01-18", "2027-01-22", "final"],
    ["1994 runs RG2 to RG7 in PLM2 (to SOP)", "2026-12-07", "2027-04-14", "run"],
]
DM = [
    ["Programming (in development)", "2026-10-19", "2027-02-12", "group"],
    ["M1 Access scope gaps closed", "2026-10-19", "2026-11-06", "program"],
    ["M2 Customer data review timer (10 WD)", "2026-11-02", "2026-11-27", "program"],
    ["M3 Equipment + gauge completeness", "2026-11-16", "2027-01-04", "program"],
    ["M4 Customer part numbers on series parts", "2026-11-16", "2026-12-28", "program"],
    ["M5 Backup schedule + restore test", "2026-10-26", "2026-11-20", "program"],
    ["M6 Legacy drive data per active project", "2026-11-23", "2027-02-12", "program"],
    ["Testing", "2027-01-25", "2027-02-26", "group"],
    ["T1 Acceptance test + restore drill", "2027-01-25", "2027-02-26", "test"],
    ["Finalisation", "2027-03-01", "2027-04-14", "group"],
    ["F1 Procedure released, training", "2027-03-01", "2027-03-19", "final"],
    ["F2 Network drives read-only for active projects", "2027-03-22", "2027-03-26", "final"],
    ["F3 Effectiveness review", "2027-04-05", "2027-04-14", "run"],
]
LL = [
    ["Programming", "2026-10-19", "2026-12-11", "group"],
    ["L1 SharePoint list frozen, PLM2 only", "2026-10-19", "2026-10-30", "program"],
    ["L2 Lessons check at SEP RG1 / RG2", "2026-11-02", "2026-11-27", "program"],
    ["L3 Release step binding for all changes", "2026-11-09", "2026-11-27", "program"],
    ["L4 Lessons as input to risk / FMEA", "2026-11-16", "2026-12-11", "program"],
    ["Testing", "2026-11-30", "2026-12-18", "group"],
    ["T1 Run on 1994 RG2 + G6X changes", "2026-11-30", "2026-12-18", "test"],
    ["Finalisation", "2026-12-07", "2027-01-29", "group"],
    ["KP KPIs (to be defined)", "2026-12-07", "2026-12-18", "final"],
    ["F1 Procedure released", "2026-12-21", "2027-01-04", "final"],
    ["F2 First quarterly lessons review", "2027-01-25", "2027-01-29", "final"],
    ["Quarterly review in management review", "2027-02-01", "2027-04-14", "run"],
]
MASTER = [
    ["01 Change management (ECR)", "2026-10-19", "2026-12-22", "group"],
    ["Role model + open points", "2026-10-19", "2026-11-27", "program"],
    ["Acceptance test + G6X pilot", "2026-10-19", "2026-12-11", "test"],
    ["Procedure, training, go-live", "2026-11-02", "2026-12-22", "final"],
    ["02 SEP / project", "2026-10-19", "2027-01-22", "group"],
    ["Project overview + gate enforcement", "2026-10-19", "2026-12-11", "program"],
    ["Evidence upload, 1994 RG1 review", "2026-10-19", "2027-01-04", "test"],
    ["Procedure, Excel matrix retired", "2026-12-14", "2027-01-22", "final"],
    ["03 Data management", "2026-10-19", "2027-03-26", "group"],
    ["Development items M1-M6", "2026-10-19", "2027-02-12", "program"],
    ["Acceptance test + restore drill", "2027-01-25", "2027-02-26", "test"],
    ["Procedure, drives read-only", "2027-03-01", "2027-03-26", "final"],
    ["04 Lessons learned", "2026-10-19", "2027-01-29", "group"],
    ["PLM2 only, SEP + FMEA links", "2026-10-19", "2026-12-11", "program"],
    ["Run on 1994 + G6X", "2026-11-30", "2026-12-18", "test"],
    ["Procedure, first quarterly review", "2026-12-21", "2027-01-29", "final"],
]
for name, rows in (("ecr", ECR), ("sep", SEP), ("dm", DM), ("ll", LL), ("master", MASTER)):
    gantt(rows, f"img/gantt_{name}.png", S, E, TODAY)
print("ok")

# ------------------------------------------------ timing planner + tasks (schematic)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
fig = plt.figure(figsize=(8.6, 4.4), dpi=200)
ax = fig.add_axes([0.0, 0.0, 0.6, 1.0]); ax.axis("off"); ax.set_xlim(0, 6); ax.set_ylim(0, 3.9)
ax.text(0.05, 3.72, "Timing tab: detailed plan of one change (schematic)", fontsize=11, fontweight="bold", color="#1F2937")
blocks = [("Tool design", "Tooling", 0.0, 0.9, 1.0), ("Tool rework", "Vendor", 0.9, 2.1, 0.6),
          ("Trial T1", "Manufacturing", 2.1, 2.5, 0.0), ("Measurement", "Quality", 2.5, 3.0, 0.0),
          ("Bank build", "Scheduling", 2.2, 3.1, 0.0), ("Release / PPA", "Quality", 3.0, 3.5, 0.0)]
x0, sc = 2.1, 1.08
for i, (n, d, a, b, prog) in enumerate(blocks):
    y = 3.2 - i * 0.42
    ax.text(0.05, y, n, fontsize=9.1, va="center", color="#1F2937")
    ax.text(1.28, y, d, fontsize=8.2, va="center", color="#6B7280")
    ax.add_patch(plt.Rectangle((x0 + a * sc, y - 0.12), (b - a) * sc, 0.24, fc="#E8EEF7", ec="#2F5597", lw=0.8))
    if prog:
        ax.add_patch(plt.Rectangle((x0 + a * sc, y - 0.12), (b - a) * sc * prog, 0.24, fc="#2F5597", ec="none"))
    ax.plot([x0 + a * sc, x0 + b * sc], [y - 0.17, y - 0.17], color="#9CA3AF", lw=1.2)
# deviation on tool rework
ax.add_patch(plt.Rectangle((x0 + 2.1 * sc, 3.2 - 0.42 - 0.12), 0.25 * sc, 0.24, fc="#FCEBEA", ec="#B42318", lw=0.8))
ax.text(x0 + 2.1 * sc + 0.32, 3.2 - 0.42, "deviation: reason,\nlock or escalate", fontsize=7.5, color="#B42318", va="center")
ax.axvline(x0 + 1.5 * sc, ymin=0.12, ymax=0.9, color="#B42318", lw=0.8)
ax.text(x0 + 1.5 * sc, 0.62, "today", fontsize=7.8, color="#B42318", ha="center")
ax.plot([0.1, 0.4], [0.3, 0.3], color="#9CA3AF", lw=1.2); ax.text(0.45, 0.3, "baseline", fontsize=7.8, va="center", color="#6B7280")
ax.add_patch(plt.Rectangle((1.1, 0.24), 0.3, 0.12, fc="#2F5597")); ax.text(1.45, 0.3, "progress", fontsize=7.8, va="center", color="#6B7280")
ax.text(2.2, 0.3, "Each team confirms the plan revision; export to MS Project", fontsize=7.8, va="center", color="#6B7280")
ax2 = fig.add_axes([0.62, 0.0, 0.38, 1.0]); ax2.axis("off"); ax2.set_xlim(0, 4); ax2.set_ylim(0, 3.9)
ax2.text(0.05, 3.72, "My tasks: what each person sees", fontsize=11, fontweight="bold", color="#1F2937")
tasks = [("Confirm plan revision 2", "Tooling", "due Thu", "#1F2937"),
         ("Progress report tool rework", "Tooling", "due Tue", "#1F2937"),
         ("Release checklist: gauge check", "Quality", "overdue", "#B42318"),
         ("Decide plan deviation", "PM", "due today", "#B7791F"),
         ("Read and understood: ECC-0013", "Production", "due Fri", "#1F2937"),
         ("Lessons learned step", "PM", "next", "#1F2937")]
for i, (n, d, due, col) in enumerate(tasks):
    y = 3.25 - i * 0.47
    ax2.add_patch(FancyBboxPatch((0.05, y - 0.19), 3.85, 0.38, boxstyle="round,pad=0,rounding_size=0.05", fc="#FAFAFA", ec="#D1D5DB", lw=0.8))
    ax2.text(0.15, y + 0.05, n, fontsize=8.8, color="#1F2937", va="center")
    ax2.text(0.15, y - 0.11, d, fontsize=7.5, color="#6B7280", va="center")
    ax2.text(3.8, y, due, fontsize=8.2, color=col, va="center", ha="right", fontweight="bold")
ax2.text(0.05, 0.3, "Due-soon and overdue reminders go to the responsible,\nthe backup of the department is informed", fontsize=7.8, color="#6B7280", va="center")
fig.savefig("img/timing_tasks.png", bbox_inches="tight", pad_inches=0.05, facecolor="white")
print("timing ok")
