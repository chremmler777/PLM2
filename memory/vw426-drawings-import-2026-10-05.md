---
name: vw426-drawings-import-2026-10-05
description: VW426 Atlas (1864) 2D drawing releases from SharePoint KTW_OPVW_426 imported to prod as customer revision history A/B/C(/D); six 7.10.26 indexes assumed
metadata:
  type: project
---

2026-10-05 21:03 on prod (backup plm2-before-vw426-drawings-20261005-210303.sql.gz), script
backend/scripts/import_vw426_drawings.py: 27 files (25 .CATDrawing + 2 PDF prints) from
ktxgroup.sharepoint.com/sites/KTW_OPVW_426 Shared Documents/08_Develeopment_public/03_Drawing/02_Release
(1 -- 9.16.24 Nomination, 2 -- 6.10.25, 3 -- 7.10.26). Index A set on each part's existing official revision 1,
B/C/D as new official majors 2..4 (no triage, newest active), files kind DRW, note "VW release <date>".

User decisions: full history; Out314-/Out316-<letter> = index; the six 7.10.26 files without a letter
(3CR.807.425, .425.B, .531.A, .532.A, 3CS.807.425, 3CS.807.643) got "next after last known" -> their summary says
"index assumed, check the title block". RH parts 3CR.919.492.A/.C and 3CS.807.644 have no drawing (left as they were).
Not imported: "OP VW 426 Drawing issues 7.29.26" pdf/pptx and the empty "OP 2D Drawing LOP.xlsx".
Download path: playwright-cli -s=sharepoint (persistent login) -> REST list -> curl with the session cookies.
.CATDrawing support in code: f58ea193 (needs a deploy; the import patched the map at runtime).
