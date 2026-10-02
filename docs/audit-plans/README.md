# PLM2 audit implementation plans (internal working documents, status 2026-09-30)

Internal, not document-controlled plans for IATF 16949 / VDA / TISAX audits: pull the document of the audited topic and show it next to the live system.

| File | Topic |
|---|---|
| TOC-PLM-00 Program Overview | Entry point: landscape today vs target, master timing, audit quick guide, TWOS/RFQ2 as completed examples |
| TOC-PLM-01 Change Management ECR | Built; testing + role model tightening; go-live 12/21/2026 |
| TOC-PLM-02 SEP Project Database | Built; evidence upload; 1994 lead project; new projects in PLM2 from 01/18/2027 |
| TOC-PLM-03 Data Management | Core tight; remaining functions in development; drives read-only 03/22/2027 |
| TOC-PLM-04 Lessons Learned | Built; binding into SEP/ECR; procedure 01/04/2027 |
| TOC-PLM-05 Information Security TISAX | VDA ISA controls in place + tightening actions |
| TOC-PLM-06 Work Instruction ECR Simulation | How Project Management simulates ECRs before go-live: admin picker, both change types, timing, Process Flow check (18 known differences), findings |
| TOC-PLM-06 ECR Simulation Findings Log.xlsx | Findings, Process Flow check and simulations run; filled by the testers, due 10/16/2026 |
| TOC-PLM-LOP Action Plan PLM2.xlsm | All 43 actions in the KTX LOP (F-DVS-CORP-010), the live action plan |

`pdf/` holds PDF copies. Word files take styles from the KTX template FM-QUA-0039-07 but carry a plain internal header/footer: no document number field, revision, approval block or revision history.

Rebuild (after editing `build/content.py`): `cd build && python3 make_charts.py && python3 build_ktx.py && ./convert.sh`
(conversion and the LOP fill use Word/Excel on the Windows side via PowerShell; LOP: `lop.ps1.in` + `lop_rows.csv`).
