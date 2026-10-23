---
name: audit-implementation-plans-2026-09-30
description: Audit escalation docs TOC-PLM-00..05 + KTX LOP action plan in docs/audit-plans (KTX template FM-QUA-0039-07, Word/Excel via PowerShell); dates and rebuild steps
metadata:
  type: project
---

2026-09-30: built docs/audit-plans/: TOC-PLM-00 overview (master timing, audit quick guide, TWOS + RFQ2 as done examples),
01 ECR (go-live 2026-12-07), 02 SEP (new projects PLM2-only 2027-01-04, 1994 lead project, no SOP date known), 03 data
management (drives read-only 2027-03-08), 04 lessons learned (procedure 2026-12-18), 05 TISAX page, plus
"TOC-PLM-LOP Action Plan PLM2.xlsm" (KTX LOP F-DVS-CORP-010, 40 actions). Not committed.

**Why:** user wants an archivable, self-explaining plan to pull in IATF/VDA/TISAX audits; tone: status + timing, weaknesses brief.
User asked to use KTX templates (Word FM-QUA-0039-07 from PDB repo, LOP from Documents/SEP/weissenburg-ep-docs).

**How to apply:** edit build/content.py, then make_charts.py, build_ktx.py, convert.sh. LibreOffice has no Writer on this box
(no sudo), so PDFs come from MS Word via PowerShell COM; Excel COM fills the LOP (openpyxl would drop its chart/validation).
Open inputs for Rev. 02: 1994 SOP date, approver names, doc numbering confirmation (TOC-PLM-xx chosen by Claude).

2026-09-30 later: KTX Toccoa has NO information security officer and no TISAX label / asset register yet (user).
IS officer removed everywhere; IT supports I2 and I3; I3 now "start an asset list with IT, record PLM2 as the
prototype-data system (basis for a future TISAX scope)". Docs, PDFs and LOP rebuilt. LOP rebuild: substitute
__WD__ in lop.ps1.in with python (sed eats the backslashes), copy lop_rows.csv + tpl/F_DVS_CORP_010_LOP.xlsm as tpl_lop.xlsm.
2026-10-01: TOC-PLM-01 got action KP (KPIs to be defined, starting with implementation on time, due 12/11/2026, Quality + Program Mgmt.) and KPI row 'Changes implemented on time' (target to be defined); LOP now 42 actions.
2026-10-01: TOC-PLM-04 got the same: action KP (KPIs to be defined, lesson actions on time, due 12/18/2026) + KPI row; LOP 43 actions. Open question to user: renumber F-actions so TR/KP become F-codes.
