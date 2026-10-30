"""Silao SharePoint (mtdmexico VW316TAOSPA) folders -> SEP work items (file slots).

PLM2 has no project-level document area; SEP items are the agreed slots for
project documents (forms, evidence). Each project folder of the Silao library
is filed on the SEP item that fits it best. First matching prefix wins, so
specific prefixes come before their parents. None = not imported (finance,
photo dumps, other programs); those stay on the local mirror only.

Keys are paths relative to "Shared Documents/". Values: (project code, gate
code, item_no) or None.
"""

T, A = "VW316PA", "AU436"

SEP_MAP: list[tuple[str, tuple[str, str, int] | None]] = [
    # --- 01. MTNA -------------------------------------------------------------
    ("01. MTNA/04. Open Items List", (T, "B/RG6", 14)),
    ("01. MTNA", (T, "B/RG6", 43)),

    # --- 02. PBC / 01. Sales ---------------------------------------------------
    ("02. PBC/01. Sales/01. RFQ Info", (T, "K0/RG1", 18)),
    ("02. PBC/01. Sales/02. RFQ Re-Version", (T, "K0/RG1", 5)),
    ("02. PBC/01. Sales/03. Tooling control", (T, "D/RG4", 6)),
    ("02. PBC/01. Sales/04.ARG GS Wrapp", (T, "C/RG5", 2)),
    ("02. PBC/01. Sales", (T, "K0/RG1", 5)),

    # --- 02. PBC / 02. PM ------------------------------------------------------
    ("02. PBC/02. PM/01. Taos PA 2025 Part Number & Production Plan", (T, "K/RG2", 35)),
    ("02. PBC/02. PM/TAOS PA_Part number list", (T, "K/RG2", 35)),
    ("02. PBC/02. PM/02. QTR_Taos PA", (T, "E/RG3", 13)),
    ("02. PBC/02. PM/03. Kick Off", (T, "K/RG2", 10)),
    ("02. PBC/02. PM/04. Commitment", (T, "K/RG2", 1)),
    ("02. PBC/02. PM/05. QPN/01. RG2", (T, "K/RG2", 39)),
    ("02. PBC/02. PM/05. QPN/02. RG3", (T, "E/RG3", 31)),
    ("02. PBC/02. PM/05. QPN/03. RG4", (T, "D/RG4", 17)),
    ("02. PBC/02. PM/05. QPN/04. RG5", (T, "C/RG5", 38)),
    ("02. PBC/02. PM/05. QPN/05. RG6", (T, "B/RG6", 43)),
    ("02. PBC/02. PM/05. QPN", (T, "B/RG6", 43)),
    ("02. PBC/02. PM/06. Customer Evaluations", (T, "C/RG5", 7)),
    ("02. PBC/02. PM/07. FAKOM Research", (T, "E/RG3", 20)),
    ("02. PBC/02. PM/08. IBO Payments", None),
    ("02. PBC/02. PM/09. PMR", (T, "C/RG5", 38)),
    ("02. PBC/02. PM/11. Internal Project Evaluations", (T, "B/RG6", 22)),
    ("02. PBC/02. PM/12. LOI", (T, "K0/RG1", 6)),
    ("02. PBC/02. PM/13. Production Build Out Plan", (T, "C/RG5", 30)),
    ("02. PBC/02. PM/14. Checking Fixtures", (T, "E/RG3", 25)),
    ("02. PBC/02. PM/15. Commitment FAKOM", (T, "E/RG3", 20)),
    ("02. PBC/02. PM/16. Feasibility", (T, "K0/RG1", 1)),
    ("02. PBC/02. PM/17. Event Quantity", (T, "B/RG6", 12)),
    ("02. PBC/02. PM/18. Cubing", (T, "C/RG5", 8)),
    ("02. PBC/02. PM/19. VW Visits", (T, "E/RG3", 13)),
    ("02. PBC/02. PM/21. CPM", (T, "A/RG7", 4)),
    ("02. PBC/02. PM/22. VW Documents", (T, "K0/RG1", 18)),
    ("02. PBC/02. PM/23. Argentina FAKOM", (T, "E/RG3", 20)),
    ("02. PBC/02. PM/24. SFN 1", (T, "B/RG6", 21)),
    ("02. PBC/02. PM/25. SFN 2", (T, "B/RG6", 21)),
    ("02. PBC/02. PM/26. SOMO GOAL 2026", (T, "A/RG7", 1)),
    ("02. PBC/02. PM/27. INSOURCING MOLDS PLASESS", (T, "A/RG7", 14)),
    ("02. PBC/02. PM/28. RESIN CHANGE", (T, "A/RG7", 1)),
    ("02. PBC/02. PM/29. GOLF A8", None),  # separate RFQ (F MX I 25 251), not Taos PA
    ("02. PBC/02. PM/30. INSOURCING MOLDS SAKAIYA", (T, "A/RG7", 14)),
    ("02. PBC/02. PM/31. SOMO SPORT 2026", (T, "A/RG7", 1)),
    ("02. PBC/02. PM/32. SOMO WOLFSBURG 2028", (T, "A/RG7", 1)),
    ("02. PBC/02. PM", (T, "C/RG5", 38)),

    # --- 03. MTDM (plant side) ---------------------------------------------------
    ("03. MTDM/2YC Outlet Mold Final Data", None),       # 2YC = other program
    ("03. MTDM/MKZ Paint delovery issue", None),        # MKZ = other program
    ("03. MTDM/MTDM NM/2YC", None),
    ("03. MTDM/MTDM NM/Tiguan data toss", None),
    ("03. MTDM/MTDM NM/01. SAP", (T, "K/RG2", 35)),
    ("03. MTDM/MTDM NM/02. FAKOM Matrix", (T, "E/RG3", 20)),
    ("03. MTDM/MTDM NM/03. Investment Plan vs Actual", (T, "K/RG2", 38)),
    ("03. MTDM/MTDM NM/04. RESIN", (T, "E/RG3", 29)),
    ("03. MTDM/MTDM NM/05. Capacity", (T, "K0/RG1", 29)),
    ("03. MTDM/MTDM NM/06. Tickets", (T, "B/RG6", 14)),
    ("03. MTDM/MTDM NM/07. Shpping Document", (T, "B/RG6", 12)),
    ("03. MTDM/MTDM NM/08. Tooling Information", (T, "B/RG6", 27)),
    ("03. MTDM/MTDM NM/09. Package", (T, "K/RG2", 33)),
    ("03. MTDM/MTDM NM/10. Event parts preparation schedule", (T, "B/RG6", 12)),
    ("03. MTDM/MTDM NM/11. Process Development", (T, "D/RG4", 12)),
    ("03. MTDM/MTDM NM/12. HOE", (T, "C/RG5", 30)),
    ("03. MTDM/MTDM NM/13. Work Station", (T, "D/RG4", 11)),
    ("03. MTDM/MTDM NM/14. Mass Production FCST", (T, "K0/RG1", 29)),
    ("03. MTDM/MTDM NM/15. Modify Point", (T, "A/RG7", 1)),
    ("03. MTDM/MTDM NM/16. Test Parts Preparation", (T, "C/RG5", 18)),
    ("03. MTDM/MTDM NM/17. SFN2", (T, "B/RG6", 21)),
    ("03. MTDM/MTDM NM/18. Rack", (T, "K/RG2", 33)),
    ("03. MTDM/MTDM NM/19. LAYOUT", (T, "K/RG2", 31)),
    ("03. MTDM/MTDM NM/20. Change point", (T, "A/RG7", 1)),
    ("03. MTDM/MTDM NM/21. Assembly Movement line layout creation", (T, "K/RG2", 31)),
    ("03. MTDM/MTDM NM/22. POKAYOKE", (T, "K/RG2", 20)),
    ("03. MTDM/MTDM NM/23.  Taos & Tiguan Facility location check", (T, "K/RG2", 31)),
    ("03. MTDM/MTDM NM/24. EOA&Gate cut", (T, "D/RG4", 12)),
    ("03. MTDM/MTDM NM/25, Welding Machine AGR Modify", (T, "D/RG4", 12)),
    ("03. MTDM/MTDM NM/26. Assembly Jig Quote", (T, "D/RG4", 15)),
    ("03. MTDM/MTDM NM/Cost Summary", (T, "K/RG2", 38)),
    ("03. MTDM/MTDM NM/Gate Cutting_EOA", (T, "D/RG4", 12)),
    ("03. MTDM/MTDM NM/Paint", (T, "E/RG3", 29)),
    ("03. MTDM/MTDM NM/Photo", (T, "C/RG5", 8)),
    ("03. MTDM/MTDM NM/Schacht Blende", (T, "C/RG5", 8)),
    ("03. MTDM/MTDM NM", (T, "D/RG4", 12)),
    ("03. MTDM/MTDM Paint", (T, "E/RG3", 29)),
    ("03. MTDM/MTDM QC/Air bag CW45", None),            # photo dump (892 files)
    ("03. MTDM/MTDM QC/Airbag CW48 Mock up DEKORBLENDE ONLY", None),  # photo dump (2368 files)
    ("03. MTDM/MTDM QC/Cal Lab", (T, "C/RG5", 16)),
    ("03. MTDM/MTDM QC/Part Wrapped 417-418 CMM", (T, "C/RG5", 22)),
    ("03. MTDM/MTDM QC", (T, "C/RG5", 22)),
    ("03. MTDM/Packaging", (T, "K/RG2", 33)),
    ("03. MTDM/Taos PA BOM", (T, "K/RG2", 35)),

    # --- 04. purchasing ----------------------------------------------------------
    ("04.MTDM PUR", (T, "C/RG5", 35)),

    # --- 05. Data Transfer to KTX: project-level parts ----------------------------
    # (per-tool and per-part data under MTNA NME and Design go on the parts/tools)
    ("05. Data Transfer to KTX/QA/AU436", (A, "C/RG5", 9)),
    ("05. Data Transfer to KTX/QA/VW316PA/VW EP Specifications", (T, "K0/RG1", 18)),
    ("05. Data Transfer to KTX/QA/VW316PA", (T, "C/RG5", 9)),
    ("05. Data Transfer to KTX/MTNA NME/AU436/Injection Parameters", (A, "B/RG6", 26)),
    ("05. Data Transfer to KTX/MTNA NME/VW316 PA/Injection Parameters", (T, "B/RG6", 26)),
    ("05. Data Transfer to KTX/MTNA NME/AU436/Mold Transfer Sheets", (A, "A/RG7", 14)),
    ("05. Data Transfer to KTX/MTNA NME/VW316 PA/Mold Transfer Sheets", (T, "A/RG7", 14)),
    ("05. Data Transfer to KTX/MTNA NME/VW316 PA/Fixtures", (T, "E/RG3", 25)),
    ("05. Data Transfer to KTX/MTNA NME/AU436/Demo Molds/Fixtures", (A, "E/RG3", 25)),

    ("05. Data Transfer to KTX/MTNA NME/AU436/AU436_INJ_ControlDimensions", (A, "C/RG5", 23)),
    ("05. Data Transfer to KTX/MTNA NME/AU436/AU436_QC_CriticalDimensions", (A, "C/RG5", 23)),
    ("05. Data Transfer to KTX/MTNA NME/VW316 PA/VW316.QC_Critical Dimensions", (T, "C/RG5", 23)),
    ("05. Data Transfer to KTX/MTNA NME/VW316 PA/VW316PA.INJ_ControlDimensions", (T, "C/RG5", 23)),
    ("05. Data Transfer to KTX/MTNA NME/Press Info", (T, "B/RG6", 29)),
    ("05. Data Transfer to KTX/MTNA NME/AU436_VW316_Transfer Documents", (T, "A/RG7", 14)),
    ("05. Data Transfer to KTX/MTNA NME/MTDM Tooling repair log", (T, "A/RG7", 14)),
    ("05. Data Transfer to KTX/MTNA NME/MTNA.PROVIDED.SPARE.PARTS.LIST", (T, "B/RG6", 31)),
    # customer release packages / set lists (per-part drawings and CAD go on the parts)
    ("05. Data Transfer to KTX/Design/VW Group Data/AU436/210920___AU436", (A, "K0/RG1", 18)),
    ("05. Data Transfer to KTX/Design/VW Group Data/AU436/AU436 K RELEASE", (A, "E/RG3", 16)),
    ("05. Data Transfer to KTX/Design/VW Group Data/AU436/AU436_AIRVENT_B-RELEASE", (A, "E/RG3", 16)),
    ("05. Data Transfer to KTX/Design/VW Group Data/VW 316_5ME/00.-Moriroku_Setliste", (T, "K/RG2", 35)),
    ("05. Data Transfer to KTX/Design/VW Group Data/VW 316_5ME/CW07 B REL", (T, "E/RG3", 16)),
    ("05. Data Transfer to KTX/Design/VW Group Data/VW 316_5ME/VW316 TAOS PA - Grain Map", (T, "E/RG3", 20)),
    ("05. Data Transfer to KTX/Design/VW Group Data/VW 316_5ME/VW316-5-ME_TDL_Update", (T, "K/RG2", 35)),
    ("02. PBC/07_Injection Capacity", (T, "K0/RG1", 29)),
    ("02. PBC/08_Injection Capacity", (T, "K0/RG1", 29)),
    ("K4T", (T, "K0/RG1", 18)),

    # --- General --------------------------------------------------------------------
    ("General/01. LL Taos PA", (T, "K0/RG1", 16)),
    ("General", (T, "K0/RG1", 18)),
]

# File types never imported (photo/video dumps stay on the mirror).
SKIP_EXT = {".avi", ".mov", ".mp4", ".heic", ".bmp", ".db", ".tmp", ".lnk"}
SKIP_NAME_PREFIX = ("~$",)  # Office lock files


def sep_slot(rel_path: str):
    """(project, gate, item_no) for a library-relative path, None = not imported,
    'part' = handled by the part/tool import (no SEP slot)."""
    for prefix, slot in SEP_MAP:
        if rel_path == prefix or rel_path.startswith(prefix + "/") or (
                rel_path.startswith(prefix) and "/" not in rel_path[len(prefix):]):
            return slot
    return "part"
