---
name: br167-project-91-import-2026-10-02
description: BR167 Daimler / MBUSI (P: folder 1316) loaded as PLM project 91 from the Windows-built PLM package; live on prod; data gaps and ideas to add
metadata:
  type: project
---

**Project code 91** (user 2026-10-02: "use 91", P: folder is `1316_BR167_Daimler`; most other P: folder numbers match PLM codes, this one is to be fixed later). Not related to 1642 "MERCEDES US BR 167" (WinCarat: aero covers 3260 = 1681 facelift, underbody cover 3289) or 1888 T167 (Yanfeng China).

**Source:** package `C:\Users\christoph.demmler\Downloads\BR167_PLM` (index `00_BR167_PLM_INDEX.xlsx`, prompt `00_PLM_PROMPT.md`), built by a Windows session from a read-only P: scan. Scripts: `backend/scripts/br167_extract.py` (WSL host, openpyxl -> `br167_stage/br167.json` + drawings, git-ignored) and `import_br167.py` (backend container, idempotent).

**Local 2026-10-02:** project id 36; 82 new parts (articles + 28 tools incl. capacity tools 0827-2..0830-2, 0841-2), revision `1` official/import with customer_index = Part-BOM E/Q level, 244 BOM lines (multi-level rebuilt: assembly -> painted 10-xxxx-243-n -> molded 10-xxxx-001-n -> material/paint/boxes), 37 relations (tool produces, 08xx-2 produce the same articles; 91-0013 welding device assembles both consoles), 26 drawings (kind DRW). 20 articles already in other projects (13 in 1888, 5 in 94, 65-0035 in 1642, 65-0021 in 1456) were left there and only linked; their empty BOMs were filled. WM94SW welding machine skipped (MachineDB). **PROD 2026-10-02 21:17:** same result as local (project id 36, 82 parts, 244 BOM lines, 37 relations, 26 drawings; rerun = 0). Ran via docker cp of the script + stage into `compose-plm2-backend-1` with `CREATED_BY=14 BR167_STAGE=/app/uploads/_stage_br167` (stage removed after with `docker exec -u 0`). Backup `db-backups/plm2-before-br167-20261002-211706.sql.gz`.

**Source data issues found:** Part-BOM lists tool 0822 for lamellas 6-9 (real tools 0823/0824 exist on P:, created with 0822 data, flagged CHECK); LH rows of 0851/0841 had no children (copied from RH); BR167 MBUSI lamella/console articles sit in 1888 T167 (should probably move to 91); drawing file index vs Part-BOM E-level not reconciled (Smaragd is master, flag only).

**Ideas to add to PLM (learned on the way):** external link store (P:/UNC folder refs per part/project with category, file count; now only in part description); project-level documents area (PPAP, FMEA/CP, WI, TTS, packaging releases: ~1450 package docs have no home); drawing-vs-Smaragd index check; supplier records for toolmakers (Siebenwurst, Rathgeber, Buck, Misselbeck have none, so toolmaker_id empty); article move between projects; customer PO/TTS per tool.

**Access notes:** WSL mirrored networking misses the FortiClient adapter if the VPN comes up after WSL starts; prod SSH then works via `ProxyCommand ~/.ssh/ktx-relay.sh %h %p` (PowerShell TCP relay) with the agent from `~/.ssh/agent.env`. P: (172.17.33.2:445) was unreachable even from Windows on 2026-10-02, and its range collides with docker0 172.17.0.0/16 in WSL.

**NEXT when P: is reachable again (user 2026-10-02: resume BR167 then):** verify tools 0823/0824 data on P:, check drawing index vs E-level (Smaragd master), decide 1888 -> 91 move of the BR167 MBUSI lamellas/consoles, match the other P: project folders to PDB/PLM codes, then build the ideas list (link store, project documents, toolmaker suppliers).
