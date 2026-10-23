---
name: brose-resin-status-2026-09-30
description: 1994/2277 Brose resin nomination status after Christine Kaufmann's mails up to 2026-09-30; what is safe vs open
metadata:
  type: project
---

Procurement (Christine Kaufmann) mails, 2026-09-23..30, in Desktop\Christine (.msg).
Full technical review lives in MaterialDB `docs/review-1994-brose-resin-2026-09-24.md`.

Safe: PC/ABS Decor Cover 206.881.793 -> Bayblend T85 XF black, existing 40-0221
(Covestro confirmed VW 50026-GK1 + TL 52231 A&B on 2026-09-28; Pulse dropped).
REZYcom PP/PA6 rejected (recycled). Colour NM0 confirmed by Brose on 887.233,
881.479, 883.607 (no paint).

Open at 2026-09-30: PA66 Pivot Axis (Radilon A HSK 333 BK offered 09-30, not in
MaterialDB, needs VW 50127 + GK1 confirmation), PA6 GF15 pick (Eplamid vs Chemlon
vs Ultramid 40-0130), PP TD20 Hostacom NM0 grade + price, Romiloy release/virgin +
budget, TPU second offer + NM0 batching, NM0 colour masters from Brose, PV 3952,
2277 back panel colour, Karl's resin budgets.

PLM prod: 1994 articles all material_source=new (free text), 2277 mostly empty;
descriptions still carry old RFQ colour text (MIC 3 colors etc.).
Related: [[1994-brose-volume-sheet-2026-09-23]], [[brose-award-import-2026-09-02]]

Applied on prod 2026-09-30 13:15 (backup db-backups/plm2-before-resin-status-20260930-131506.sql.gz)
via backend/scripts/update_brose_resin_status.py (323f12c3, not pushed): "Resin status 2026-09-30"
comment + flag on part.material for 18 articles, 793 linked to 40-0221, 2277 drawing materials set.
RFQ2 bom_item 341 (Pivot Axis) still PA6-GF15 (material_id 31), not changed; PLM has PA66.

Later 2026-09-30 (Christoph): all six resins confirmed by Purchasing: T85 XF 40-0221, EPLAMID 6 H G15 BK005,
Hostacom TRC 352N, ROMILOY 3020/11, RADILON A HSK 333 BK, Pearlthane 11T95P. NM0 is batched by us (no supplier
confirmed NM0). Suppliers will send the VW/TL/PV 3952/GK1 statements. Ask Brose: pivot axis in standard black OK?
Meeting list: Desktop\Christine\1994-2277 Resin Meeting Checklist 2026-09-30.xlsx + artifact 5Xs6TtJ3ALURSwwMkVSZ1Y.
PLM worksheet notes still say "not nominated" (not yet updated).

Documented on prod 2026-09-30 15:53 (backups materialdb-before-brose-nomination-*, plm2-before-resin-nominated-*):
MaterialDB #92 RADILON added (research, approved, TDS + 23 values); #88/#90/#91 approved; notes on 17/19.
PLM: all 18 articles part.material confirmed + linked (PP -> 40-0223, PA6 -> #88, 607 -> #90, G05 -> #92,
G07 -> #91); part.colour_code open on G05 and the 4 PP-TD20 2277 parts (Brose colour questions).
Scripts: plm2 update_brose_resin_nominated.py, MaterialDB app/scripts/brose_resin_nomination.py (not pushed).

Shrinkage (2026-09-30, verified against the PDFs): T85 XF 0.5-0.7 both (ISO 2577, 150x105x3, 260/80);
EPLAMID 0.7 par / 1.0 norm (ISO 294-4, 2 mm); ROMILOY 0.8-1.0 no direction; RADILON 1.2 / 1.3 (ISO 294-4,
290/70/60, thickness not stated); Hostacom TRC 352N and Pearlthane 11T95P none on sheet. Online search found
nothing authoritative -> suppliers must give values. Built worksheet shrink columns + tool shrink fields
(plm2 9dc78b3d..4a092026, migration 110; MaterialDB e00f14c), pushed and DEPLOYED to prod 2026-09-30 18:34.
Covestro confirmation .msg added to MaterialDB 40-0221 as approval doc (prod).

Documented on prod 2026-09-30 20:01 (backup plm2-before-tool-shrink-20260930-200152): tool shrink
199401/199403 0.7/1.0, 199407 0.9, 199409 0.65, 227704 1.25 (flags confirmed, basis in comments);
Hostacom tools + 227705 still open (supplier request to Christine). NM0 set on 206.883.607 and _G07.
BOM for Purchasing: Desktop\Christine\1994-2277 BOM PLM prod 2026-09-30.xlsx (pictures, purchased parts).
Pivot axis colour (standard black?) still open with Brose.
