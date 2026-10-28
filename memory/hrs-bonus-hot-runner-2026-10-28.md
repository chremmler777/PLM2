---
name: hrs-bonus-hot-runner-2026-10-28
description: HRS group bonus (Christine 10/28) - PARKED 2026-10-28, Brandon (toolshop) tracks HRS quotes/orders by hand; per-tool feed system of 1994/2277 from FZ quotes kept as reference
metadata:
  type: project
---
Christine (procurement) 2026-10-28: group bonus agreement with HRSflow / Oerlikon / Inglass, including hot runners our
toolmakers buy. Every January each plant reports per HRS item: T2 (name/country/city), toolmaker (name/country/city),
application, drops, tool code. Source for new tools should be PLM2.

PLM2 today: no hot runner fields; suppliers only have a free-text address (FZ Tools empty); T2 = plant.location
"Toccoa, GA, USA"; 2277 tools have no toolmaker (Christoph: FZ, V10 standard without FlexFlow, Cody 10/26).

Feed system per tool (quoted, not as-built):
- 199401 HRS hot tips 4; 199405 HRS valve sequential 4; 199409 HRS hot tips 2.
- 199402/03/04/06/07/08/10: heated sprue (no HR), 1 each. FZ's own RFQ26 quote "Hot Runner System" column + RFQ2 TLD
  open_sprue sprue_type heated; make not stated, P2 = 0 (inside the mold price).
- 227701/227702 HRS 8 regular SVG + 4 GLOW = 12; 227703 4 SVG + 2 GLOW = 6; 227704 hot tips 2; 227705 open 4
  (FZ 20260930 standard quote, U:\RFQ\RFQ25...\Quote In; RFQ2 V10 import just says "HRS SVG 12/6").
- Where it lives: RFQ2 tooling_offer_lines.tech (hot_runner_make, drops_quoted); tooling_calcs HR fields empty,
  tooling_variant_items.num_drops = 1 everywhere (default, unusable).

PARKED 2026-10-28 (Christoph): nothing to build; Brandon (toolshop) tracks HRS quotes/orders by hand until a system
exists. 2277 back panel HR type (227701/02/03) stays OPEN: regular SVG vs FlexFlow One, decision expected mid-November 2026.

Design as discussed (for when it is unparked): parts tool_hr_make / tool_hr_type (incl. "heated sprue") / tool_hr_drops /
tool_hr_ordered_on / tool_hr_source; suppliers country + city; worksheet columns; cross-project xlsx report
(application = Brose no. + part name + program/Scout; explicit "none" for cold tools); backfill from the quotes.
Estimate 1-1.5 days. Open: the sprue make (HRS?) and what GLOW is, both to confirm with FZ BOM / HRS order confirmation.
