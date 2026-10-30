"""Build the Silao import stage (silao.json + files/) from the extracted program
data and the local SharePoint mirror. Runs on the WSL host; import_silao.py then
loads the stage inside the PLM backend container.

    python3 scripts/silao_extract.py --extract <dir with taos.json, au436.json>
        --mirror <Assistant>/state/silao-sp --stage <stage dir> [--files]

Without --files only silao.json is written (and checked); --files also
hard-links the selected mirror files into <stage>/files/ (same disk, no copy).

Unknown numbers are never invented: a part without a real number is left out
and listed under "held" for Christoph (ask before placeholders).
"""
import argparse
import hashlib
import json
import os
import re
from collections import Counter

from silao_sep_map import SKIP_EXT, SKIP_NAME_PREFIX, sep_slot

T, A = "VW316PA", "AU436"
FZ_SUPPLIER_ID = 1  # "FZ Tools" in suppliers

PROJECTS = [
    {"code": T, "name": "VW Taos PA (VW316/5) Silao", "customer_naming": "vw",
     "description": (
         "VW Taos PA (VW316/5 facelift) instrument panel decor (Kombiblende FS/BFS, Dekorblende, "
         "Radioblende, Mitte air vent) and door trim inserts (TIB FR/RR), made at KTX Silao (ex "
         "Moriroku MTDM). Customers: SAS Mexico / Forvia (Faurecia) Mexico; versions MEXICO, SAM/ARG, "
         "GOAL, SPORT.\nImported 2026-10-30 from SharePoint mtdmexico.sharepoint.com/sites/VW316TAOSPA "
         "(MTNA data transfer April/May 2025; part number list 2026-10-16) and Christoph's mail. "
         "Project documents are filed on the SEP items; the full library mirror is kept on the "
         "Assistant PC (state/silao-sp).")},
    {"code": A, "name": "Audi Q5 AU436 air vents Silao", "customer_naming": "vw",
     "description": (
         "Audi Q5 (AU436) air vents: Ausstroemer FS/BFS LL+RL and Mitte, Basis/High trims, made at KTX "
         "Silao (ex Moriroku MTDM); molds 0026M-0066M (8 run at Safe Demo Technic).\nImported 2026-10-30 "
         "from SharePoint mtdmexico.sharepoint.com/sites/VW316TAOSPA (MTNA data transfer April 2025) and "
         "Christoph's mail. Project documents are filed on the SEP items.")},
]

FILE_TYPE = {  # extract kind -> (RevisionFile.file_type, kind)
    "drawing_2d": ("drawing", "DRW"), "cad_3d": ("cad", None), "mold_spec": ("document", "SPEC"),
    "transfer_sheet": ("document", "XFER"), "parts_list": ("document", "PL"),
    "steel_cert": ("document", "CERT"), "hot_runner": ("drawing", "HR"),
    "moldflow": ("document", "MFL"), "graining": ("document", "GRN"),
    "test_report": ("test_result", None), "bom": ("document", "BOM"), "other": ("document", None),
}


# Taos door molds: legacy tool numbers from Huascar's clamp-force mail ("Door Tibs",
# 2026-08-27). They are not Toccoa tools (Toccoa 3284/3285 are BMW G05 underbody).
DOOR_TOOLS = {
    "MTDM-TIB-061": "V-3281",   # TIB Dekore LI 2GJ.867.439.B
    "SAK-440": "V-3282",        # TIB Dekore RE 2GJ.867.440
    "SAK-440B": "V-3283",       # TIB Dekore RE 2GJ.867.440.B
    "MTDM-TIB-062": "V-3284",   # TIB Dekore RE 2GJ.867.440.D
    "MTDM-TIB-062A": "V-3285",  # TIB Dekore RE 2GJ.867.440.E
    "MTDM-TIB-449": "V-3286",   # TIB Zierrahmen LI/RE 2GJ.867.449/450 (one family tool)
    "MTDM-TIB-450": "V-3286",
}
DOOR_NOTE = ("Door TIB mold number from the clamp-force calculation in 'Door Tibs' (Huascar Miranda, "
             "2026-08-27): V-3281..V-3286. Gate shadow / flash work Aug-Sep 2026: impact plates "
             "ground and shimmed, slides adjusted, trials on 180T/360T; required clamp force "
             "2,186-3,956 kN (series press 175T is too small). Resin now Bayblend T85XF.")

# Changes since the SharePoint state, from Christoph's mail (2025-11 .. 2026-10).
# (project, match: part/tool numbers or customer-number prefixes, text)
CHANGES = [
    (A, ["8MB.820.901", "8MC.820.902", "0026M", "0055M"],
     "LCMEI-7386 'Y' gap Blende FS LHD+RHD (2026-02..10): rib variants V1-V3; Audi and Uwe settled on V2 "
     "(shorter rib at the angled section, +0.104 cm3 / +0.114 g PC/ABS, no runner change). Quoted 36 h "
     "(Audi buyer wants 18 h); V2 LHD print, fit trial at Audi 2026-10-26; commercial deal open. "
     "Tool NOT changed, no 2D/3D release yet. Earlier (2025-11..2026-03): cross-dome stiffening, rib "
     "version instead of honeycomb, 2 new sub-inserts + shouldered block ejector, feasible LHD+RHD."),
    (A, ["0033M", "0060M", "8MB.820.901-AU436-0007", "8MB.820.902-AU436-0007"],
     "LCMEI-7815 Schlitten FS/BFS/Mitte LL+RL (2026-01..10): 4 stop ribs with contact (top 1.6+0.8 mm, "
     "bottom 0.4 mm), 4.036-4.066 g per slide, cycle +2 s, 36 h x 75 EUR. New drawings 260316 in KVS "
     "2026-04-16, Audi GO before 2026-08-14. Tools 0033M/0060M back from toolshop with ribs 2026-10-14; "
     "K30 graining (EDM) of the ribs still open. Note: tool 3D showed 2 ribs per part before the change "
     "(customer data none), open question 2026-02-17."),
    (A, ["0045M", "8MB.820.901-AU436-0008"],
     "Force feeling (2025-12..2026-01, merged into LCMEI-7815): Kunststoffachse matching area +0.20 mm, "
     "+0.002 g per axle, no runner or drawing change. Implementation in the tool unverified."),
    (A, ["0051M", "0052M"],
     "Schliessklappe 2K capacity (2025-12..2026-02): volume increase, cycle -15%, quote for a new "
     "2/2+2/2 index-plate tool (Arburg); 'Kappa' tool problems. Decision unverified."),
    (A, ["8MB.820.901", "8MB.820.902", "8MA.820.951"],
     "Drawing update 2026-03-16 (KTX, in KVS, sent by Uwe 2026-07-27 / 2026-10-06): FS DRW_TZ 005, "
     "BFS DRW_TZ 004, Mitte DRW_TZ 004, replacing 241210/241105_CSI. Filed as revision 2."),
    (T, ["V-3281", "V-3282", "V-3283", "V-3284", "V-3285", "V-3286"], DOOR_NOTE),
    (T, ["0079M", "0080M"],
     "Mold 3D (STEP) re-requested from FZ (FZ-23024/23025, Aug 2026): the SharePoint STEP files were "
     "corrupt; new data came via a transfernow link (may have expired, ask Joshua Liu)."),
    (T, ["0081M", "0082M", "0083M", "0085M", "0086M"],
     "2K anti-squeak TPE (Blende FS/BFS/Mitte): proposal Sarlink TPV 4139D -> Santoprene 123-40 (40-0334, "
     "Toccoa overstock), Apr 2026; only after sampling, measurement and Cpk. Outcome unverified."),
    (T, ["105100019", "102100064"],
     "Clip supplier switch (Aug 2026): ARaymond edge clip 241179 / cage nut 017562 vs Termax 26013 / "
     "26017; drawing review done, sample assembly test pending."),
]
CHANGE_GENERAL = {
    T: ("Changes since the SharePoint state (mail): Silao reports the mold 3D data on SharePoint does not "
        "match the physical tools (Victor Martinez, 2025-12-03); Taos PA ARG wrapped Blende Oben FS/BFS "
        "(2GK.858.415) reactivation requested by VWM (2026-07), wrapping supplier open; Taos PA Sport silver "
        "anodized paint trials (May 2026); DEMO-molded parts planned to move into KTX Silao (2026, "
        "transfer unverified); resin change GX-90 / A35-105 -> Bayblend T85XF (28. RESIN CHANGE)."),
    A: ("Changes since the SharePoint state (mail): LCMEI-7815 Schlitten stop ribs (approved, tools "
        "modified 2026-10-14, K30 graining open), LCMEI-7386 Blende FS gap (V2 agreed technically, not "
        "released, tool unchanged), Kunststoffachse force feeling (+0.2 mm), new drawings 260316 for FS/BFS/"
        "Mitte, Schliessklappe 2K capacity tool quote. DEMO-molded parts planned to move into KTX Silao. "
        "Latest Audi data is in KVS (Uwe) and Nextcloud 'KTX Mexico/260729_AU436'."),
}

# Mail attachments (scratchpad mailatt/<short id>/...) -> where they go.
# ("rev2", [finished-good customer numbers], customer_index) or ("sep", project, gate, item_no)
MAIL_FILES = {
    "9E215B850000": None,  # handled per file below (BFS / Mitte drawings)
    "9E2148A50000": None,  # FS drawing
    "E0ADE4C00000": None,  # old CSI drawings -> revision 1
    "9E214A410000": ("sep", A, "A/RG7", 14),
    "E0ADE4F10000": ("sep", A, "A/RG7", 1),
    "9E214A400000": ("sep", T, "A/RG7", 14),
    "5AE811D20000": ("sep", T, "A/RG7", 14),
    "9E214A420000": ("sep", T, "B/RG6", 26),
    "E0AE40360000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0ADEAAE0000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0ADE6320000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0AE15190000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0ADEBDF0000": None,  # on the LCMEI change (import_silao_changes.py)
    "9E2153490000": None,  # on the LCMEI change (import_silao_changes.py)
    "9E2154410000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0AD72910000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0AE3FA50000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0AE655F0000": None,  # on the LCMEI change (import_silao_changes.py)
    "E0ADE49C0000": None,  # on the LCMEI change (import_silao_changes.py)
    "9E2152E20000": ("sep", T, "A/RG7", 1),
    "9E2156800000": ("sep", T, "A/RG7", 1),
    "9E2152E00000": ("sep", T, "A/RG7", 1),
    "E0AE3F4A0000": ("sep", T, "A/RG7", 1),
    "9E2149F50000": ("sep", T, "A/RG7", 1),
    "E0ADBEE10000": ("sep", A, "A/RG7", 1),
    "9E2152DE0000": ("sep", T, "K0/RG1", 29),
    "9E2152CF0000": ("sep", T, "A/RG7", 1),
    "E0AD7F320000": ("sep", A, "A/RG7", 1),
}
# Audi drawings: file prefix -> (finished-good customer number prefix, index, revision)
AUDI_DRW = [
    ("8MB_820_901_C__DRW_TZ__005", "8MB.820.901", "005", "2"),
    ("8MB_820_902_C__DRW_TZ__004", "8MB.820.902", "004", "2"),
    ("8MA_820_951_C__DRW_TZ__004", "8MA.820.951", "004", "2"),
    ("8MB_820_901_C__DRW_TZ__004", "8MB.820.901", "004", "1"),
    ("8MB_820_902_C__DRW_TZ__003", "8MB.820.902", "003", "1"),
    ("8MA_820_951_C__DRW_TZ__003", "8MA.820.951", "003", "1"),
]


def split_refs(refs):
    out = []
    for r in refs if isinstance(refs, list) else [refs]:
        if r:
            out += [x.strip() for x in str(r).split("/") if x.strip()]
    return out


def clean(v):
    return None if v in (None, "", "null") else v


def cycle(v):
    if v is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(v))
    return float(m.group(0)) if m else None


def tonnage(v):
    if v is None:
        return None
    m = re.search(r"\d{2,4}", str(v))
    return int(m.group(0)) if m else None


def desc(lines):
    return "\n".join(x for x in lines if x)


class Stage:
    def __init__(self):
        self.parts, self.bom, self.relations = {}, {}, []
        self.part_files, self.sep_files, self.held = [], [], []
        self.linked_paths = set()

    def add_part(self, pn, **kw):
        if pn in self.parts:
            # same number twice: keep the first, note the clash
            if self.parts[pn]["name"] != kw.get("name"):
                self.held.append(f"duplicate number {pn}: '{self.parts[pn]['name']}' kept, "
                                 f"'{kw.get('name')}' not loaded")
            return
        self.parts[pn] = {"pn": pn, **kw}


def build_taos(st, d):
    tools_by_ref = {}
    for t in d["tools"]:
        pn = clean(t.get("mold_no")) or DOOR_TOOLS.get(t.get("tool_id"))
        if not pn:
            st.held.append(f"{T} tool '{t['name']}' ({t.get('tool_id')}): no mold number in the data")
            continue
        if pn in tools_by_ref:  # V-3286 is one family tool for TIB RR LH + RH
            tools_by_ref[pn] = {**tools_by_ref[pn],
                                "produces": split_refs(tools_by_ref[pn]["produces"]) + split_refs(t["produces"])}
            continue
        if pn == "V-3286":
            t = {**t, "name": "TIB Zierrahmen RR LH/RH 2GJ.867.449/450 (family)"}
        tools_by_ref[pn] = t
        st.add_part(
            pn, project=T, name=f"{pn} {t['name']}"[:255], item_category="tool", part_type="purchased",
            supplier=clean(t.get("toolmaker")) and t["toolmaker"][:255],
            toolmaker_id=FZ_SUPPLIER_ID if "FZ" in (t.get("toolmaker") or "") else None,
            cavities=clean(t.get("cavities")), cycle_s=cycle(t.get("cycle_s")),
            machine=clean(t.get("machine")) and str(t["machine"])[:255],
            tonnage_t=tonnage(t.get("tonnage_t")),
            description=desc([
                f"Taos PA mold {pn}, MTNA tool id {t.get('tool_id')}." if not pn.startswith("V-") else
                f"Taos PA door mold {pn} (placeholder in the data: {t.get('tool_id')}).",
                f"Origin: {t.get('origin')}." + (" Toolmaker: " + t["toolmaker"] if t.get("toolmaker") else ""),
                f"Hot runner: {t['hot_runner']}." if t.get("hot_runner") else None,
                f"Shot weight: {t['shot_weight_g']} g." if t.get("shot_weight_g") else None,
                f"Status: {t['status']}" if t.get("status") else None,
                "Source: " + "; ".join(t["source"]) if isinstance(t.get("source"), list) else None]))
    for m in d["molded_parts"]:
        pn = m["silao_pn"]
        if pn.startswith("TBD"):
            st.held.append(f"{T} molded part '{m['name_de']}' ({m['vw_pn']}): no KTX item code "
                           "(wrapping BOM reuses 105300018/019)")
            continue
        bought = pn.startswith("1051") or "Demo" in (m.get("origin") or "") or "Plasess" in (m.get("origin") or "")
        st.add_part(
            pn, project=T, name=f"{m['vw_pn']} {m['name_de']}"[:255],
            customer_part_number=clean(m.get("vw_pn")), item_category="article",
            part_type="purchased" if bought else "internal_mfg",
            material=clean(m.get("material")), colour_code=None,
            description=desc([
                f"Taos PA molded part {pn} ({m.get('name_en')}).",
                f"Color: {m['color']}." if m.get("color") else None,
                f"Weight: {m['weight_g']} g." if m.get("weight_g") else None,
                f"Origin: {m['origin']}." if m.get("origin") else None,
                "Source: " + "; ".join(m["source"]) if isinstance(m.get("source"), list) else None]))
    for p in d["purchased_parts"]:
        st.add_part(p["pn"], project=T, name=p["name"][:255], item_category="article",
                    part_type="purchased", supplier=clean(p.get("supplier")),
                    description=desc([f"Taos PA purchased part, supplier {p.get('supplier')}.",
                                      "Source: " + "; ".join(p["source"]) if isinstance(p.get("source"), list) else None]))
    for f in d["finished_goods"]:
        pn = f["silao_pn"]
        st.add_part(
            pn, project=T, name=f"{f['vw_pn']} {f['name']} {f.get('color') or ''}".strip()[:255],
            customer_part_number=f["vw_pn"], item_category="article", part_type="sub_assembly",
            colour_code=clean(f.get("color_code")), customer_index=clean(f.get("tgs")),
            description=desc([
                f"Taos PA finished good {pn}, version {f.get('version')}, family {f.get('family')}.",
                f"VW {f['vw_pn']}, color {f.get('color')} ({f.get('color_code')}), ambient light {f.get('ambient_light')}.",
                f"Forvia/Faurecia PN {f['faurecia_pn']}." if f.get("faurecia_pn") else None,
                f"TGS {f.get('tgs')} (released {f.get('tgs_released')}), drawing {f.get('drawing_date')}, CPM {f.get('cpm_date')}.",
                f"BOM source: {f.get('bom_source')}" if f.get("bom_source") else "BOM: molded parts only (no BOM sheet; derived)."]))
        lines = []
        for b in f["bom"]:
            lines.append({"child": b.get("pn") or "", "name": b.get("name") or b.get("pn") or "?",
                          "qty": b.get("qty") or 1, "unit": "pcs",
                          "note": "; ".join(x for x in (b.get("type"), b.get("supplier")) if x) or None})
        st.bom[pn] = lines
    for pn, t in tools_by_ref.items():
        for ref in split_refs(t["produces"]):
            st.relations.append({"from": pn, "to": ref, "type": "produces"})
    return tools_by_ref


def build_au436(st, d, numbers, moldlist=None):
    """numbers: optional {"fg": {audi_pn: ktx_pn}, "molded": {tool_part_id: ktx_pn}} from mail.
    moldlist: per-mold fields from Moriroku's AU436 Mold List Rev. 15 (2022-01-25)."""
    fgmap = (numbers or {}).get("fg", {})
    mmap = (numbers or {}).get("molded", {})
    ml = moldlist or {}
    tools_by_ref = {}
    for t in d["tools"]:
        pn = t["mold_no"]
        tools_by_ref[pn] = t
        r = ml.get(pn, {})
        ml_machine = (f"M/C #{r['m/c_no']} {r['machine_size']}T (Mold List 2022)"
                      if r.get("m/c_no") not in (None, "", "N/A") else None)
        st.add_part(
            pn, project=A, name=f"{pn} {t['name']}"[:255], item_category="tool", part_type="purchased",
            supplier=clean(t.get("toolmaker")) and t["toolmaker"][:255],
            cavities=clean(t.get("cavities")), cycle_s=cycle(t.get("cycle_s")),
            machine=(clean(t.get("machine")) and str(t["machine"])[:255]) or ml_machine,
            tonnage_t=tonnage(t.get("tonnage_t")) or tonnage(r.get("machine_size")),
            grain=(r.get("texture(s)") or None) and r["texture(s)"][:80],
            description=desc([
                (f"Mold List Rev. 15 (Moriroku 2022-01-25): {r.get('mfg_location')}, M/C {r.get('m/c_no')} "
                 f"{r.get('machine_size')}T, cav {r.get('no_of_cav')}, steel {r.get('mold_material')}, texture "
                 f"{r.get('texture(s)')}, resin {r.get('resin')}, gate {r.get('gate_design')}.") if r else None,
                f"AU436 mold {pn}, MTNA tool id {t.get('tool_id')}.",
                f"Origin: {t.get('origin')}" + (f", molded at {t['molding_location']}" if t.get("molding_location") else "") + ".",
                f"Toolmaker: {t['toolmaker']}." if t.get("toolmaker") else None,
                f"Hot runner: {t['hot_runner']}." if t.get("hot_runner") not in (None, True) else ("Hot runner: yes." if t.get("hot_runner") else None),
                f"Shot weight: {t['shot_weight_g']} g." if t.get("shot_weight_g") else None,
                f"Status: {t['status']}" if t.get("status") else None]))
    for m in d["molded_parts"]:
        ref = m["audi_pn"]
        pn = m.get("silao_pn") or mmap.get(ref)
        if not pn:
            pn = ref  # MTNA part id (8MB.820.901-AU436-0001) until Silao item codes are known
        tref = m.get("tool_ref")
        r = ml.get(tref[0] if isinstance(tref, list) and tref else tref or "", {})
        tex = r.get("texture(s)")
        st.add_part(
            pn, project=A, name=f"{ref} {m['name_de']}"[:255], customer_part_number=ref,
            item_category="article", part_type="internal_mfg",
            material=clean(m.get("material")) or (r.get("resin") or None),
            grain=tex[:80] if tex and tex != "N/A" else None,
            description=desc([
                f"AU436 molded part ({m.get('name_en')}).",
                f"Finish: {m['finish']}." if m.get("finish") else None,
                f"Weight: {m['weight_g']} g ({m.get('weight_source')})." if m.get("weight_g") else None,
                f"Aliases: {', '.join(m['aliases'])}." if m.get("aliases") else None,
                m.get("note")]))
        m["_pn"] = pn
    by_ref = {m["audi_pn"]: m["_pn"] for m in d["molded_parts"]}
    for f in d["finished_goods"]:
        apn = f.get("audi_pn")
        pn = f.get("silao_pn") or (apn and fgmap.get(apn)) or apn
        if not pn:
            st.held.append(f"{A} finished good '{f['name']}': no Audi or KTX part number (TBC in source)")
            continue
        v = f.get("variant") or {}
        st.add_part(
            pn, project=A, name=f"{apn} {f['name']}"[:255], customer_part_number=apn,
            item_category="article", part_type="sub_assembly", colour_code=clean(f.get("color")),
            customer_index=clean(f.get("audi_index")),
            description=desc([
                f"AU436 finished good {f['name']}: trim {v.get('trim')}, side {v.get('side')}, {v.get('finish')}.",
                f"Audi {apn} index {f.get('audi_index')}; CAD {f.get('cad_revision')}.",
                "BOM inferred from tool cavities and the 2021 parts overview (no assembly BOM in the data)."]))
        st.bom[pn] = [{"child": by_ref.get(b["pn"], b.get("pn") or ""), "name": b.get("name") or b.get("pn") or "?",
                       "qty": b.get("qty") or 1, "unit": "pcs", "note": b.get("type")} for b in f["bom"]]
    for t in d["tools"]:
        for ref in split_refs(t["produces"]):
            st.relations.append({"from": t["mold_no"], "to": by_ref.get(ref, ref), "type": "produces"})
    return tools_by_ref, by_ref


def link_documents(st, project, docs, files, resolve):
    """Expand doc entries (file or folder) to files and file them on the part."""
    for d in docs:
        targets = d["links_to"] if isinstance(d["links_to"], list) else [d["links_to"]]
        pns = [resolve(x) for x in targets if x]
        pns = [p for p in pns if p in st.parts]
        root = d["path"].rstrip("/")
        hits = [p for p in files if p == root or p.startswith(root + "/")]
        if not pns or not hits:
            continue
        ftype, kind = FILE_TYPE.get(d["kind"], ("document", None))
        for p in hits:
            if os.path.splitext(p)[1].lower() in SKIP_EXT or os.path.basename(p).startswith(SKIP_NAME_PREFIX):
                continue
            st.linked_paths.add(p)
            for pn in pns[:1]:  # one home per file: the first linked tool/part
                st.part_files.append({"pn": pn, "rel": p, "filename": os.path.basename(p),
                                      "file_type": ftype, "kind": kind,
                                      "note": f"Silao SharePoint: {os.path.dirname(p)}"})


def sep_name(rel, prefix_len):
    """Filename with the subfolders below the mapped folder, so flat SEP slots keep context."""
    parts = rel.split("/")
    sub = [x for x in parts[prefix_len:-1]]
    name = parts[-1]
    if sub:
        name = " - ".join(sub[-2:]) + " - " + name
    return name[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True)
    ap.add_argument("--mirror", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--numbers", help="optional JSON with AU436 KTX numbers from mail")
    ap.add_argument("--files", action="store_true")
    a = ap.parse_args()

    files = {}
    for line in open(os.path.join(a.extract, "filelist.tsv"), encoding="utf-8"):
        p, size, _ = line.rstrip("\n").split("\t")
        files[p] = int(size or 0)
    taos = json.load(open(os.path.join(a.extract, "taos.json")))
    au = json.load(open(os.path.join(a.extract, "au436.json")))
    numbers = json.load(open(a.numbers)) if a.numbers else None

    moldlist_path = os.path.join(a.extract, "au436_moldlist.json")
    moldlist = json.load(open(moldlist_path)) if os.path.exists(moldlist_path) else None

    st = Stage()
    build_taos(st, taos)
    _, au_ref = build_au436(st, au, numbers, moldlist)
    link_documents(st, T, taos["documents"], files, lambda x: x)
    link_documents(st, A, au["documents"], files, lambda x: au_ref.get(x, x))

    # changes from mail -> part descriptions ("CHANGE ..." lines) and project descriptions
    for proj, keys, text in CHANGES:
        for p in st.parts.values():
            if p["project"] != proj:
                continue
            cpn = p.get("customer_part_number") or ""
            if p["pn"] in keys or any(cpn.startswith(k) for k in keys if "." in k):
                p["description"] = (p.get("description") or "") + "\nCHANGE (mail): " + text
    for pr in PROJECTS:
        pr["description"] += "\n" + CHANGE_GENERAL[pr["code"]]

    # mail attachments
    extra_revisions = []
    mail_dir = os.path.join(a.extract, "..", "mailatt")
    for short in sorted(os.listdir(mail_dir)) if os.path.isdir(mail_dir) else []:
        mdir = os.path.join(mail_dir, short)
        if not os.path.isdir(mdir):
            continue
        for fn in sorted(os.listdir(mdir)):
            if re.match(r"(?i)^(outlook-|image\d*|img_)", fn) or fn.endswith(":Zone.Identifier"):
                continue
            rel = f"_mail/{short}/{fn}"
            files[rel] = os.path.getsize(os.path.join(mdir, fn))
            drw = next((x for x in AUDI_DRW if fn.startswith(x[0])), None)
            if drw:
                prefix, cpn, index, revname = drw
                fgs = [p["pn"] for p in st.parts.values() if p["project"] == A and
                       p["part_type"] == "sub_assembly" and (p.get("customer_part_number") or "").startswith(cpn)]
                if revname == "1":
                    for pn in fgs:
                        st.part_files.append({"pn": pn, "rel": rel, "filename": fn, "file_type": "drawing",
                                              "kind": "DRW", "note": f"Audi drawing index {index} (mail {short})"})
                else:
                    for pn in fgs:
                        extra_revisions.append({
                            "pn": pn, "revision_name": revname, "customer_index": index,
                            "summary": (f"Audi drawing DRW_TZ {index} 2026-03-16 (KTX, in KVS; LCMEI-7815 "
                                        "Schlitten ribs), received by mail from Uwe Schulz."),
                            "files": [{"rel": rel, "filename": fn, "file_type": "drawing", "kind": "DRW",
                                       "note": f"mail {short}"}]})
                continue
            slot = MAIL_FILES.get(short)
            if slot and slot[0] == "sep":
                st.sep_files.append({"project": slot[1], "gate": slot[2], "item_no": slot[3],
                                     "rel": rel, "filename": f"mail {short[:4]} - {fn}"[:200]})

    # project documents and unlinked tool-area leftovers -> SEP items
    from silao_sep_map import SEP_MAP
    for p in files:
        if p in st.linked_paths:
            continue
        if os.path.splitext(p)[1].lower() in SKIP_EXT or os.path.basename(p).startswith(SKIP_NAME_PREFIX):
            continue
        slot = sep_slot(p)
        prefix_len = 0
        if slot == "part":
            proj = A if "/AU436" in p else T
            slot = (proj, "E/RG3", 20) if "Graining" in p else (proj, "A/RG7", 14)
            prefix_len = 4
        elif slot is None:
            continue
        else:
            prefix = next(k for k, v in SEP_MAP if p == k or p.startswith(k + "/") or
                          (p.startswith(k) and "/" not in p[len(k):]))
            prefix_len = prefix.count("/") + 1
        st.sep_files.append({"project": slot[0], "gate": slot[1], "item_no": slot[2],
                             "rel": p, "filename": sep_name(p, prefix_len)})

    # drop relations/BOM children that point at held parts
    st.relations = [r for r in st.relations if r["from"] in st.parts and r["to"] in st.parts]
    for lines in st.bom.values():
        for ln in lines:
            if ln["child"] not in st.parts:
                ln["child"] = ""

    out = {
        "generated": "2026-10-30",
        "revision_summary": ("Series baseline from the Silao SharePoint data transfer (MTNA, April/May "
                             "2025; Taos part number list 2026-10-16)."),
        "projects": PROJECTS,
        "parts": list(st.parts.values()),
        "bom": st.bom, "relations": st.relations,
        "part_files": st.part_files, "sep_files": st.sep_files,
        "extra_revisions": extra_revisions, "held": st.held,
    }
    os.makedirs(a.stage, exist_ok=True)

    def source(rel):
        if rel.startswith("_mail/"):
            return os.path.join(mail_dir, rel[len("_mail/"):])
        return os.path.join(a.mirror, rel)

    all_files = st.part_files + st.sep_files + [f for r in extra_revisions for f in r["files"]]
    missing = [f["rel"] for f in all_files if not os.path.isfile(source(f["rel"]))]
    if a.files:
        for f in all_files:
            src = source(f["rel"])
            dst = os.path.join(a.stage, "files", f["rel"])
            if not os.path.isfile(src) or os.path.exists(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.link(src, dst)
    json.dump(out, open(os.path.join(a.stage, "silao.json"), "w"), ensure_ascii=False, indent=1)

    c = Counter((p["project"], p["item_category"], p["part_type"]) for p in out["parts"])
    for k, v in sorted(c.items()):
        print(f"  {k[0]:8} {k[1]:8} {k[2]:12} {v}")
    sz = lambda lst: sum(files.get(f["rel"], 0) for f in lst) / 1e9
    print(f"parts={len(out['parts'])} bom_parents={len(st.bom)} bom_lines={sum(map(len, st.bom.values()))} "
          f"relations={len(st.relations)}")
    print(f"part_files={len(st.part_files)} ({sz(st.part_files):.1f} GB)  "
          f"sep_files={len(st.sep_files)} ({sz(st.sep_files):.1f} GB)  "
          f"extra_revisions={len(extra_revisions)}  not yet in mirror={len(missing)}")
    for h in st.held:
        print("HELD: " + h)


if __name__ == "__main__":
    main()
