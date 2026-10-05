---
name: project-timing-blocks-2026-10-02
description: Project timing from standard blocks instead of copy-paste MS Project (G6x/G67 pilot, TOC-PLM-07 requirements, TRACE.md); goal = automate in PLM2 + SEP project database
metadata:
  type: project
---

2026-10-02: user's goal: project-member timing generated in PLM2 + PDB (= SEP project database) from standard blocks,
not copied tasks; "document everything we find and trace the implementation".
Source: PM of project 1748's MS Project file "G6x Project Timeline (2026-09-30).mpp" (Windows Downloads), 239 tasks,
0 links. Read with mpxj + a local JRE (pip mpxj/jpype1, install-jdk into scratch venv; no system Java).

Built: docs/project-timing/ (G6x Timing Template.xlsx with formula plan, G67 Timeline (from template).xml MSPDI,
generate.py, TRACE.md = living trace: TR-01..22, TF-01..10, D-01..05, log). TOC-PLM-07 Requirements Project Timing
(docs/audit-plans/build/content_rs.py, built with build_ktx.py + convert.sh; build_ktx header now takes d["date"]).
Not committed yet.

**Why:** the PM overplanned with repetitive rows; standards belong in PLM/PDB. SEP matrix = WHAT per gate, blocks =
HOW/WHEN per mold, mold changes = ECR plans (not project rows).

**How to apply:** every implementation step: update TRACE.md (status + evidence), commit messages name TR-xx, carry
status into TOC-PLM-07 section 8 on revision. LibreOffice cannot start on this box: verify xlsx formulas with the
python `formulas` package (bounded ranges only, whole-column refs hang it). Proposed timing: workshop 10/30, sign-off
11/13/2026, phase 1 after ECR go-live (02/26/2027). Related: [[audit-implementation-plans-2026-09-30]], [[project-team-responsibles-2026-09-25]].
