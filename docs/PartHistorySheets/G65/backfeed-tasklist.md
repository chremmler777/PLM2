# G65 backfilled changes — department backfeed tasklist

**41 auto-created `closed` changes** were backfilled from the G65 (BMW G6X, project 1748) part-history sheets. They were implemented before PLM existed, so they carry only what the sheets recorded. Each department below owns filling the gaps so these historical changes become complete PLM records.

## Scope

| Affected assembly | Change numbers | Count |
|---|---|---|
| 20-3342-001-0 | PHS-20-3342-001-0-1 … PHS-20-3342-001-0-8 | 8 |
| 20-3346-001-0 | PHS-20-3346-001-0-1 … PHS-20-3346-001-0-6 | 6 |
| 20-3354-001-0 | PHS-20-3354-001-0-1 … PHS-20-3354-001-0-8 | 8 |
| 20-3369-001-0 | PHS-20-3369-001-0-1 … PHS-20-3369-001-0-9 | 9 |
| 20-3369-002-0 | PHS-20-3369-002-0-1 … PHS-20-3369-002-0-9 | 9 |
| 50-0331 | PHS-50-0331-1 | 1 |

## Per-department worklist

### R&D / Developer

For all 41 backfilled changes:

- [ ] Affected sub-components and tools per change — the sheets list only the top ZSB assembly, not which molded parts, clips, or tools actually changed.
- [ ] Geometry-change flag + 3D evidence (no_geometry_change) for each change.
- [ ] Resulting part revision per change (link the ECN revision the change produced).
- [ ] Full change description and root cause — sheets give only a one-line occasion (First Part / VS0 / VS1 / R@R).

### Tool Engineer / Tool design

For all 41 backfilled changes:

- [ ] Tool(s) modified for each change and the nature of the tool work — the tool (33xx) is implied by the assembly number but not linked as an impacted item.

### Quality / APQP

For all 41 backfilled changes:

- [ ] Feasibility verdict per change (the change never ran an assessment).
- [ ] Dimensional / laboratory / function evaluation results — the sheet's Evaluation-Suppl. columns (Dimensional/Laboratory/Function/Total) are blank.
- [ ] PPAP submission and level per change.
- [ ] Quality sign-off.

### Project Manager

For all 41 backfilled changes:

- [ ] Timing milestone / required-by date.
- [ ] Gate decisions (feasibility, budget, release) — none were recorded pre-PLM.
- [ ] PM sign-off; whether the change was a series or single change.

### Sales

For all 41 backfilled changes:

- [ ] Actual customer response — backfill defaulted every change to 'accepted'; confirm or correct.
- [ ] Quoted price to the customer.
- [ ] Confirm the customer EC number and customer level captured from the sheet.

### Manufacturing Engineer / IE / Production

For all 41 backfilled changes:

- [ ] Process / implementation impact and implementation mode.
- [ ] Production routing and run-at-rate confirmation (the 'R@R' rows).

### Costing (via each assessing department)

For all 41 backfilled changes:

- [ ] Cost impact per assessing department (estimated cost) and internal cost approval — no cost data exists on the sheets.

### Purchasing

For all 41 backfilled changes:

- [ ] Purchased-component impact (clips / fasteners, 50-series) and supplier PPAP / confirmation.

### Logistics

For all 41 backfilled changes:

- [ ] Packaging impact — returnable packaging appears in the BOM but is not tied to these changes.

## Appendix — what each sheet row already provides

| Change | Affects | Occasion | Cust. level | EC number | Int. level | Drawing idx | Agreed by |
|---|---|---|---|---|---|---|---|
| PHS-20-3342-001-0-1 | 20-3342-001-0 | First Part - BBG | AI04 | NFT05C | Q1 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-2 | 20-3342-001-0 | VS0 - Tool Maker Parts | AI04 | EF8S5E | Q2 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-3 | 20-3342-001-0 | VS0 - Tool Maker Parts | AI04 | EF8S5E | Q3 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-4 | 20-3342-001-0 | VS0 - Tool Maker Parts | AI04 | EF8S5E | Q4 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-5 | 20-3342-001-0 | VS1 - Homeline Parts | AI04 | EF8S5E | Q5 | I1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-6 | 20-3342-001-0 | VS1 - Homeline Parts | AI04 | EF8S5E | Q6 | I1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-7 | 20-3342-001-0 | VS1 - Homeline Parts | AI04 | EF8S5E | Q7 | I1A | Mr. Wolfgang Schubert |
| PHS-20-3342-001-0-8 | 20-3342-001-0 | R@R | AI04 | EF8S5E | Q8 | I1A | Mr. Wolfgang Schubert |
| PHS-20-3346-001-0-1 | 20-3346-001-0 | First Part - BBG | AI02 | NFT04C | Q1 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3346-001-0-2 | 20-3346-001-0 | VS0 - Toolshop - Trial 1: | AI04 | EFS85E | Q2 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3346-001-0-3 | 20-3346-001-0 | VS0 - Toolshop - Trial 2 | AI04 | EFS85E | Q3 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3346-001-0-4 | 20-3346-001-0 | VS0 - Toolshop - Trial 3 | AI04 | EFS85E | Q4 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3346-001-0-5 | 20-3346-001-0 | VS1 - Homeline - Trial 1 (KM 1000-3) | AI04 | EFS85E | Q5 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3346-001-0-6 | 20-3346-001-0 | VS1 - Homeline - Trial 2 (KM 1000-2) | AI04 | EFS85E | Q5 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-1 | 20-3354-001-0 | First Part - BBG | AI04 | EFT40C | Q1 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-2 | 20-3354-001-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q2 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-3 | 20-3354-001-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q3 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-4 | 20-3354-001-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q4 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-5 | 20-3354-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q5 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-6 | 20-3354-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q6 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-7 | 20-3354-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q7 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3354-001-0-8 | 20-3354-001-0 | R@R | AI04 | EF8S5E | Q8 | I1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-1 | 20-3369-001-0 | First Part - BBG | AI04 | EFT40C | Q1 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-2 | 20-3369-001-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q2 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-3 | 20-3369-001-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q3 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-4 | 20-3369-001-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q4 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-5 | 20-3369-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q5 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-6 | 20-3369-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q6 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-7 | 20-3369-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q7 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-8 | 20-3369-001-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q8 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-001-0-9 | 20-3369-001-0 | R@R | AI04 | EF8S5E | Q8 | I1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-1 | 20-3369-002-0 | First Part - BBG | AI03 | E6E35D | Q1 | H1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-2 | 20-3369-002-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q2 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-3 | 20-3369-002-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q3 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-4 | 20-3369-002-0 | VS0 - Tool Maker Parts | AI04 | EFS85E | Q4 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-5 | 20-3369-002-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q5 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-6 | 20-3369-002-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q6 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-7 | 20-3369-002-0 | VS1 - Homeline Parts | AI04 | EFS85E | Q7 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-8 | 20-3369-002-0 | VS4 - Homeline Parts | AI04 | EFS85E | Q8 | L1A | Mr. Wolfgang Schubert |
| PHS-20-3369-002-0-9 | 20-3369-002-0 | R@R | AI04 | EF8S5E | Q8 | L1A | Mr. Wolfgang Schubert |
| PHS-50-0331-1 | 50-0331 | First Part - Clip | - | 3 | - | 7311312 - D | Mr. Wolfgang Schubert |
