---
name: version-nav-2026-10-19
description: PLM2 Documents tab version navigator (explorer tree + file completeness) deployed 2026-10-19; follow-up ideas
metadata:
  type: project
---
Deployed to prod 2026-10-19 (main 475fbdfb, alembic still 116): the Documents tab has a collapsible "Versions" side panel instead of the revision tabs. Customer versions as folders, iterations nested, files as leaves. Each version shows a state chip, the first line of its summary, the date, and completeness chips: 3D native / STEP / 2D drawing as here ✓, stale ↩ (an older version's file still applies, e.g. "drawing not updated") or missing ✗. On iterations a gap is "inherited", never flagged. New read-only GET /parts/{id}/revision-files feeds it.

Why: Christoph found the old tabs confusing and wanted an explorer-like tree like other PLMs (Teamcenter/Windchill pattern), plus a view of which file types are missing or outdated ("drawing not updated, still old ref").

How to apply: the offered follow-up (not built) is the same completeness check as a worksheet column across all parts ("3 parts with outdated drawing"). Rules live in frontend/src/components/parts/versionTree.ts. Related: [[revision-update-simplify-2026-10-10]].
