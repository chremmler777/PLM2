# Proposed cost sheet rates 2026 (KTX Toccoa and Silao)

> **Status: PROPOSAL ONLY. To be confirmed by Sales and Finance before use in any customer quote.**
> These are fully loaded internal hourly rates for costing engineering changes (ECRs). They are not wages.
> Compiled 2026-09-26 from public wage statistics and industry references (sources at the end).
> Machine-readable copy: `proposed-cost-sheet-rates-2026.json` (same folder).

## 1. USA Toccoa, Georgia (USD)

Multiplier `k = 2.20` (derived from the three user anchors, see section 4). Wage basis: BLS OEWS May 2025, Georgia statewide mean hourly wage.

| Department | Proposed rate | Currency | Wage basis (BLS OEWS May 2025, Georgia mean) | Multiplier | Title-level cross-check (Georgia) |
|---|---:|---|---|---:|---|
| Development | 116 | USD/h | 17-2141 Mechanical Engineers, $52.71 | 2.20 | Product/design engineering is mechanical engineering; ranks between Tool and Manufacturing Engineer |
| Tool Engineer | **120** (anchor) | USD/h | 17-2141 Mechanical Engineers, $52.71 | 2.28 implied | Tooling engineer, Atlanta: $105,770/yr = $50.85/h (ZipRecruiter) |
| Manufacturing Engineer | **100** (anchor) | USD/h | 17-2112 Industrial Engineers, $50.26 | 1.99 implied | Manufacturing engineer, GA: $34.75/h (ZipRecruiter) |
| Process Engineer | 100 | USD/h | 17-2112 Industrial Engineers, $50.26 (same SOC as Manufacturing Engineer, inherits its anchor) | 1.99 | Injection molding process engineer, GA: $37.35/h (ZipRecruiter), +7% vs ME title; formula without parity rule would give 111 |
| APQP | **80** (anchor) | USD/h | 17-3026 Industrial Engineering Technologists and Technicians, $33.40 | 2.40 implied | APQP engineer, GA: $88,383/yr = $42.49/h; APQP QE Hartwell GA posting $75k to $95k |
| Packaging Engineer | 100 | USD/h | 17-2112 Industrial Engineers, $50.26 (same SOC as Manufacturing Engineer, inherits its anchor) | 1.99 | Packaging engineer, GA: $35.77/h (ZipRecruiter), +3% vs ME title |
| Quality | 92 | USD/h | 50% 17-2112 Industrial Engineers (quality engineer) + 50% 17-3026 technicians (metrology, PPAP, lab) = $41.83 | 2.20 | Quality engineer, GA: $34.12/h; senior QE $42.74/h; supplier QE $45.25/h (ZipRecruiter) |
| Scheduling | 63 | USD/h | 43-5061 Production, Planning and Expediting Clerks, $28.48 | 2.20 | Production scheduler, GA: $24.38/h (ZipRecruiter) |
| Sales | 134 | USD/h | 41-4011 Sales Representatives, Wholesale and Manufacturing, Technical and Scientific Products, $61.06 | 2.20 | Key account level. Usually not billed on ECRs; if billed, Finance may prefer to cap at the Project Manager rate |
| Project Manager | 114 | USD/h | 13-1082 Project Management Specialists, $51.96 | 2.20 | Automotive program manager, Marietta GA: $101,595/yr = $48.84/h (ZipRecruiter), which would give 107 |

Finance: not proposed as a billable department. For internal reference only, 13-2011 Accountants and Auditors ($45.02) x 2.20 = 99 USD/h.

Regional check (Gainesville GA MSA, the nearest published metro area to Toccoa, May 2025 means): Mechanical Engineers $44.98, Industrial Engineers $47.61, Industrial Engineering Technicians $32.81, Production Planning Clerks $27.97, Project Management Specialists $43.25, Sales Managers $70.99. Local engineering wages run about 5 to 15% below the state mean, so against local wages the anchors imply a blended multiplier of 2.39 instead of 2.20. The proposal stays on the statewide basis because it is published for every role and Toccoa recruits engineers from the wider Georgia/Upstate SC market.

## 2. Silao, Guanajuato, Mexico (USD, recommended)

Country factor `0.43` applied to each Toccoa rate (derivation in section 4). MXN column is for information only, at the Banxico FIX of 2026-09-22 (17.3015 MXN/USD).

| Department | Proposed rate | Currency | Basis | Info: MXN/h at 17.30 |
|---|---:|---|---|---:|
| Development | 50 | USD/h | Toccoa 116 x 0.43 | 865 |
| Tool Engineer | 52 | USD/h | Toccoa 120 x 0.43 | 900 |
| Manufacturing Engineer | 43 | USD/h | Toccoa 100 x 0.43 | 744 |
| Process Engineer | 43 | USD/h | Toccoa 100 x 0.43 | 744 |
| APQP | 34 | USD/h | Toccoa 80 x 0.43 | 588 |
| Packaging Engineer | 43 | USD/h | Toccoa 100 x 0.43 | 744 |
| Quality | 40 | USD/h | Toccoa 92 x 0.43 | 692 |
| Scheduling | 27 | USD/h | Toccoa 63 x 0.43 | 467 |
| Sales | 58 | USD/h | Toccoa 134 x 0.43 | 1,003 |
| Project Manager | 49 | USD/h | Toccoa 114 x 0.43 | 848 |

Cross-checks for Silao:
- Tool engineer postings in Silao at 45,000 MXN/month (San José Iturbide 45,000 to 53,000; León 30,000 to 45,000). 45,000 MXN = 15.01 USD/h base; with 1.50 Mexican statutory burden, the local overhead share and the USD-priced overhead share (section 4) this gives about 47 USD/h, close to the proposed 52.
- Indeed shows Industrial Engineer in Silao at 19,987 MXN/month and GKN Automotive Guanajuato Manufacturing Engineer at 18,427 MXN/month. These posting averages are junior-heavy; using them gives a factor of 0.27 (ME about 27 USD/h). This is the low case.
- Tetakawi 2026 benchmark: Manufacturing Engineer fully burdened 23.42 USD/h (4,559 USD/month) at 18.0 MXN/USD. This is the basis for the 0.43 factor.
- Relative pay differs by role in Mexico: bilingual Sales and Project Managers carry a larger premium than in the US; schedulers and technicians a smaller one. The single factor keeps the method simple; Finance may adjust Sales/PM up and Scheduling down if actual Silao payroll shows it.

### Currency recommendation for Silao

Quote Silao rates in **USD**.
- Automotive supply contracts into the Bajío cluster (OEMs and Tier 1s) are normally priced in USD, and most US-Mexico B2B transactions are priced in dollars; peso moves of 8 to 12% within a year are common, so an MXN rate card held for a model year carries real FX risk.
- One currency across both plants keeps the ECR cost sheet comparable and lets the customer see the Mexico discount directly.
- Legal note for Finance: under Ley Monetaria Art. 8, a USD obligation payable in Mexico may be settled in MXN at the Banxico FIX on the payment date unless payment in USD was expressly agreed. The CFDI can be issued in USD with the exchange rate stated. For a purely domestic Mexican customer that requires MXN, convert at the FIX of the quote date and state a validity period.

## 3. Machine hourly rates (injection molding presses)

Definition used: press rate including depreciation, auxiliaries (dryers, TCUs, robot), energy, maintenance, floor space, plant overhead and the operator share shown. Excludes material, packaging and engineering hours (those are billed via the department rates).

| Tonnage class | USA Toccoa (USD/h) | Silao Mexico (USD/h) | Basis |
|---|---:|---:|---|
| <=200 t | 59 | 43 | Machine part 42 + 0.5 operator |
| 200-450 t | 76 | 52 | Machine part 50 + 0.75 operator |
| 450-800 t | 93 | 62 | Machine part 59 + 1.0 operator |
| >800 t | 148 | 114 | Machine part 114 + 1.0 operator |

Derivation:
- Machine part (USA, 2026 USD), escalated with BLS PPI Plastics Product Manufacturing (PCU326---326---; June 2021 213.8, June 2023 251.356, June 2026 270.145):
  - <=200 t: MAPP 2021 micro-molding (<45 t) average 32 USD/h x 1.26 = 40; PlasticsToday 2023 molder 35 USD/h for 25 to 100 t x 1.075 = 38; set 42 for a class reaching 200 t.
  - 450-800 t: PlasticsToday 2023 molder 55 USD/h for 601 to 700 t x 1.075 = 59.
  - >800 t: MAPP 2021 1,000 t press about 90 USD/h x 1.26 = 114.
  - 200-450 t: interpolated, 50.
- Operator (USA): BLS OEWS May 2025 Georgia 51-4072 Molding, Coremaking and Casting Machine Setters/Operators, Metal and Plastic, mean 22.71 USD/h x 1.50 fringe (BLS ECEC manufacturing: wages 66.8% of total compensation) = 34 USD/h.
- Mexico: machine part x 0.95 (same USD-priced equipment and molds; CFE industrial energy is not cheaper than in Georgia; floor space and maintenance labor are cheaper) plus operator at about 6 USD/h fully burdened (Tetakawi 2026: Bajío entry-level operators 5.00 to 5.75 USD/h fully burdened).
- Plausibility: offshore/industry guides quote 30 to 50 USD/h at 100 t, 80 to 120 USD/h at 500 t and 150 to 250 USD/h at 1,000 t (ZetarMold), and 30 to 120+ USD/h overall (Jino). The proposal sits at the lower-middle of those ranges, consistent with the US Southeast being a lower-cost region. MAPP publishes a full tonnage table (14 classes, US regions) to members only; if KTX is a member, that report should replace these estimates.

### Sampling / trial price per class

**Left empty.** No public reference with sampling or trial prices by tonnage class was found. The only reference is a generic "300 to 1,500 USD per trial round depending on machine size and material" from an offshore molder's guide (Jino), which is not class-specific and not US/Mexico based. Suggested build-up if Finance wants a formula instead of a flat price: (setup hours + run hours) x machine rate of the class + process engineer hours x Process Engineer rate + material + measurement/report hours x Quality rate.

## 4. Method

### 4.1 Toccoa multiplier from the anchors

The three anchors are fully loaded rates. Mapping each to the closest BLS occupation (Georgia mean, May 2025):

| Anchor | Rate | BLS SOC | GA mean wage | Implied multiplier |
|---|---:|---|---:|---:|
| Tool Engineer | 120 | 17-2141 Mechanical Engineers | 52.71 | 2.28 |
| Manufacturing Engineer | 100 | 17-2112 Industrial Engineers (includes manufacturing engineers) | 50.26 | 1.99 |
| APQP | 80 | 17-3026 Industrial Engineering Technologists and Technicians (quality planning / APQP coordination) | 33.40 | 2.40 |
| **Blended** | 300 | | 136.37 | **2.20** |

All three anchors sit within about 10% of the blended 2.20, so one multiplier describes them well. Anchors are kept exactly as given; the small spread reflects a tooling skill premium (above) and a competitive ME rate (below).

Rules applied to the other departments:
1. Rate = 2.20 x Georgia mean wage of the mapped SOC, rounded to whole USD.
2. If a department maps to the same SOC as an anchor, it inherits the anchor rate (Process and Packaging share 17-2112 with Manufacturing Engineer, so both are 100; the BLS SOC cannot tell them apart and title-level data puts them within +3 to +7% of the ME title).
3. Quality is a blend of 50% quality engineer (17-2112) and 50% technician (17-3026), because ECR quality work (PPAP, dimensional layouts, CMM, lab tests) is split between both.

Plausibility of 2.20: labor burden alone is 1.50 (BLS ECEC, manufacturing, June 2025: wages 66.8% of total compensation), leaving 1.47 for overhead, G&A and margin. Wrap-rate references put small businesses at 1.6 to 2.2 and engineering firms with large facilities at 2.8 to 3.0. US engineering offices bill 130 to 175 USD/h, design services 100 to 120 USD/h, and a senior consulting engineer billing 135 USD/h is typically paid 50 to 55 USD/h (about 2.5x). KTX's anchors are therefore at the moderate end of market billing, appropriate for an internal supplier rate.

### 4.2 Silao country factor

Toccoa rate = labor cost x 1.47, so labor is 68% of the rate and overhead/G&A/margin 32%.
- Mexican engineering labor cost relative to US: Tetakawi 2026 Manufacturing Engineer fully burdened 23.42 USD/h at 18.0 MXN/USD, which is 24.37 USD/h at the current 17.30 FIX; US equivalent 50.26 x 1.50 = 75.24 USD/h; ratio r = 0.324.
- Half of the overhead layer is assumed to scale with local wages (facility, local indirect staff, margin on labor) and half to be USD-priced and not cheaper in Mexico (CAD/CAE/PLM licenses, IT, corporate engineering support, customer travel).
- Factor = 0.68 x r + 0.16 x r + 0.16 = 0.43.
- Sensitivity: at Tetakawi's own 18.0 MXN/USD the factor is 0.42; with junior-heavy Indeed posting averages (about 20,000 MXN/month) it is 0.27. Mexican statutory burden (IMSS, Infonavit 5%, SAR, aguinaldo, prima vacacional, PTU) is 40 to 60% on top of base, taken as 1.50.
- Market check: nearshore engineering in Mexico is typically quoted 30 to 50% below US rates (software-heavy sources). Silao at 57% below Toccoa is lower than that, which matches the much lower manufacturing-engineering wages in Guanajuato compared with Mexico's software market.
- Mexico's 48-hour week gives more paid hours per year, which would lower hourly cost slightly further; not applied (conservative).

### 4.3 Rounding and currency

Whole numbers, no further rounding. Toccoa in USD. Silao in USD with MXN shown for information.

## 5. Open points for Sales / Finance

1. Confirm the three anchors and whether Sales time is ever billed on ECRs (if not, drop Sales from the customer cost sheet).
2. Replace BLS/market wages with actual KTX payroll averages per department when available; keep k = 2.20 and factor 0.43 unless Finance's actual overhead absorption says otherwise.
3. If KTX is a MAPP member, replace the machine rate estimates with the MAPP 2025 Machine Rate Report (Southeast region, by tonnage).
4. Decide on a sampling/trial price policy (flat per class or formula as above).
5. Confirm USD quoting for Silao with the customer contracts in force.

## 6. Sources

US wages and burden
- BLS OEWS May 2025 via BLS Public Data API (series OEUS1300000000000xxxxxx03 Georgia, OEUM0023580000000xxxxxx03 Gainesville GA MSA): https://www.bls.gov/oes/ and https://data.bls.gov/oes/#/area/0023580
- BLS, Occupational Employment and Wages in Gainesville, GA, May 2025: https://www.bls.gov/regions/southeast/news-release/2026/occupationalemploymentandwages_gainesvillega_20260707.htm
- BLS ECEC June 2025 (manufacturing wages 66.8% of compensation): https://www.bls.gov/news.release/archives/ecec_09122025.htm
- BLS PPI Plastics Product Manufacturing (PCU326---326---): https://www.bls.gov/ppi/
- ZipRecruiter, Manufacturing Engineer salary in Georgia: https://www.ziprecruiter.com/Salaries/Manufacturing-Engineer-Salary--in-Georgia
- ZipRecruiter, Tooling Engineer jobs Atlanta GA: https://www.ziprecruiter.com/Jobs/Tooling-Engineer/-in-Atlanta,GA
- ZipRecruiter, Injection Molding Process Engineer salary in Georgia: https://www.ziprecruiter.com/Salaries/Injection-Molding-Process-Engineer-Salary--in-Georgia
- ZipRecruiter, Quality Engineer salary in Georgia: https://www.ziprecruiter.com/Salaries/Quality-Engineer-Salary--in-Georgia
- ZipRecruiter, Supplier Quality Engineer salary in Georgia: https://www.ziprecruiter.com/Salaries/Supplier-Quality-Engineer-Salary--in-Georgia
- ZipRecruiter, Packaging Engineer salary in Georgia: https://www.ziprecruiter.com/Salaries/Packaging-Engineer-Salary--in-Georgia
- ZipRecruiter, Production Scheduler salary in Georgia: https://www.ziprecruiter.com/Salaries/Production-Scheduler-Salary--in-Georgia
- ZipRecruiter, Automotive Program Manager jobs Marietta GA: https://www.ziprecruiter.com/Jobs/Automotive-Program-Manager/-in-Marietta,GA
- ZipRecruiter, APQP Engineer salary: https://www.ziprecruiter.com/Salaries/Apqp-Engineer-Salary
- Ladders, APQP Quality Engineer, Hartwell GA: https://www.theladders.com/job/apqp-quality-engineer-expert-connections-hartwell-ga_87944508

US billing rates and wrap rates
- GovDash, wrap rate guide: https://www.govdash.com/blog/wrap-rate-government-contracting-guide
- Cad Crowd, engineering design services cost: https://www.cadcrowd.com/blog/how-much-do-engineering-design-services-cost/
- Eng-Tips, billing rates thread: https://www.eng-tips.com/threads/billing-rates.521063/

Mexico wages, burden, FX, currency practice
- Tetakawi, Manufacturing Labor Costs in Mexico: 2026 Wage Benchmarks: https://tetakawi.com/blog/manufacturing-wages-in-mexico-executive-benchmark-guide/
- Indeed MX, Ingeniero industrial salaries Guanajuato (Silao 19,987 MXN/month): https://mx.indeed.com/career/ingeniero-industrial/salaries/Guanajuato
- Indeed MX, GKN Automotive Ingeniero de manufactura Guanajuato: https://mx.indeed.com/cmp/Gkn-Automotive/salaries/Ingeniero-a-de-manufactura/Guanajuato
- Indeed MX, Ingeniero de manufactura salaries Mexico: https://mx.indeed.com/career/ingeniero-de-manufactura/salaries
- Indeed MX, Ingeniero herramentales jobs Guanajuato: https://mx.indeed.com/q-ingeniero-herramentales-l-guanajuato-empleos.html
- OCC, Ingeniero de herramentales Guanajuato: https://www.occ.com.mx/empleos/de-ingeniero-de-herramentales/en-guanajuato/
- Computrabajo, Ingeniero APQP salary Mexico: https://mx.computrabajo.com/salarios/ingeniero-apqp
- Computrabajo, Ingeniero de procesos Guanajuato: https://mx.computrabajo.com/trabajo-de-ingeniero-de-procesos-en-guanajuato
- Deel, factores de integración IMSS 2026: https://www.deel.com/es/blog/factores-integracion-del-salario/
- CalculoSeguro, costo de empleado 2026: https://calculoseguro.mx/calculadora-costo-empleado/
- Banxico FIX (17.3015 on 2026-09-22): https://www.banxico.org.mx/tipcamb/llenarTiposCambioAction.do?idioma=sp
- Ley Monetaria, Art. 8: https://leyes-mx.com/ley_monetaria_de_los_estados_unidos_mexicanos/8.htm
- IDC, obligaciones en moneda extranjera: https://idconline.mx/corporativo/2023/10/03/cumplimiento-de-obligaciones-en-mexico-en-moneda-extranjera
- Cosmo Sourcing, Mexico sourcing guide 2026 (USD pricing, peso volatility): https://www.cosmosourcing.com/mexico-sourcing
- Fastmarkets, US-Mexico automotive supply chain pricing: https://www.fastmarkets.com/insights/why-cross%E2%80%91border-price-intelligence-is-now-critical-for-the-us-mexico-automotive-supply-chain/
- Border Assembly, automotive industry in the Bajío: https://borderassembly.com/automotive-industry-in-the-bajio/
- 4M Labs, nearshore rates Mexico 2026: https://4mlabs.io/en/blogs/nearshore-rates-mexico-2026/

Machine rates and trials
- MAPP, 2024 Machine Rate Report (members only): https://www.mappinc.com/resources/benchmarking-publications/2024-mapp-machine-rate-report/
- Plastics Business, The Complexity of Machine Rates (MAPP 2021: <45 t 32 USD/h, 1,000 t about 90 USD/h): https://plasticsbusinessmag.com/articles/2021/the-complexity-of-machine-rates-in-the-plastics-processing-industry/
- PlasticsToday, Pricing your work: the machine rate enigma (2023: 35 USD/h 25 to 100 t, 55 USD/h 601 to 700 t): https://www.plasticstoday.com/resin-pricing/pricing-your-work-the-machine-rate-enigma
- ZetarMold, injection molding cost calculator (100 t 30 to 50, 500 t 80 to 120, 1,000 t 150 to 250 USD/h): https://zetarmold.com/injection-molding-cost-calculator-formula-real-examples/
- Jino, injection moulding cost guide 2026 (30 to 120+ USD/h): https://jinoplastics.com/injection-moulding-cost/
- Jino, mould trial setup costs (300 to 1,500 USD per trial round, generic): https://jinoplastics.com/injection-mould-trial-setup-costs/
- Basilius, understanding machine rates (no standard method): https://www.basilius.com/blog/understanding-injection-molding-machine-rates/
