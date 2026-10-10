"""BR167 Daimler / MBUSI PLM package -> JSON + staged drawings for import_br167.py.

Runs on the WSL host (needs openpyxl, reads the package on C:). The package
was built 2026-10-02 from P:\\1316_BR167_Daimler (read-only scan); its index
00_BR167_PLM_INDEX.xlsx is the source. P: itself is never touched here.

    python3 backend/scripts/br167_extract.py [--pkg <package root>]

Writes backend/scripts/br167_stage/br167.json and copies the current drawing
PDFs to backend/scripts/br167_stage/drawings/ (git-ignored).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
from collections import OrderedDict, defaultdict

import openpyxl

PKG = "/mnt/c/Users/christoph.demmler/Downloads/BR167_PLM"
STAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "br167_stage")
P_ROOT = "P:\\1316_BR167_Daimler"
UNC_ROOT = "\\\\172.17.33.2\\Projects$\\1316_BR167_Daimler"

# Lamellas 6-9 run on tools 0823/0824 (article number segment, P: tool folders
# tagged 823/824); the Part-BOM repeats tool 0822 for them.
MISSING_TOOLS = {"0823": "TOOL LAMELLA 6,7", "0824": "TOOL LAMELLA 8,9"}
# Welding equipment: assembles the center consoles, not a BOM line.
EQUIPMENT = {"WM94SW", "91-0013"}

# Drawings that are not in Article_Master's "Drawing in package" column.
# (relative path in the package, article, note)
EXTRA_DRAWINGS = [
    ("01_Window_Frame/04_Drawings/50-0785_Clip Loudsp/017842-0C00-Bf_06072016154849.pdf", "50-0785", "Raymond clip drawing"),
    ("01_Window_Frame/04_Drawings/50-0786_Clip Sunblind/011511-0C00-Db_24082016122537.pdf", "50-0786", "Raymond clip drawing"),
    ("01_Window_Frame/04_Drawings/50-0801_Zeichnung.pdf", "50-0801", "Carrier drawing"),
    ("01_Window_Frame/04_Drawings/2018-09-24_ZGS002/A1677272501_AKUSTIKSCHAUM_002_DWG_24092018.pdf", "50-0803", "Daimler A1677272501 ZGS 002, 2018-09-24"),
    ("01_Window_Frame/04_Drawings/D.3.12_PPAP Green - 837_838/_A1677272501_28.pdf", "50-0803", "Daimler A1677272501 from PPAP green 0837/0838"),
    ("02_Center_Console/04_Drawings/2017-03-27/50-0264_Grammer_Zeichnung_2017-03-27.pdf", "50-0264", "Grammer clip drawing 2017-03-27"),
    ("03_Lamellas/04_Drawings/65-0031/2017-12-04_BR167_Lamellen_Feurer.pdf", "65-0031", "Feurer packaging drawing 2017-12-04"),
]


def s(v):
    if v is None:
        return None
    v = str(v).strip()
    return None if v in ("", "-", "None") else v


def num(v):
    v = s(v)
    if v is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", v)
    return float(m.group(0).replace(",", ".")) if m else None


def cavities(v):
    v = s(v)
    if v is None:
        return None
    # The layout as written ("1+1"), never summed.
    m = re.search(r"\d+(?:\s*\+\s*\d+)*", v)
    return re.sub(r"\s+", "", m.group(0)) if m else None


SOP_MONTHS = {"Jan": 1, "Feb": 2, "Mrz": 3, "Mär": 3, "Apr": 4, "Mai": 5, "Jun": 6, "Jul": 7,
              "Aug": 8, "Sep": 9, "Okt": 10, "Nov": 11, "Dez": 12}


def sop_date(v):
    m = re.match(r"(\w+)\.?\s*(\d{4})", s(v) or "")
    if m and m.group(1)[:3] in SOP_MONTHS:
        return f"{m.group(2)}-{SOP_MONTHS[m.group(1)[:3]]:02d}-01"
    return None


def classify(t, group, artnr):
    """(item_category, part_type) from Part-BOM type + article group."""
    if artnr in EQUIPMENT:
        return "assembly_equipment", "purchased"
    if t == "W":
        return "tool", "purchased"
    if group.endswith("-RM"):
        return "article", "purchased"
    if group == "AS-FG":
        return "article", "sub_assembly"
    return "article", "internal_mfg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default=PKG)
    args = ap.parse_args()
    wb = openpyxl.load_workbook(os.path.join(args.pkg, "00_BR167_PLM_INDEX.xlsx"), read_only=True)
    am = list(wb["Article_Master"].iter_rows(values_only=True))[1:]
    tools_sheet = list(wb["Tools_Old_New"].iter_rows(values_only=True))[1:]
    bom_rows = list(wb["BOM_Structure"].iter_rows(values_only=True))[1:]
    link_folders = list(wb["Link_Folders"].iter_rows(values_only=True))[1:]

    # --- parts (first Article_Master row per article wins) -------------------
    parts = OrderedDict()
    for r in am:
        artnr = s(r[2])
        if not artnr or artnr in parts:
            continue
        cat, ptype = classify(r[4], r[5] or "", artnr)
        p = {
            "artnr": artnr, "name": s(r[3]), "type": r[4], "group": s(r[5]),
            "item_category": cat, "part_type": ptype, "product": s(r[0]),
            "customer_part_number": s(r[8]), "level": s(r[9]), "drawing_no": s(r[10]),
            "colour": s(r[11]), "surface": s(r[12]), "single_weight": s(r[14]),
            "cavities": s(r[16]), "shot_weight": s(r[18]), "cycle": s(r[19]),
            "machine": s(r[21]), "parts_tray": s(r[22]), "parts_pallet": s(r[23]),
            "dimension": s(r[24]), "supplier": s(r[26]), "tool_ref": s(r[27]),
            "pack_code": s(r[28]), "sop": sop_date(r[29]), "sop_text": s(r[29]),
            "total_parts": s(r[30]), "links": [],
        }
        if p["item_category"] == "tool":
            p["toolmaker"] = p["supplier"]
        parts[artnr] = p

    for nr, name in MISSING_TOOLS.items():
        base = parts["0822"]
        parts[nr] = {**base, "artnr": nr, "name": name, "tool_ref": nr, "links": [],
                     "flag": "Not in the Daimler Part-BOM (it lists tool 0822 for lamellas 6-9). "
                             "Cavities/press/maker copied from 0822, verify."}

    # Tools_Old_New: capacity tools 2024/25 + PO/TTS on originals
    for r in tools_sheet:
        nr = s(r[0])
        if nr in parts:
            continue
        base = parts.get(nr.split("-")[0])
        parts[nr] = {
            "artnr": nr, "name": f"TOOL {s(r[2])} ({nr})", "type": "W", "group": "TOOL",
            "item_category": "tool", "part_type": "purchased", "product": s(r[3]),
            "customer_part_number": None, "level": None, "drawing_no": None,
            "colour": None, "surface": None, "single_weight": None,
            "cavities": s(r[6]), "shot_weight": s(r[9]), "cycle": s(r[8]), "machine": s(r[7]),
            "supplier": s(r[5]), "toolmaker": s(r[5]), "tool_ref": nr, "status": s(r[1]),
            "customer_pns_text": s(r[4]), "po_tts": s(r[12]), "notes": s(r[13]),
            "replaces": base["artnr"] if base else None, "links": [],
        }
        if s(r[14]):
            parts[nr]["links"].append({"category": "Tool data (new tools 2024/25)", "path": s(r[14])})

    # --- tool -> article relations --------------------------------------------
    produces = defaultdict(list)
    for t in [p for p in parts.values() if p["item_category"] == "tool"]:
        seg = t["artnr"].split("-")[0]
        for a in parts.values():
            bits = a["artnr"].split("-")
            if (a["item_category"] == "article" and len(bits) >= 3 and bits[1] == seg
                    and (a["group"] or "").startswith("IM-")):
                produces[t["artnr"]].append(a["artnr"])
    assembles = {eq: ["20-0825-243-0", "20-0826-243-0"] for eq in EQUIPMENT}

    # --- BOM (Part-BOM is flattened; rebuild levels) -------------------------
    groups = OrderedDict()
    for r in bom_rows:
        groups.setdefault(s(r[0]), []).append(r)
    bom = defaultdict(OrderedDict)  # parent -> child -> {qty, unit, note}

    def add(parent, child, qty):
        if child == parent or child not in parts:
            return
        c = parts[child]
        if c["item_category"] in ("tool", "assembly_equipment"):
            return
        if child in bom[parent]:
            return
        q = num(qty)
        line = {"qty": q or 1.0, "unit": "pcs"}
        if q is None and c["type"] == "M":
            line.update(unit="as req.", note="Qty per shot weight (Part-BOM gives no count)")
        elif q is None:
            line.update(note="Qty not given in Part-BOM")
        bom[parent][child] = line

    for parent, rows in groups.items():
        children = [r for r in rows if s(r[4]) != parent]
        headers, prev_header, in_blocks = [], False, False
        for r in children:
            c = s(r[4])
            if re.match(r"^10-\d{4}-001-", c):
                in_blocks = True
            if not in_blocks:
                add(parent, c, r[7])
                continue
            if c.startswith("10-"):
                headers = headers + [c] if prev_header else [c]
                prev_header = True
                continue
            prev_header = False
            for h in headers:
                add(h, c, r[7])
    # painted 10-SSSS-243-n contains molded 10-SSSS-001-n
    for a in list(parts):
        m = re.match(r"^10-(\d{4})-243-(\d+)$", a)
        if m:
            molded = f"10-{m.group(1)}-001-{m.group(2)}"
            if molded in parts:
                bom[a] = OrderedDict([(molded, {"qty": 1.0, "unit": "pcs"}), *bom[a].items()])
    # LH rows lost their children to the RH row (row-order inference)
    for lh, rh in (("20-0851-001-0", "20-0851-002-0"), ("20-0841-001-0", "20-0841-002-0")):
        if not bom.get(lh) and bom.get(rh):
            bom[lh] = OrderedDict((k, {**v, "note": ((v.get("note") or "") + " Copied from RH (shared Part-BOM rows).").strip()})
                                  for k, v in bom[rh].items())

    # --- P: link references (folders, never files) ---------------------------
    by_tool = defaultdict(lambda: defaultdict(list))
    for r in link_folders:
        cat, tools, folder = s(r[0]), s(r[2]), s(r[3])
        if not cat or cat.startswith("DOC") or not folder:
            continue
        for t in re.findall(r"\d+", tools or ""):
            by_tool[t.zfill(4)][cat].append(folder)
        m = re.search(r"\\((?:10|20|25|50|65)-\d{4}(?:-\d{3}-\d+)?)", folder)
        if m and m.group(1) in parts and cat == "3D CAD / native data":
            parts[m.group(1)]["links"].append({"category": cat, "path": folder})
    for tnr, cats in by_tool.items():
        if tnr not in parts:
            continue
        for cat, folders in sorted(cats.items()):
            # trim to 3 levels below the project root (product\area\sub-area), dedupe
            roots = []
            for f in folders:
                rest = f[len(P_ROOT) + 1:].split("\\") if f.startswith(P_ROOT) else f.split("\\")
                r = P_ROOT + "\\" + "\\".join(rest[:3])
                if r not in roots:
                    roots.append(r)
            for r in roots:
                parts[tnr]["links"].append({"category": cat, "path": r,
                                            "folders": sum(f.startswith(r) for f in folders)})

    # --- drawings ------------------------------------------------------------
    drawings = []
    seen = set()
    for r in am:
        artnr, rel = s(r[2]), s(r[32])
        if artnr and rel and (artnr, rel) not in seen:
            seen.add((artnr, rel))
            drawings.append({"artnr": artnr, "rel": rel, "note": f"Drawing {s(r[10])} (Part-BOM level {s(r[9])})"})
    for rel, artnr, note in EXTRA_DRAWINGS:
        drawings.append({"artnr": artnr, "rel": rel, "note": note})
    os.makedirs(os.path.join(STAGE, "drawings"), exist_ok=True)
    for d in drawings:
        src = os.path.join(args.pkg, d["rel"])
        d["file"] = os.path.basename(d["rel"])
        d["staged"] = f"drawings/{hashlib.md5(d['rel'].encode()).hexdigest()[:8]}_{d['file']}"
        dst = os.path.join(STAGE, d["staged"])
        if not os.path.exists(dst):
            shutil.copy2(src, dst)

    out = {
        "project": {"code": "91", "name": "BR167 Daimler / MBUSI",
                    "p_root": P_ROOT, "unc_root": UNC_ROOT},
        "parts": list(parts.values()),
        "bom": {p: [{"child": c, **v} for c, v in kids.items()] for p, kids in bom.items() if kids},
        "produces": produces, "assembles": assembles, "drawings": drawings,
    }
    with open(os.path.join(STAGE, "br167.json"), "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"parts={len(parts)} tools={sum(p['item_category'] == 'tool' for p in parts.values())} "
          f"bom_parents={len(out['bom'])} bom_lines={sum(len(v) for v in out['bom'].values())} "
          f"produces={sum(len(v) for v in produces.values())} drawings={len(drawings)}")


if __name__ == "__main__":
    main()
