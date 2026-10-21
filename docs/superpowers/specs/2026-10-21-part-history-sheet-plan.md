# Part history per article (BMW Part History Sheet) - plan

Status 2026-10-21: plan only. Do not build before #46 data route and #47 ECR solid are deployed.
Request: Christoph via the Ass session. Templates: /home/nitrolinux/claude/Assistant/docs/reports/phs-g65-ice-templates/

## What the PHS is (from the 5 G65 ICE sheets)

- Header: customer part no. (BMW 5A5D994), part name (ZB UBV Mitte), supplier + supplier no., internal part no. (10-3346-001-0), internal ZSB no. (20-3346-001-0), production plant, PPA location.
- One row per occasion, numbered (lfd. no.): First Part - BBG, VS0 toolmaker trial n, VS1 homeline trial n (machine), R@R, later ECs.
- Columns: customer level (AI02/AI04), EC number (NFT04C, EFS85E), internal level (Q1..Q8, +1 per row), drawing / 3D data index (H1A, I1A), agreed by (name, company/dept, date), supplier evaluation dimensional / laboratory / function / total (St / S* / Nt legend), delivery no. + date, comments.
- In the real sheets the evaluation and delivery-no. columns are mostly empty; agreed-by is always the same BMW contact without a date. Hand-typed data has errors (EF8S5E vs EFS85E, 1.23.2025 for 2026, US date order).
- 5A5D970 (3342) has a second sheet "PHS - Clip": one PHS per customer part number, a workbook can hold several.

## Mapping onto PLM2

One new table, `part_history_entries`, per article (part_id), ordered by lfd. no. Each row stores what the sheet needs and links to the source it came from, so most of it is filled in, not typed.

| PHS column | Source | Fill |
|---|---|---|
| Header customer part no. / name / internal nos. | parts.customer_part_number, name, part_number, the ZSB (parent / produces relation) | auto |
| Supplier, supplier no., plant, PPA location | project/plant settings (new: customer-specific supplier no.) | once per project |
| lfd. no. | row order | auto |
| Occasion - process | event type: first_part, vs0_trial, vs1_trial, rar, ec, other + free text | picked; trial rows proposed from PDB |
| Customer level (AI04) | part_revisions.customer_statement / customer_index at that time | auto, editable |
| EC number | the ECR's customer EC number (ECR solid; new field if absent) | auto from linked ECR |
| Internal level Q1..Qn | counter, +1 per sampling row unless marked same level | auto, editable |
| Drawing / 3D index (H1A) | the PLM2 revision in force at that date (customer_index of the drawing/CAD file) | auto |
| Agreed by name/dept/date | customer contact per project + date | default from project, editable |
| Evaluation dim / lab / func / total | entered after the measurement / lab / function check; total derived (worst of three) | hand, with link to the report |
| Delivery no. + date | PDB sampling: th_no, end_date (or the shipment) | auto from PDB, editable |
| Comments | text | hand |

Sources in detail:
- **Revisions and ECR (PLM2):** a frozen/approved revision or a closed customer ECR proposes a row "EC <no>" with the new index. The data route (#46) gives the received date and customer index.
- **PDB samplings:** PDB `samplings` (tool_number, machine, th_no, start/end date, reason, state). A confirmed sampling for the article's tool proposes a VS0 (toolmaker) or VS1 (homeline, machine in the text) row. PLM2 reads PDB read-only through an API; a proposal is accepted or dismissed by the engineer, never written silently.
- **Measurement reports:** a CMM / lab report file is attached to the row (revision_files-style storage) and the evaluation cells link to it.

## Export

Button "Export PHS" on the article (and per project, one workbook with one sheet per BMW part no.): fills a copy of BMW's own layout (sheet "PHS", header cells B3/B5/J3/J5/J7/P3/P5/P7, rows from 16, columns B..P) with openpyxl, so the customer gets the format they expect. Template file is checked in once, not rebuilt in code. Dates written as real dates in the sheet's format.

Import once: the 5 G65 sheets (and the older P:\1748 PCH FILES, after checking) as the starting history, with the typos flagged.

## Order of work (after #46 and #47)

1. Table + API + article tab "Part history" (manual rows, export).
2. Import of the existing PHS files for 1748.
3. Proposals from PLM2 revisions / ECRs.
4. Proposals from PDB samplings (needs a PDB read API or DB read access).
5. Report attachments and evaluation legend.

## Prod data found 2026-10-21

- Project 1748 is in PLM2 prod (148 parts), but the BMW numbers (5A5D994 etc.) are not set as customer_part_number on any part.
- 10-3354-001-0 is named "CANCELLED" in PLM2 while the PHS for 5A627C0 uses it as the internal part no.

## Questions for Christoph

1. Is it BMW-only, or every customer (the same tab, with BMW's layout as one export)?
2. Who keeps it: Quality (Shubham) or the project engineer? Who signs the "agreed" column, and is BMW's contact per project enough?
3. Internal level Q: +1 per sampling, or only when the part changed? (G65: Q5 twice for two homeline trials on 3346, but +1 each on 3369.)
4. Evaluation St/Nt: entered from the CMM/lab reports by hand, or should CASQIT/the measurement room feed it?
5. Delivery no.: is that the PDB TH number, or a shipping document number?
6. Fill the BMW numbers on 1748 parts from the PHS headers, and is 10-3354-001-0 really cancelled?
7. Import the old P:\1748 PCH files and the Part Change Overview .xlsm as history, or start from the 5 current sheets?
