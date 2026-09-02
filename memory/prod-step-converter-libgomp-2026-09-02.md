---
name: prod-step-converter-libgomp-2026-09-02
description: Prod PLM2 STEP-to-glb conversion silently produced placeholder cubes because libgomp.so.1 symlink was missing in the conda image; fixed in Dockerfile ffbdf633, verify OCC import after every rebuild
metadata:
  type: project
---

**Symptom (2026-09-02):** all server-converted STEP files rendered as cubes. `convert_step_to_gltf`
returns True even when it writes the 924-byte placeholder, so the attach script reported
"converted". Prebuilt glbs (from RFQ2) were fine, which hid the problem for 1994B.

**Cause:** prod image had `/opt/conda/lib/libgomp.so.1.0.0` but no `libgomp.so.1` symlink;
`OCC.Core.STEPControl` import failed in the conversion subprocess. Local image happened to have it.

**Fix:** `backend/Dockerfile` installs conda `libgomp` and guards the symlink (ffbdf633). Live
container patched with `docker exec -u root ... ln -sf`. `scripts/reconvert_brose_viewers.py`
regenerates viewers whose glb is under 2 KB (idempotent).

**How to apply:** after any prod rebuild run
`docker exec compose-plm2-backend-1 python -c "from OCC.Core.STEPControl import STEPControl_Reader"`.
Treat a viewer glb under 2 KB as a failed conversion, never as a tiny part. Consider making
`convert_step_to_gltf` return False on placeholder fallback (open improvement).
See [[brose-award-import-2026-09-02]], [[live-db-is-postgres-2026-08-06]].
