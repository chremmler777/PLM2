---
name: strategic-business-tooling-map-2026-10-08
description: Huascar's "Strategic Bussiness.xlsx" mapped to our RFQs with tooling quotes per tool/shop, tariff rules, RFQ25/26 CBD numbers, active-RFQ answer (2026-10-07/08)
metadata:
  type: project
---

Input: Desktop\TTTTTTTTTTTTTTTTTTTT\Strategic Bussiness.xlsx (sheet "Strategic BS", col N "Tooling estimated Cost" was empty).
Output: same folder `Strategic Bussiness - tooling refs v2.xlsx` (v1 was open in Excel). Original untouched.
Builder script (session scratchpad, not kept): reads U:\RFQ quote files + U:\RFQ\_Tool_Cost_Calibration\2026-09-30 jsonl dumps.

**User rules for this work**
- Quotes only in the cost column - never the auto estimator (RFQ-RFQ-xx "Cost Estimate" tab) and not KTX estimate sheets (Mobis garnish Mold Cost Comp: China = 70% of Canada, a calc).
- Show per tool: article no., toolshop, quote ref; counts (tools in RFQ / considered), shops, spread, separate FZ columns, tariff status.
- Ex/incl tariff must be explicit per shop; RFQ25 and RFQ26 shown split.

**Mapping (cost col = FZ DAP ex tariff where FZ quoted)**
- Bosch EVO-X 2195 -> RFQ21, FZ only, 1 of 3 fascia tools (60100006756702) 109,800; no tariff line.
- OPM GM Lyriq spoiler bracket -> 260227 Spoiler, NextGen 7251 Canard Bracket (GM 26474398) 308,415 only.
- Toyota 2213 cluster -> RFQ29 (55405-0E110), no toolshop quotes. Toyota cowl -> RFQ37 (400D), FZ 481,859 / 653,382 incl; Hitop ball-park 421,400.
- Brose Scout seat back -> RFQ25 (PLM 2277) + RFQ26 (PLM 1994, FZ NOMINATED).
- Inteva BR267 -> RFQ31 speaker grille: FZ 92,000 (no tariff line), Hitop 69,800 + 28,000 tariff, NextGen 198,270 incl 15%.
- Moriroku Pilot tray -> 260112: FZ 103,000 (tariff col = 0), VHP 81,400, NextGen 202,350.
- Yanfeng 2194 Y0797228 -> RFQ20 takeover (existing FZ-24008 tool), 0 new tooling. BMW 1748 = running project, no RFQ.
- Nothing on U: for Kia, Seco, Mobis end caps/air vents, Hyundai various, Navistar bezels, Rivian R3 cowl, Odyssey tray. DNMEX RFQ35 weak match only.

**RFQ25/26 CBD (KTX quote mask, S1 = DAP ex tariff, L = S1 + T1)** - ex / incl tariff
- RFQ25: FZ V9 09-30 Glow HRS 555,200 / 765,920; FlexFlow 651,200 / 903,749; Hitop 386,400 / 511,480; BH 559,850 / 783,650.
- RFQ26: FZ V8 09-15 393,760 / 545,502 (nominated); Hitop 296,450 / 385,690; BH 445,800 / 567,650.
- Tariff basis differs by shop: FZ 43.57% on tool+HR+grain, Hitop 40% on tool+HR, BH own figure (~29-42%, L also incl. financial cost / USA grain prep).
- NextGen RFQ25 CBD has prices in wrong columns (MIC price under Pivot) - use the PDFs: 8315 lists 15% NOT included; 8068/8316 say no tariffs, no amount.
- FlexFlow vs Glow is RFQ25, not RFQ26.

**Context told to Huascar (email 2026-10-08):** only active RFQs are 25/26, 40, 42; everything older is outside quote validity (FZ 30 days) and tariffs must be re-checked. RFQ39 (BMW G45 LCI) already has FZ/Hitop/BH quotes (09-15..09-28) - not waiting on toolshops.

**How to apply:** reuse these numbers/refs when the strategic list or Brose tooling comes up again; re-verify validity dates before quoting them as current. Related: [[brose-award-import-2026-09-02]], [[brose-resin-status-2026-09-30]].
