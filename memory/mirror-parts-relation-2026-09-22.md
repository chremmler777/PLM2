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

**Built 2026-09-22 (merged to main, d2c6b387):** `mirror_of` is a valid
relation type (one mirror per article, no chains in either direction, articles
of one project only); the project page shows a red `⇄ Mirror of …` chip, the
tree marks mirrors, and a mirror with no own 3D/drawing shows the source
part's document under the red banner "Mirrored part. Showing … Geometry is
the mirror image, RPS and references differ." Relations form offers
"mirror of" on articles. Deferred: partial unique index for one-mirror-per-part
(application-level only today), a11y on the revision strip tabs.

See [[prod-data-is-truth]] for how data changes reach prod.
