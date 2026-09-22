---
name: mirror-parts-relation
description: Mirrored parts (LH/RH, 40/60) are never physical copies; the mirror carries a mirror_of relation to the data-holding part. UI follow-up open: show it in the BOM and a viewer warning
metadata:
  type: project
---

Ruling by the user, 2026-09-22: "mirrors can be just stated as mirrors, no
need to mirror them physically, that needs to be clear in the BOM, viewer
can just show warning that part is mirrored."

**Data:** `part_relations.relation_type = 'mirror_of'` from the mirror to
the part that holds the customer files (the one whose drawing Brose
delivered). Written by `backend/scripts/reset_1994_e1.py` for 1994:
206.882.252 → 206.882.251, 206.885.968 → 206.885.967. No files are copied
to the mirror; only files delivered under its own number are attached.

**Open UI work (not built yet, 2026-09-22):**
- `mirror_of` is not in the API's `VALID_RELATION_TYPES`
  (`backend/app/api/v1/items/part_relations.py`), so it cannot be created
  from the UI. Add it, one mirror per part (see the 2026-09-08 master BOM /
  tooling board spec, which designed exactly this relation).
- BOM tree and part page: show "mirror of <part>" on the mirror.
- 3D viewer on a mirror with no own files: warning "mirrored part, data on
  <part>", offer to open the source's viewer.

See [[prod-data-is-truth]] for how data changes reach prod.
