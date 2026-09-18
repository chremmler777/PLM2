---
name: customer-package-receive-2026-09-18
description: Customer package receive, chosen E number, customer index everywhere; merged to main 2026-09-18; rulings and follow-ups
metadata:
  type: project
---

Merged to `main` on 2026-09-18 (fast-forward from `feature/customer-data-index`, 33 commits, backend 890 / frontend 610 tests green).

**What it is.** A customer delivery is the assembly file plus one file per part, and not every part changes. "+ Customer package" on an assembly (part page header, project page revision header) previews every file: match to a part by customer part number or our number in the filename, index read from the filename (`3CR807425B_…` → `B`) or the package index, action `new_major` / `unchanged` / `unmatched`. Same index as the active revision = unchanged = nothing stored, E stays. Only changed parts get a new major; the assembly goes last so its BOM copy follows the children's active revisions. Any error row blocks the whole package (409 with rows, table stays editable). Sameness is by customer index only, never by file hash (Christoph's explicit choice). Customer data creates majors freely; the E number can be chosen (must be above every existing one of that kind, gaps allowed). Every revision name renders as `E2 · B`. Spec: `docs/superpowers/specs/2026-09-18-customer-package-receive-design.md`; guide: `docs/CUSTOMER_DATA_INDEX.md`.

**Why:** Christoph uploads whole assemblies on prod and does not want the clamp stored again every time the assembly changes, nor a change request for E-level updates, and the customer's numbering can be ahead of ours.

**How to apply:** New customer data goes through the package flow or "+ Customer data"; do not add a hash-based sameness check; keep the customer part number on parts filled (now editable on the add-part form and inline on the part page) because matching depends on it. No new migrations in this work.

**Rulings made during the build** (revisit if wrong): unmatched files are skipped whatever their type; confirm refuses parts outside the assembly's project; `customer_part_number` persistence on create/update was added although the plan did not list it; package button lives in the project page revision header.

**Follow-ups left open:** dialog lacks aria labels / role=dialog (matches existing dialogs); `CustomerPackageService` reaches into `BomTreeService._display_revision` and `RevisionService._majors`; only the first occurrence of a customer number in a filename is checked for an index; `received_at` unused in preview; env quirk: run backend tests with `uv run --no-sync pytest` because an untracked empty `backend/uv.lock` makes plain `uv run` wipe the venv. Related: [[plm-master-datasource]], [[phase5-status]].
