"""Read-only WinCarat (Oracle KWA) extraction to JSON — SP-B step 1.

Standalone: depends only on `oracledb` + WINCARAT_* env vars, so it runs
inside the TWOS backend container (`claude-twos-backend-1`), which has
both. It does NOT import PLM models. Output is one JSON document consumed
by `import_wincarat.py` (which runs in the PLM container).

Scope: all active projects (PROJEKTSTATUS in SERIES, PRE-SERI), skipping
zero-article projects. Full part set (every TEILEART), tool enrichment
from WERKZ, supplier names from LIEFERANT, and the assembly BOM tree with
quantities from STULIKO/STULIPO.

This WinCarat is a single-mandant KTX America (USA) instance — one plant
(WERKSTAMM 'DEFAULT'); there is no Silao/Mexico data to exclude.

Usage (inside the TWOS container):
    python wincarat_extract.py --out /tmp/wincarat.json
    python wincarat_extract.py --plants-only     # sanity: list plants
"""
import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal

import oracledb

ACTIVE_STATUS = ("SERIES", "PRE-SERI")


def connect():
    return oracledb.connect(
        user=os.environ["WINCARAT_USER"],
        password=os.environ["WINCARAT_PASSWORD"],
        params=oracledb.ConnectParams(
            host=os.environ["WINCARAT_HOST"],
            port=int(os.environ["WINCARAT_PORT"]),
            sid=os.environ["WINCARAT_SID"],
        ),
        tcp_connect_timeout=15,
    )


def _clean(v):
    if v is None:
        return None
    if hasattr(v, "read"):          # CLOB/BLOB
        v = v.read()
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip() or None
    return v


def query(cur, sql, **kw):
    cur.execute(sql, **kw)
    cols = [d[0] for d in cur.description]
    return [{c: _clean(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def plants_only(cur):
    for r in query(cur, "select WERKNREIGEN, NAME1, LANDNAME, ORT from KWA.WERKSTAMM"):
        print(f"  plant {r['WERKNREIGEN']!r}: {r['NAME1']} ({r['LANDNAME']}, {r['ORT']})")


def extract(cur, project_filter=None) -> dict:
    # 1) active, non-empty projects with customer name.
    #    Default scope is active status (SERIES/PRE-SERI); pass an explicit
    #    project_filter (list of PROJEKTNR) to pull specific projects
    #    regardless of status — e.g. the status-less VW426 Atlas (1864).
    if project_filter:
        binds = {f"pf{j}": v for j, v in enumerate(project_filter)}
        placeholders = ",".join(f":pf{j}" for j in range(len(project_filter)))
        where = f"p.PROJEKTNR in ({placeholders})"
    else:
        binds = {}
        where = "p.PROJEKTSTATUS in ('SERIES','PRE-SERI')"
    projects = query(cur, f"""
        select p.PROJEKTNR, p.PROJEKTNREXT, p.BESCHREIBUNG, p.KDNR, p.PROJEKTSTATUS,
               k.MATCHCODE as CUSTOMER,
               (select count(*) from KWA.ARTIKEL a where a.PROJEKTNR = p.PROJEKTNR) as NART
          from KWA.PROJEKTSTAMM p
          left join KWA.KUNDE k on k.KDNR = p.KDNR
         where {where}
    """, **binds)
    projects = [p for p in projects if (p.get("NART") or 0) > 0]
    projnrs = [p["PROJEKTNR"] for p in projects]

    # 2) suppliers (small) -> name by number
    suppliers = {r["LIEFERANTNR"]: (r["MATCHCODE"] or r["NAME1"])
                 for r in query(cur, "select LIEFERANTNR, MATCHCODE, NAME1 from KWA.LIEFERANT")}

    # 3) tools (WERKZ) by ARTNR
    tools = {r["ARTNR"]: r for r in query(cur, """
        select ARTNR, KAVITAET, ZUSTANDSTEXT, WARTUNGSINTERVALL, GESAMTPROD, LIEFERANTNR
          from KWA.WERKZ
    """)}

    # 3b) GLOBAL article name/type map (all ARTIKEL) — used to resolve BOM
    #     children that live outside the active projects (raw material 40-*,
    #     clips 50-*, hardware 65-*), whose names sit on their own article row.
    #     EIGENKZ (own-manufacture flag) is the make/buy signal: 1 = in-house
    #     (internal_mfg / sub_assembly), 0 = bought (purchased).
    art_meta = {r["ARTNR"]: {"matchcode": r.get("MATCHCODE") or r.get("TEXT"),
                             "teileart": r.get("TEILEART"),
                             "eigenkz": r.get("EIGENKZ")}
                for r in query(cur, "select ARTNR, MATCHCODE, TEXT, TEILEART, EIGENKZ from KWA.ARTIKEL")}

    # 4) all articles for the active projects (one bulk pull)
    #    Oracle IN-list cap is 1000; chunk the project numbers.
    articles = []
    for i in range(0, len(projnrs), 500):
        chunk = projnrs[i:i + 500]
        binds = {f"p{j}": v for j, v in enumerate(chunk)}
        placeholders = ",".join(f":p{j}" for j in range(len(chunk)))
        articles += query(cur, f"""
            select ARTNR, MATCHCODE, TEXT, KDARTNR, KDNR, PROJEKTNR, TEILEART,
                   STUELINR, ZEICHNR, GEWICHTNETTO, ZUSTAND, LETZTERLIEFERANT, EIGENKZ
              from KWA.ARTIKEL where PROJEKTNR in ({placeholders})
        """, **binds)

    # 5) BOM lines from KWA.MATERIAL (the live recipe/component table here;
    #    STULIKO/STULIPO are unused in this instance). MATERIAL.STLAPLNR is the
    #    parent article, ARTNR the child, MENGE the quantity. Pull all lines
    #    whose parent is one of our active-project articles.
    parent_artnrs = sorted({a["ARTNR"] for a in articles})
    bom_by_parent: dict = {}
    for i in range(0, len(parent_artnrs), 500):
        chunk = parent_artnrs[i:i + 500]
        binds = {f"s{j}": v for j, v in enumerate(chunk)}
        placeholders = ",".join(f":s{j}" for j in range(len(chunk)))
        for line in query(cur, f"""
            select STLAPLNR, STLPOS, LFDNR, ARTNR as CHILD_ARTNR, MENGE, MENGEPROTEILE,
                   MENGEEINH, BENENNUNG, VERSCHLEISSTEIL, ERSATZTEIL
              from KWA.MATERIAL where STLAPLNR in ({placeholders})
              order by STLAPLNR, STLPOS, LFDNR
        """, **binds):
            bom_by_parent.setdefault(line["STLAPLNR"], []).append(line)

    # assemble per-project structure
    arts_by_proj: dict = {}
    for a in articles:
        artnr = a["ARTNR"]
        rec = {
            "artnr": artnr,
            "matchcode": a.get("MATCHCODE") or a.get("TEXT"),
            "kdartnr": a.get("KDARTNR"),
            "teileart": a.get("TEILEART"),
            "stuelinr": a.get("STUELINR"),
            "zeichnr": a.get("ZEICHNR"),
            "gewichtnetto": a.get("GEWICHTNETTO"),
            "zustand": a.get("ZUSTAND"),
            "eigenkz": a.get("EIGENKZ"),
        }
        if a.get("TEILEART") == "W" and artnr in tools:
            t = tools[artnr]
            rec["tool"] = {
                "kavitaet": t.get("KAVITAET"),
                "zustandstext": t.get("ZUSTANDSTEXT"),
                "wartungsintervall": t.get("WARTUNGSINTERVALL"),
                "gesamtprod": t.get("GESAMTPROD"),
                "lieferant": suppliers.get(t.get("LIEFERANTNR")),
            }
        sup = suppliers.get(a.get("LETZTERLIEFERANT"))
        rec["supplier"] = sup
        rec["bom"] = [
            {
                "posnr": b.get("STLPOS") or b.get("LFDNR"),
                "child_artnr": b.get("CHILD_ARTNR"),
                "menge": b.get("MENGE") if b.get("MENGE") is not None else b.get("MENGEPROTEILE"),
                "einheit": b.get("MENGEEINH"),
                "name": (art_meta.get(b.get("CHILD_ARTNR"), {}).get("matchcode")
                         or b.get("BENENNUNG")),
                "child_teileart": art_meta.get(b.get("CHILD_ARTNR"), {}).get("teileart"),
                "child_eigenkz": art_meta.get(b.get("CHILD_ARTNR"), {}).get("eigenkz"),
                "verschleissteil": bool(b.get("VERSCHLEISSTEIL")),
                "ersatzteil": bool(b.get("ERSATZTEIL")),
            }
            for b in bom_by_parent.get(artnr, [])
        ]
        arts_by_proj.setdefault(a["PROJEKTNR"], []).append(rec)

    out_projects = []
    for p in projects:
        out_projects.append({
            "projektnr": p["PROJEKTNR"],
            "name": p.get("PROJEKTNREXT") or p.get("BESCHREIBUNG") or p["PROJEKTNR"],
            "beschreibung": p.get("BESCHREIBUNG"),
            "kdnr": p.get("KDNR"),
            "customer": p.get("CUSTOMER"),
            "status": p.get("PROJEKTSTATUS"),
            "parts": arts_by_proj.get(p["PROJEKTNR"], []),
        })
    return {"projects": out_projects}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--plants-only", action="store_true")
    ap.add_argument("--projects", help="comma-separated PROJEKTNR to extract "
                    "regardless of status (default: all SERIES/PRE-SERI)")
    args = ap.parse_args()

    conn = connect()
    try:
        cur = conn.cursor()
        if args.plants_only:
            plants_only(cur)
            return
        pf = [x.strip() for x in args.projects.split(",")] if args.projects else None
        data = extract(cur, project_filter=pf)
    finally:
        conn.close()

    nproj = len(data["projects"])
    nparts = sum(len(p["parts"]) for p in data["projects"])
    nbom = sum(len(a["bom"]) for p in data["projects"] for a in p["parts"])
    print(f"Extracted {nproj} projects, {nparts} parts, {nbom} BOM lines.")
    if not args.out:
        sys.exit("Pass --out <path> to write JSON.")
    with open(args.out, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
