# Project Worksheet, Field Notes and Linked Material Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-project worksheet (one row per article, with the producing tool's values) where every field can be commented and flagged, plus a real material field on the article linked to MaterialDB, an xlsx export and a one-time import of the 1994 Excel open points.

**Architecture:** Backend: two new tables (`field_notes`, `field_note_comments`, migration 082) with a small service and API; six material columns on `parts` (migration 083) plus a server-side MaterialDB client that caches the MaterialDB service list and searches it; one read endpoint that assembles all worksheet rows in a fixed number of queries and one export endpoint that writes typed xlsx from the rows the browser shows. Frontend: api modules and query hooks, a reusable `FieldNoteMarker` with a popover, a `MaterialField` on the article page, markers plus a `?focus=<field_key>` highlight on the article, tool and paint sections, and a `WorksheetView` driven by a column registry (`worksheetColumns.ts`) with pure table helpers (`worksheetTable.ts`).

**Tech Stack:** FastAPI 0.109, SQLAlchemy async, Alembic, pydantic 2.5, httpx 0.26 (`httpx.MockTransport` in tests), openpyxl (already in `backend/requirements.txt` as `openpyxl>=3.1`, no new dependency); React 18, TanStack Query 5, react-router 6, Tailwind, vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-24-project-worksheet-design.md`

**Worktree:** `/home/nitrolinux/claude/plm2-integ` (branch `feature/project-worksheet`). A Vite dev server runs on port 5181 from `frontend/vite.integ.config.ts`: never stop it, never stage `vite.integ.config.ts`. The integ backend is the container `plm2-integ-backend` (port 8010, mounts `backend/` at `/app`, database `plm_integ` on `claude-plm2-db-1`).

## Global Constraints

- No em dashes in code comments, UI copy or commit messages (use a comma, colon or "to").
- `.tsx` files export only components (plus types). Hooks and helpers live in `.ts` files.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Values are never edited in the worksheet; they are changed where they live (article, tool, paint). The worksheet only reads, comments and flags.
- Material applies to articles only: 400 on any other item category.
- `material_source`: null | `materialdb` | `new`. A new material shows the amber badge text `NEW, not in MaterialDB`.
- MaterialDB is read only for PLM. The browser never sees `MATERIALDB_SERVICE_TOKEN`. Settings `MATERIALDB_BASE_URL` and `MATERIALDB_SERVICE_TOKEN` are empty by default; search returns 503 with a clear message when unset or unreachable; existing links keep their cached label.
- Field notes: unique (`part_id`, `field_key`); comments append only; flag is null | `open` | `confirmed` | `rejected`; every comment and flag change writes a changelog entry on the part (`field_comment_added`, `field_flag_set`).
- Flag colours: open = yellow, confirmed = green, rejected = red; in xlsx exactly `FFFFFF00`, `FFC6EFCE`, `FFF8CBAD` (the colours of the engineering Excel).
- Show/hide columns is remembered per browser through `frontend/src/lib/safeStorage.ts`.
- Migrations are guarded (inspect before create/drop), like `backend/alembic/versions/081_dfm_audit.py`. 082 revises 081, 083 revises 082.
- Tests: backend `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest <file> -n 0 -q`; frontend `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run <file>`.
- Do not restart `plm2-integ-backend` before Task 17: its start command runs `alembic upgrade head` on the live `plm_integ`, which Task 17 Step 5 wants to migrate from 081 on a copy first. Migration checks during the lanes use scratch SQLite files or throwaway Postgres copies.

## Review Focus

1. A text cell whose value starts with `=` (a pasted formula or a note like `=2 cavities?`) must be written to the xlsx as literal text, never as a formula. Pinned in Task 7 (`test_export_keeps_formula_like_text_as_text`).
2. MaterialDB answering garbage, a non-200 or timing out during a pick or refresh must give a 503 with a readable message and leave the part's saved material untouched. Pinned in Task 5 (`test_pick_when_unreachable_is_503_and_part_unchanged`, `test_refresh_unreachable_keeps_label`) and Task 4 (`test_search_non_200_is_503`).
3. Two articles made by one tool (1+1 handles, latch covers 40/60): a flag on `tool.cavities` set from either row must show on both rows and on the tool page, because it lives on the tool. Pinned in Task 12 (`tool columns read and edit the tool, shared by rows of the same tool`).
4. A malformed field key in the URL (upper case, no dot, a tool key on an article) must be a 400 with a message, not a 500 or a silently stored note. Pinned in Task 2 (`test_bad_field_keys_are_400`).
5. Stored column visibility that is missing, corrupt JSON, or unreadable (private window) must fall back to the default columns without crashing the worksheet. Pinned in Task 13 (`hidden columns fall back to defaults on bad storage`).

---

## API contract (both lanes build against this)

All paths below are under `/api/v1` on the backend; the frontend axios client already prefixes `/plm2/api`, so frontend code writes `/v1/...`. Org scoping: a part or project outside the caller's organization is 404 (same helpers as `backend/app/api/v1/items/part_paint.py`).

### Field notes

`FieldNoteComment`:
```json
{"id": 7, "body": "Excel BOM says 4 cavities, PLM has 2", "author_id": 2, "author_name": "Engineer", "created_at": "2026-09-24T10:12:00"}
```

`FieldNoteSummary` (list endpoints):
```json
{"id": 3, "part_id": 2295, "field_key": "tool.cavities", "flag_status": "open",
 "flag_set_by": 2, "flag_set_by_name": "Engineer", "flag_set_at": "2026-09-24T10:12:00",
 "created_at": "2026-09-24T10:11:00", "comment_count": 1, "last_comment": FieldNoteComment | null}
```

`FieldNoteThread` = `FieldNoteSummary` + `"comments": [FieldNoteComment, ...]` (oldest first). For a field without a note: `id`, `flag_*`, `created_at`, `last_comment` are null, `comment_count` 0, `comments` [].

| Method | Path | Body | Answer |
|---|---|---|---|
| GET | `/parts/{part_id}/field-notes?field_key=` | | `FieldNoteSummary[]` |
| GET | `/parts/{part_id}/field-notes/{field_key}` | | `FieldNoteThread` (empty thread if none) |
| POST | `/parts/{part_id}/field-notes/{field_key}/comments` | `{"body": "..."}` | 201 `FieldNoteThread` |
| PUT | `/parts/{part_id}/field-notes/{field_key}/flag` | `{"status": "open" \| "confirmed" \| "rejected" \| null}` | `FieldNoteThread` |
| GET | `/projects/{project_id}/field-notes` | | `FieldNoteSummary[]` of every part in the project |

Errors: bad field key or key not valid for the item category, whitespace-only comment: 400 `{"detail": "..."}`; empty body or unknown status: 422. Field key format: `^[a-z][a-z0-9_]{0,30}\.[a-z][a-z0-9_]{0,30}$`. Prefixes `tool.` and `dfm.` only on tools; `paint.` and `revision.` never on tools; `part.` on any part.

### Material

Part responses (`GET/PUT /parts/{id}`) gain: `material_source`, `materialdb_id`, `material_ktx_number`, `material_label`, `material_new_text`, `material_synced_at` (all nullable).

`MaterialHit`:
```json
{"id": 11, "ktx_number": "40-1234", "trade_name": "Ultramid B3WG6", "grade": "black 00564",
 "manufacturer": "BASF", "family": "PA6", "classification": "series", "label": "40-1234 Ultramid B3WG6 black 00564"}
```
A research material (no KTX number) has `label` like `"REZYcom PA6 RB122 F15 (research)"`.

| Method | Path | Body | Answer |
|---|---|---|---|
| GET | `/materials/search?q=` | | `MaterialHit[]` (max 20; `[]` when q has under 2 characters); 503 when MaterialDB is not configured or unreachable |
| PUT | `/parts/{part_id}/material` | `{"source": "materialdb", "materialdb_id": 11}` or `{"source": "new", "new_text": "PA6-GF15 acc. VW 50125"}` or `{"source": null}` | `PartResponse`; 400 not an article or id not in MaterialDB; 422 bad shape; 503 MaterialDB down |
| POST | `/parts/{part_id}/material/refresh` | | `PartResponse`; 400 not linked; 409 no longer in MaterialDB (label kept); 503 MaterialDB down (label kept) |

MaterialDB UI link (frontend only): `/materialdb/materials/{materialdb_id}` (MaterialDB frontend route `/materialdb/materials/:id`).

### Worksheet

`GET /projects/{project_id}/worksheet`:
```json
{"project_id": 35, "rows": [{
  "part_id": 2271, "row_kind": "article",
  "part_number": "20-1994-001-0", "customer_part_number": "206.882.251", "tier1_part_number": null,
  "name": "206.882.251 Handle, manual lift, passenger", "part_type": "internal_mfg", "item_category": "article",
  "thumbnail_url": null, "lifecycle_phase": "rfq",
  "colour_code": "NM0", "grain": "KF8",
  "mirror_of": null,
  "revision": {"revision_name": "E1", "customer_index": "001", "phase": "review"},
  "material": {"material_source": "new", "materialdb_id": null, "material_ktx_number": null,
               "material_label": null, "material_new_text": "PA6-GF15 acc. VW 50125", "material_synced_at": null},
  "paint": {"painted": false, "colour": null, "colour_hex": null, "paint_system": null},
  "tool": {"part_id": 2295, "part_number": "199401", "name": "1994 TOOL Handle", "cavities": 2,
           "toolmaker_id": null, "toolmaker_name": null, "cycle_time_s": 55.0, "tonnage_class": null},
  "other_tools": [],
  "dfm": {"status": "waiting", "waiting_on": ["ktx"], "open_topics": 1}
}]}
```
`colour_code`: the MIC colour of an unpainted article (e.g. `NM0`; a painted article's colour is in `paint`), `grain` (e.g. `KF8`): both article fields (`PUT /parts/{id}` with `colour_code` / `grain`, trimmed, empty clears, 400 on other categories, changelog `field_updated`), null when unset and on tool-only rows. `row_kind`: `article` | `purchased` (article with `part_type == "purchased"`) | `tool_only` (tool that produces no article of the project; then `tool` describes the row's own tool, `revision` is null, material all null, paint not painted). `mirror_of`: `{"part_id", "part_number", "customer_part_number"}` or null. `dfm`: null when the row has no tool; `status` one of `no_topic`, `waiting`, `all_answered`, `open`, `finished`; `waiting_on` ordered toolmaker, ktx, tier1.

`POST /projects/{project_id}/worksheet/export`:
```json
{"columns": [{"key": "part.part_number", "label": "KTX no.", "type": "text"},
             {"key": "tool.cavities", "label": "Cavities", "type": "number"}],
 "rows": [{"cells": [{"value": "20-1994-001-0", "flag": null, "comments": 0},
                     {"value": 2, "flag": "open", "comments": 1}]}],
 "frozen_columns": 2}
```
Answer: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `Content-Disposition: attachment; filename="<code>-worksheet-<YYYY-MM-DD>.xlsx"`. 422 when a row's cell count differs from the column count, more than 60 columns or 5000 rows.

---

## File structure

Backend (lane B):
- Create `backend/app/models/field_note.py`: `FieldNote`, `FieldNoteComment`, `FIELD_FLAG_STATUSES`.
- Modify `backend/app/models/__init__.py`: import the two models.
- Create `backend/alembic/versions/082_field_notes.py`.
- Create `backend/app/services/field_note_service.py`: validation, comment, flag, listing, serialization.
- Create `backend/app/api/v1/items/field_notes.py`: the five field note routes.
- Modify `backend/app/api/v1/__init__.py`: register new routers.
- Modify `backend/app/models/part.py`, `backend/app/schemas/part.py`: material columns and response fields.
- Create `backend/alembic/versions/083_part_material.py`.
- Modify `backend/app/core/config.py`: `materialdb_base_url`, `materialdb_service_token`.
- Create `backend/app/services/materialdb_client.py`: fetch, cache, search, find, label.
- Create `backend/app/services/part_material_service.py`: link, new, clear, refresh with changelog.
- Create `backend/app/api/v1/items/materials.py`: search, put material, refresh.
- Create `backend/app/services/worksheet_service.py`: `worksheet_rows`, `dfm_status`.
- Create `backend/app/services/worksheet_export.py`: `build_xlsx`.
- Create `backend/app/api/v1/items/worksheet.py`: rows and export routes.
- Create `backend/scripts/import_1994_worksheet_notes.py`.
- Tests: `backend/tests/test_field_notes.py`, `test_field_notes_api.py`, `test_part_material.py`, `test_materialdb_search.py`, `test_worksheet.py`, `test_worksheet_export.py`, `test_import_1994_worksheet_notes.py`; `backend/tests/conftest.py` gains a `materialdb` fixture.

Frontend (lane F):
- Create `frontend/src/api/fieldNotes.ts`, `api/materials.ts`, `api/worksheet.ts`.
- Create `frontend/src/hooks/queries/useFieldNotes.ts`, `hooks/queries/useWorksheet.ts`, `hooks/useFieldFocus.ts`.
- Create `frontend/src/lib/fieldNotes.ts`, `lib/material.ts`.
- Create `frontend/src/components/fieldNotes/FieldNoteMarker.tsx`, `FieldNotePopover.tsx`.
- Create `frontend/src/components/materials/MaterialValue.tsx`, `MaterialField.tsx`.
- Create `frontend/src/components/worksheet/worksheetColumns.ts`, `worksheetTable.ts`, `WorksheetView.tsx`, `WorksheetCell.tsx`, `WorksheetCellMenu.tsx`.
- Modify `frontend/src/pages/PartDetail.tsx`, `pages/ToolDetail.tsx`, `components/tools/ToolFieldsCard.tsx`, `components/paint/PartPaintCard.tsx`, `components/project/ItemsPane.tsx`, `pages/ProjectDetailPage.tsx`.
- Tests next to sources.

## Lanes and order

| Task | Title | Lane | Depends on |
|---|---|---|---|
| 1 | Field notes model, migration 082, service | B-notes | none |
| 2 | Field notes API and changelog | B-notes | 1 |
| 3 | Material columns on parts, migration 083 | B-material | none |
| 4 | MaterialDB client, settings and proxy search | B-material | none (3 only for file order) |
| 5 | Pick, new material, clear and refresh endpoints | B-material | 3, 4 |
| 6 | Worksheet rows endpoint | B | 3 |
| 7 | Worksheet xlsx export endpoint | B | 6 (same router file) |
| 8 | Frontend api modules and query hooks | F | contract only |
| 9 | FieldNoteMarker and popover | F | 8 |
| 10 | Material field on the article page | F | 8 |
| 11 | Field markers and focus highlight on article, tool and paint | F | 9, 10 |
| 12 | Column registry | F | 8 |
| 13 | Worksheet table: filter, sort, hide, freeze, flag filter, page toggle | F | 9, 12 |
| 14 | Cell context menu: edit, comment, flag | F | 13 |
| 15 | Export button | F | 13 (needs 7 only for the browser check) |
| 16 | 1994 import script (dry run default) | B | 2, 5 |
| 17 | Verification | all | all |

Parallel lanes: the backend lane (Tasks 1 to 7, then 16) and the frontend lane (Tasks 8 to 15) run at the same time; the frontend mocks `api/client` and codes against the contract above. Inside the backend lane, B-notes (1, 2) and B-material (3, 4, 5) can run in parallel; both append one import line to `backend/app/api/v1/__init__.py` and `backend/app/models/__init__.py` (Task 1 only), so the second lane to merge resolves a one-line conflict. Inside the frontend lane, Tasks 9, 10 and 12 can run in parallel after 8. Task 17 runs last.

---

### Task 1: Field notes model, migration 082, service

**Files:**
- Create: `backend/app/models/field_note.py`
- Modify: `backend/app/models/__init__.py` (after the `from app.models.dfm import ...` line)
- Create: `backend/alembic/versions/082_field_notes.py`
- Create: `backend/app/services/field_note_service.py`
- Test: `backend/tests/test_field_notes.py`

**Interfaces:**
- Consumes: `ChangelogService.log_action(session, part_id, action, action_description, performed_by, field_name=, old_value=, new_value=)` from `app/services/part_service.py`; `user_names(session, ids) -> dict[int, str]` from `app/services/dfm_service.py`.
- Produces:
  - `FIELD_FLAG_STATUSES = ("open", "confirmed", "rejected")` in `app.models.field_note`
  - `class FieldNoteError(ValueError)`
  - `check_field_key(part: Part, field_key: str) -> None` (raises `FieldNoteError`)
  - `FieldNoteService.get(session, part_id, field_key) -> FieldNote | None`
  - `FieldNoteService.add_comment(session, part, field_key, body, user_id) -> FieldNote`
  - `FieldNoteService.set_flag(session, part, field_key, status: str | None, user_id) -> FieldNote | None`
  - `FieldNoteService.list_for_part(session, part_id, field_key=None) -> list[FieldNote]`
  - `FieldNoteService.list_for_project(session, project_id) -> list[FieldNote]`
  - `FieldNoteService.names_for(session, notes) -> dict[int, str]`
  - `FieldNoteService.summary(note, names) -> dict`, `.thread(note, names) -> dict`, `.empty_thread(part_id, field_key) -> dict` (shapes as in the contract)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_field_notes.py`:
```python
"""Field notes: one thread per (part, field_key), append-only comments, a flag,
and a changelog entry on the part for every comment and flag change."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.field_note import FieldNote
from app.models.part import Part, RevisionChangelog
from app.services.field_note_service import FieldNoteError, FieldNoteService

pytestmark = pytest.mark.asyncio


async def _mk(session_factory, seed, number="A-1", category="article"):
    async with session_factory() as s:
        p = Part(project_id=seed["project_id"], part_number=number, name=number,
                 part_type="internal_mfg", item_category=category, created_by=seed["engineer_id"])
        s.add(p)
        await s.commit()
        return p.id


async def _log(session_factory, part_id):
    async with session_factory() as s:
        return (await s.execute(select(RevisionChangelog).where(RevisionChangelog.part_id == part_id)
                                .order_by(RevisionChangelog.id))).scalars().all()


async def test_comments_share_one_note_per_field_and_append(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        await FieldNoteService.add_comment(s, part, "part.material", "Resin to be nominated", seed["engineer_id"])
        await FieldNoteService.add_comment(s, part, "part.material", "  Virgin grade asked  ", seed["engineer_id"])
        await FieldNoteService.add_comment(s, part, "part.name", "Drawing says Latch Cover 40", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        notes = (await s.execute(select(FieldNote).order_by(FieldNote.field_key))).scalars().all()
        assert [n.field_key for n in notes] == ["part.material", "part.name"]
        assert [c.body for c in notes[0].comments] == ["Resin to be nominated", "Virgin grade asked"]
    log = await _log(session_factory, pid)
    assert [e.action for e in log] == ["field_comment_added"] * 3
    assert log[0].field_name == "part.material"
    assert log[1].new_value == "Virgin grade asked"


async def test_blank_or_too_long_comment_is_refused(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.add_comment(s, part, "part.material", "   ", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.add_comment(s, part, "part.material", "x" * 4001, seed["engineer_id"])


@pytest.mark.parametrize("key", ["cavities", "Tool.cavities", "tool.", ".x", "tool.cav-ities", "a.b.c", ""])
async def test_malformed_keys_are_refused(session_factory, seed, key):
    pid = await _mk(session_factory, seed, category="tool")
    async with session_factory() as s:
        part = await s.get(Part, pid)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.add_comment(s, part, key, "x", seed["engineer_id"])


async def test_key_prefix_must_fit_the_item_category(session_factory, seed):
    article = await _mk(session_factory, seed, "A-1", "article")
    tool = await _mk(session_factory, seed, "T-1", "tool")
    async with session_factory() as s:
        a, t = await s.get(Part, article), await s.get(Part, tool)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, a, "tool.cavities", "open", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, a, "dfm.status", "open", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, t, "paint.colour", "open", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, t, "revision.level", "open", seed["engineer_id"])
        # part.* applies to both
        assert await FieldNoteService.set_flag(s, t, "part.name", "open", seed["engineer_id"]) is not None
        assert await FieldNoteService.set_flag(s, a, "part.name", "open", seed["engineer_id"]) is not None


async def test_flag_transitions_are_logged_and_same_value_is_a_no_op(session_factory, seed):
    pid = await _mk(session_factory, seed, category="tool")
    uid = seed["engineer_id"]
    async with session_factory() as s:
        part = await s.get(Part, pid)
        note = await FieldNoteService.set_flag(s, part, "tool.cavities", "open", uid)
        assert (note.flag_status, note.flag_set_by) == ("open", uid)
        assert note.flag_set_at is not None
        await FieldNoteService.set_flag(s, part, "tool.cavities", "open", uid)  # same: nothing logged
        await FieldNoteService.set_flag(s, part, "tool.cavities", "confirmed", uid)
        await FieldNoteService.set_flag(s, part, "tool.cavities", "rejected", uid)
        note = await FieldNoteService.set_flag(s, part, "tool.cavities", None, uid)
        assert (note.flag_status, note.flag_set_by, note.flag_set_at) == (None, None, None)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, part, "tool.cavities", "maybe", uid)
        await s.commit()
    log = await _log(session_factory, pid)
    assert [(e.action, e.old_value, e.new_value) for e in log] == [
        ("field_flag_set", None, "open"),
        ("field_flag_set", "open", "confirmed"),
        ("field_flag_set", "confirmed", "rejected"),
        ("field_flag_set", "rejected", None),
    ]


async def test_clearing_a_flag_that_never_existed_creates_nothing(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        assert await FieldNoteService.set_flag(s, part, "part.material", None, seed["engineer_id"]) is None
        await s.commit()
    async with session_factory() as s:
        assert (await s.execute(select(FieldNote))).scalars().all() == []
    assert await _log(session_factory, pid) == []


async def test_one_note_per_part_and_field(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        s.add_all([FieldNote(part_id=pid, field_key="part.name"), FieldNote(part_id=pid, field_key="part.name")])
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_serialized_thread_and_summary(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        await FieldNoteService.add_comment(s, part, "part.material", "first", seed["engineer_id"])
        note = await FieldNoteService.set_flag(s, part, "part.material", "open", seed["engineer_id"])
        await FieldNoteService.add_comment(s, part, "part.material", "second", seed["admin_id"])
        names = await FieldNoteService.names_for(s, [note])
        summary = FieldNoteService.summary(note, names)
        thread = FieldNoteService.thread(note, names)
    assert summary["field_key"] == "part.material"
    assert summary["flag_status"] == "open"
    assert summary["flag_set_by_name"] == "Engineer"
    assert summary["comment_count"] == 2
    assert summary["last_comment"]["body"] == "second"
    assert summary["last_comment"]["author_name"] == "Admin"
    assert "comments" not in summary
    assert [c["body"] for c in thread["comments"]] == ["first", "second"]
    empty = FieldNoteService.empty_thread(pid, "part.name")
    assert empty == {"id": None, "part_id": pid, "field_key": "part.name", "flag_status": None,
                     "flag_set_by": None, "flag_set_by_name": None, "flag_set_at": None,
                     "created_at": None, "comment_count": 0, "last_comment": None, "comments": []}


async def test_list_for_project_only_returns_that_projects_parts(session_factory, seed):
    from app.models.entities import Project
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        home = await s.get(Project, seed["project_id"])
        other = Project(plant_id=home.plant_id, name="Other", code="other", status="active")
        s.add(other)
        await s.flush()
        foreign = Part(project_id=other.id, part_number="F-1", name="F", part_type="internal_mfg",
                       item_category="article", created_by=seed["engineer_id"])
        s.add(foreign)
        await s.flush()
        await FieldNoteService.add_comment(s, await s.get(Part, pid), "part.name", "mine", seed["engineer_id"])
        await FieldNoteService.add_comment(s, foreign, "part.name", "not mine", seed["engineer_id"])
        await s.commit()
        notes = await FieldNoteService.list_for_project(s, seed["project_id"])
    assert [n.part_id for n in notes] == [pid]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_field_notes.py -n 0 -q`
Expected: collection error `ModuleNotFoundError: No module named 'app.models.field_note'`.

- [ ] **Step 3: Write the model**

`backend/app/models/field_note.py`:
```python
"""Comments and a flag on one field of one part (article or tool).

A field is addressed by (part_id, field_key); field_key is the stable key of
the worksheet column registry (frontend/src/components/worksheet/worksheetColumns.ts),
e.g. tool.cavities, part.material, paint.colour. Tool fields live on the tool,
so a flag on tool.cavities shows on every article row that tool makes.
Comments are append only: a correction is a new comment.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

FIELD_FLAG_STATUSES = ("open", "confirmed", "rejected")


class FieldNote(Base):
    __tablename__ = "field_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), index=True)
    field_key: Mapped[str] = mapped_column(String(64))
    flag_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    flag_set_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    flag_set_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    comments: Mapped[list["FieldNoteComment"]] = relationship(
        back_populates="note", cascade="all, delete-orphan",
        order_by="FieldNoteComment.created_at, FieldNoteComment.id", lazy="selectin")

    __table_args__ = (UniqueConstraint("part_id", "field_key", name="uq_field_note_part_field"),)


class FieldNoteComment(Base):
    __tablename__ = "field_note_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("field_notes.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    note: Mapped[FieldNote] = relationship(back_populates="comments")
```

In `backend/app/models/__init__.py`, add after `from app.models.dfm import DfmTopic, DfmEntry, DfmEntryFile, DfmAuditEvent`:
```python
from app.models.field_note import FieldNote, FieldNoteComment
```

- [ ] **Step 4: Write the migration**

`backend/alembic/versions/082_field_notes.py`:
```python
"""082: field notes (comments and a flag per part and field) for the project worksheet.

field_notes: one row per (part_id, field_key), flag null | open | confirmed | rejected.
field_note_comments: append-only comments of a note.

Revision ID: 082
Revises: 081
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "field_notes" not in tables:
        op.create_table(
            "field_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("field_key", sa.String(64), nullable=False),
            sa.Column("flag_status", sa.String(20), nullable=True),
            sa.Column("flag_set_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("flag_set_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("part_id", "field_key", name="uq_field_note_part_field"),
        )
    if "field_note_comments" not in tables:
        op.create_table(
            "field_note_comments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("field_notes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    insp = inspect(bind)
    if "ix_field_notes_part_id" not in {i["name"] for i in insp.get_indexes("field_notes")}:
        op.create_index("ix_field_notes_part_id", "field_notes", ["part_id"])
    if "ix_field_note_comments_note_id" not in {i["name"] for i in insp.get_indexes("field_note_comments")}:
        op.create_index("ix_field_note_comments_note_id", "field_note_comments", ["note_id"])


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "field_note_comments" in tables:
        op.drop_table("field_note_comments")
    if "field_notes" in tables:
        op.drop_table("field_notes")
```

- [ ] **Step 5: Write the service**

`backend/app/services/field_note_service.py`:
```python
"""Comments and a flag on one field of a part: the worksheet's way to find
discrepancies between drawing, RFQ and PLM. One note per (part, field_key);
comments are append only; every comment and flag change is logged on the
part's changelog so the part history shows it."""
import re
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_note import FIELD_FLAG_STATUSES, FieldNote, FieldNoteComment
from app.models.part import Part
from app.services.dfm_service import user_names
from app.services.part_service import ChangelogService

FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}\.[a-z][a-z0-9_]{0,30}$")
TOOL_PREFIXES = ("tool", "dfm")
NOT_ON_TOOL_PREFIXES = ("paint", "revision")
MAX_COMMENT_LENGTH = 4000


class FieldNoteError(ValueError):
    """Bad field key, key not valid for the item category, bad flag or empty comment."""


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def check_field_key(part: Part, field_key: str) -> None:
    if not FIELD_KEY_RE.match(field_key or ""):
        raise FieldNoteError(f"Invalid field key '{field_key}': expected <group>.<field> in lower case")
    prefix = field_key.split(".", 1)[0]
    if prefix in TOOL_PREFIXES and part.item_category != "tool":
        raise FieldNoteError(f"'{field_key}' is a tool field and {part.part_number} is not a tool")
    if prefix in NOT_ON_TOOL_PREFIXES and part.item_category == "tool":
        raise FieldNoteError(f"'{field_key}' does not apply to a tool")


def _comment_dict(c: FieldNoteComment, names: dict) -> dict:
    return {"id": c.id, "body": c.body, "author_id": c.author_id,
            "author_name": names.get(c.author_id), "created_at": _iso(c.created_at)}


class FieldNoteService:

    @staticmethod
    async def get(session: AsyncSession, part_id: int, field_key: str) -> Optional[FieldNote]:
        return (await session.execute(select(FieldNote).where(
            FieldNote.part_id == part_id, FieldNote.field_key == field_key))).scalar_one_or_none()

    @staticmethod
    async def _get_or_new(session: AsyncSession, part: Part, field_key: str) -> FieldNote:
        note = await FieldNoteService.get(session, part.id, field_key)
        if note is None:
            note = FieldNote(part_id=part.id, field_key=field_key, comments=[])
            session.add(note)
            await session.flush()
        return note

    @staticmethod
    async def add_comment(session: AsyncSession, part: Part, field_key: str, body: str,
                          user_id: int) -> FieldNote:
        check_field_key(part, field_key)
        text = (body or "").strip()
        if not text:
            raise FieldNoteError("A comment must not be empty")
        if len(text) > MAX_COMMENT_LENGTH:
            raise FieldNoteError(f"A comment is at most {MAX_COMMENT_LENGTH} characters")
        note = await FieldNoteService._get_or_new(session, part, field_key)
        note.comments.append(FieldNoteComment(body=text, author_id=user_id))
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=part.id, action="field_comment_added",
            action_description=f"Comment on {field_key}: {text[:200]}",
            performed_by=user_id, field_name=field_key, new_value=text[:500])
        return note

    @staticmethod
    async def set_flag(session: AsyncSession, part: Part, field_key: str, status: Optional[str],
                       user_id: int) -> Optional[FieldNote]:
        """status None clears. Setting the current value again changes and logs nothing."""
        check_field_key(part, field_key)
        if status is not None and status not in FIELD_FLAG_STATUSES:
            raise FieldNoteError(f"Unknown flag '{status}'. Valid: {', '.join(FIELD_FLAG_STATUSES)} or none")
        note = await FieldNoteService.get(session, part.id, field_key)
        if note is None:
            if status is None:
                return None
            note = await FieldNoteService._get_or_new(session, part, field_key)
        old = note.flag_status
        if old == status:
            return note
        note.flag_status = status
        note.flag_set_by = user_id if status else None
        note.flag_set_at = datetime.utcnow() if status else None
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=part.id, action="field_flag_set",
            action_description=f"Flag on {field_key}: {old or 'none'} to {status or 'cleared'}",
            performed_by=user_id, field_name=field_key, old_value=old, new_value=status)
        return note

    @staticmethod
    async def list_for_part(session: AsyncSession, part_id: int,
                            field_key: Optional[str] = None) -> list[FieldNote]:
        q = select(FieldNote).where(FieldNote.part_id == part_id)
        if field_key:
            q = q.where(FieldNote.field_key == field_key)
        return list((await session.execute(q.order_by(FieldNote.field_key))).scalars().all())

    @staticmethod
    async def list_for_project(session: AsyncSession, project_id: int) -> list[FieldNote]:
        return list((await session.execute(
            select(FieldNote).join(Part, Part.id == FieldNote.part_id)
            .where(Part.project_id == project_id)
            .order_by(FieldNote.part_id, FieldNote.field_key))).scalars().all())

    @staticmethod
    async def names_for(session: AsyncSession, notes: Iterable[FieldNote]) -> dict:
        ids: set = set()
        for n in notes:
            ids.add(n.flag_set_by)
            ids.update(c.author_id for c in n.comments)
        return await user_names(session, ids)

    @staticmethod
    def summary(note: FieldNote, names: dict) -> dict:
        comments = list(note.comments)
        return {
            "id": note.id, "part_id": note.part_id, "field_key": note.field_key,
            "flag_status": note.flag_status, "flag_set_by": note.flag_set_by,
            "flag_set_by_name": names.get(note.flag_set_by), "flag_set_at": _iso(note.flag_set_at),
            "created_at": _iso(note.created_at), "comment_count": len(comments),
            "last_comment": _comment_dict(comments[-1], names) if comments else None,
        }

    @staticmethod
    def thread(note: FieldNote, names: dict) -> dict:
        return {**FieldNoteService.summary(note, names),
                "comments": [_comment_dict(c, names) for c in note.comments]}

    @staticmethod
    def empty_thread(part_id: int, field_key: str) -> dict:
        return {"id": None, "part_id": part_id, "field_key": field_key, "flag_status": None,
                "flag_set_by": None, "flag_set_by_name": None, "flag_set_at": None,
                "created_at": None, "comment_count": 0, "last_comment": None, "comments": []}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_field_notes.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 7: Check the migration on a scratch SQLite DB**

```bash
cd /home/nitrolinux/claude/plm2-integ/backend
DB=sqlite+aiosqlite:////tmp/claude-1000/-home-nitrolinux-claude-plm2/682e27d6-86ce-49d1-8aa2-d85ccfa61993/scratchpad/ws082.db
DATABASE_URL=$DB python3 -m alembic upgrade head && DATABASE_URL=$DB python3 -m alembic upgrade head && DATABASE_URL=$DB python3 -m alembic current
```
Expected: ends at `082 (head)` (or `083` if Task 3 already landed); the second run is a no-op.

- [ ] **Step 8: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/models/field_note.py backend/app/models/__init__.py backend/alembic/versions/082_field_notes.py backend/app/services/field_note_service.py backend/tests/test_field_notes.py
git commit -m "feat(field-notes): comments and a flag per part field, migration 082

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Field notes API and changelog

**Files:**
- Create: `backend/app/api/v1/items/field_notes.py`
- Modify: `backend/app/api/v1/__init__.py` (import next to `dfm_router`, include after `api_router.include_router(dfm_router)`)
- Test: `backend/tests/test_field_notes_api.py`

**Interfaces:**
- Consumes: Task 1 service; `_part_in_org(db, part_id, org_id)`, `_project_in_org(db, project_id, org_id)` from `app/api/v1/items/part_paint.py`.
- Produces: the five field note routes of the contract.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_field_notes_api.py`:
```python
"""Field notes over HTTP: threads, comments, flags, project listing, org scoping."""
import pytest

pytestmark = pytest.mark.asyncio


async def _part(client, auth, seed, number, category="article"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": "internal_mfg", "item_category": category}
    r = await client.post("/api/v1/parts", json=body, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_thread_is_empty_until_the_first_comment(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed, "A-1")
    r = await client.get(f"/api/v1/parts/{pid}/field-notes/part.material", headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["id"] is None and r.json()["comments"] == []

    r = await client.post(f"/api/v1/parts/{pid}/field-notes/part.material/comments",
                          json={"body": "Resin to be nominated"}, headers=eng_auth)
    assert r.status_code == 201, r.text
    thread = r.json()
    assert thread["comment_count"] == 1
    assert thread["comments"][0]["body"] == "Resin to be nominated"
    assert thread["comments"][0]["author_name"] == "Engineer"

    r = await client.get(f"/api/v1/parts/{pid}/field-notes", headers=eng_auth)
    assert [n["field_key"] for n in r.json()] == ["part.material"]
    assert "comments" not in r.json()[0]


async def test_flag_set_and_clear_over_http_with_changelog(client, eng_auth, seed):
    tid = await _part(client, eng_auth, seed, "T-1", "tool")
    r = await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag",
                         json={"status": "open"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["flag_status"] == "open"
    assert r.json()["flag_set_by_name"] == "Engineer"
    r = await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag",
                         json={"status": None}, headers=eng_auth)
    assert r.json()["flag_status"] is None
    r = await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag",
                         json={"status": "maybe"}, headers=eng_auth)
    assert r.status_code == 422
    log = (await client.get(f"/api/v1/parts/{tid}/changelog", headers=eng_auth)).json()
    assert [e["action"] for e in log if e["action"].startswith("field_")] == ["field_flag_set", "field_flag_set"]


async def test_clearing_a_missing_flag_returns_an_empty_thread(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed, "A-1")
    r = await client.put(f"/api/v1/parts/{pid}/field-notes/part.name/flag", json={"status": None}, headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["id"] is None


@pytest.mark.parametrize("key", ["Tool.cavities", "cavities", "tool.cavities"])
async def test_bad_field_keys_are_400(client, eng_auth, seed, key):
    pid = await _part(client, eng_auth, seed, "A-1")  # an article: tool.cavities does not apply
    r = await client.post(f"/api/v1/parts/{pid}/field-notes/{key}/comments", json={"body": "x"}, headers=eng_auth)
    assert r.status_code == 400, r.text
    assert "detail" in r.json()
    r = await client.get(f"/api/v1/parts/{pid}/field-notes/{key}", headers=eng_auth)
    assert r.status_code == 400


async def test_empty_and_blank_comments(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed, "A-1")
    r = await client.post(f"/api/v1/parts/{pid}/field-notes/part.name/comments", json={"body": ""}, headers=eng_auth)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/parts/{pid}/field-notes/part.name/comments", json={"body": "   "}, headers=eng_auth)
    assert r.status_code == 400


async def test_project_listing_includes_tools_and_stays_in_the_project(client, eng_auth, seed, session_factory):
    from app.models.entities import Project
    from app.models.part import Part
    aid = await _part(client, eng_auth, seed, "A-1")
    tid = await _part(client, eng_auth, seed, "T-1", "tool")
    async with session_factory() as s:
        home = await s.get(Project, seed["project_id"])
        other = Project(plant_id=home.plant_id, name="Other", code="other", status="active")
        s.add(other)
        await s.flush()
        foreign = Part(project_id=other.id, part_number="F-1", name="F", part_type="internal_mfg",
                       item_category="article", created_by=seed["engineer_id"])
        s.add(foreign)
        await s.commit()
        other_id, foreign_id = other.id, foreign.id
    await client.post(f"/api/v1/parts/{aid}/field-notes/part.material/comments", json={"body": "a"}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{tid}/field-notes/tool.cavities/flag", json={"status": "open"}, headers=eng_auth)
    await client.post(f"/api/v1/parts/{foreign_id}/field-notes/part.name/comments", json={"body": "b"}, headers=eng_auth)

    r = await client.get(f"/api/v1/projects/{seed['project_id']}/field-notes", headers=eng_auth)
    assert r.status_code == 200
    assert sorted((n["part_id"], n["field_key"]) for n in r.json()) == sorted(
        [(aid, "part.material"), (tid, "tool.cavities")])
    r = await client.get(f"/api/v1/projects/{other_id}/field-notes", headers=eng_auth)
    assert [n["part_id"] for n in r.json()] == [foreign_id]


async def test_other_org_part_and_project_are_404(client, eng_auth, session_factory, seed):
    from app.models.entities import Organization, Plant, Project
    from app.models.part import Part
    async with session_factory() as s:
        org = Organization(name="Other Org FN", code="other-org-fn", is_active=True)
        s.add(org)
        await s.flush()
        plant = Plant(organization_id=org.id, name="P", code="p-fn", location="DE", is_active=True)
        s.add(plant)
        await s.flush()
        project = Project(plant_id=plant.id, name="X", code="x-fn", status="active")
        s.add(project)
        await s.flush()
        part = Part(project_id=project.id, part_number="X-1", name="X", part_type="internal_mfg",
                    item_category="article", created_by=seed["admin_id"])
        s.add(part)
        await s.commit()
        pid, prj = part.id, project.id
    assert (await client.get(f"/api/v1/parts/{pid}/field-notes", headers=eng_auth)).status_code == 404
    assert (await client.post(f"/api/v1/parts/{pid}/field-notes/part.name/comments",
                              json={"body": "x"}, headers=eng_auth)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{prj}/field-notes", headers=eng_auth)).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_field_notes_api.py -n 0 -q`
Expected: FAIL, 404 on every field-notes route.

- [ ] **Step 3: Write the router**

`backend/app/api/v1/items/field_notes.py`:
```python
"""Field notes (comments and a flag per field) on parts, and every note of a
project for the worksheet. Org scoping as in part_paint.py: a part or project
of another organization is 404."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _part_in_org, _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.part import Part
from app.services.field_note_service import FieldNoteError, FieldNoteService, check_field_key

router = APIRouter(tags=["field-notes"])


class CommentIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class FlagIn(BaseModel):
    status: Optional[Literal["open", "confirmed", "rejected"]] = None


async def _part(db: AsyncSession, part_id: int, user: User) -> Part:
    await _part_in_org(db, part_id, user.organization_id)
    return await db.get(Part, part_id)


def _bad_request(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/parts/{part_id}/field-notes", response_model=List[dict])
async def list_part_notes(part_id: int, field_key: Optional[str] = Query(None),
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    notes = await FieldNoteService.list_for_part(db, part.id, field_key)
    names = await FieldNoteService.names_for(db, notes)
    return [FieldNoteService.summary(n, names) for n in notes]


@router.get("/parts/{part_id}/field-notes/{field_key}", response_model=dict)
async def get_note_thread(part_id: int, field_key: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    try:
        check_field_key(part, field_key)
    except FieldNoteError as e:
        raise _bad_request(e)
    note = await FieldNoteService.get(db, part.id, field_key)
    if note is None:
        return FieldNoteService.empty_thread(part.id, field_key)
    return FieldNoteService.thread(note, await FieldNoteService.names_for(db, [note]))


@router.post("/parts/{part_id}/field-notes/{field_key}/comments", response_model=dict,
             status_code=status.HTTP_201_CREATED)
async def add_note_comment(part_id: int, field_key: str, body: CommentIn,
                           current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    try:
        note = await FieldNoteService.add_comment(db, part, field_key, body.body, current_user.id)
    except FieldNoteError as e:
        await db.rollback()
        raise _bad_request(e)
    out = FieldNoteService.thread(note, await FieldNoteService.names_for(db, [note]))
    await db.commit()
    return out


@router.put("/parts/{part_id}/field-notes/{field_key}/flag", response_model=dict)
async def set_note_flag(part_id: int, field_key: str, body: FlagIn,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    try:
        note = await FieldNoteService.set_flag(db, part, field_key, body.status, current_user.id)
    except FieldNoteError as e:
        await db.rollback()
        raise _bad_request(e)
    if note is None:
        out = FieldNoteService.empty_thread(part.id, field_key)
    else:
        out = FieldNoteService.thread(note, await FieldNoteService.names_for(db, [note]))
    await db.commit()
    return out


@router.get("/projects/{project_id}/field-notes", response_model=List[dict])
async def list_project_notes(project_id: int, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    notes = await FieldNoteService.list_for_project(db, project_id)
    names = await FieldNoteService.names_for(db, notes)
    return [FieldNoteService.summary(n, names) for n in notes]
```

In `backend/app/api/v1/__init__.py`, add after `from app.api.v1.items.dfm import router as dfm_router`:
```python
from app.api.v1.items.field_notes import router as field_notes_router
```
and after `api_router.include_router(dfm_router)`:
```python
api_router.include_router(field_notes_router)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_field_notes_api.py tests/test_field_notes.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/api/v1/items/field_notes.py backend/app/api/v1/__init__.py backend/tests/test_field_notes_api.py
git commit -m "feat(field-notes): API for threads, comments, flags and project listing

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Material columns on parts, migration 083

**Files:**
- Modify: `backend/app/models/part.py` (after the tool fields block, before `name`)
- Modify: `backend/app/schemas/part.py` (`PartResponse`)
- Create: `backend/alembic/versions/083_part_material.py`
- Test: `backend/tests/test_part_material.py` (first test only; Task 5 appends)

**Interfaces:**
- Produces: `Part.material_source`, `Part.materialdb_id`, `Part.material_ktx_number`, `Part.material_label`, `Part.material_synced_at`, `Part.material_new_text`; the same names on `PartResponse`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_part_material.py`:
```python
"""Material on the article: linked to MaterialDB or explicitly new."""
import pytest

pytestmark = pytest.mark.asyncio

MATERIAL_FIELDS = ("material_source", "materialdb_id", "material_ktx_number",
                   "material_label", "material_synced_at", "material_new_text")


async def _part(client, auth, seed, number="A-1", category="article"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": "internal_mfg", "item_category": category}
    r = await client.post("/api/v1/parts", json=body, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_new_part_has_no_material(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert {k: body[k] for k in MATERIAL_FIELDS} == {k: None for k in MATERIAL_FIELDS}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_part_material.py -n 0 -q`
Expected: FAIL with `KeyError: 'material_source'`.

- [ ] **Step 3: Add the columns and response fields**

In `backend/app/models/part.py`, after `tool_cycle_time_s: ...` and before `name: Mapped[str] = ...`:
```python
    # Material (item_category = article only). Linked to MaterialDB (a series
    # material with a 40- KTX number, or a research material without one) or
    # explicitly new, not in MaterialDB yet. material_label caches the display
    # text so a link still reads when MaterialDB is down.
    material_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # materialdb | new
    materialdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    material_ktx_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    material_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    material_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    material_new_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

In `backend/app/schemas/part.py`, in `PartResponse` after `thumbnail_url: Optional[str] = None`:
```python
    material_source: Optional[str] = None
    materialdb_id: Optional[int] = None
    material_ktx_number: Optional[str] = None
    material_label: Optional[str] = None
    material_synced_at: Optional[datetime] = None
    material_new_text: Optional[str] = None
```

- [ ] **Step 4: Write the migration**

`backend/alembic/versions/083_part_material.py`:
```python
"""083: material on parts (articles), linked to MaterialDB or marked new.

Revision ID: 083
Revises: 082
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None

COLUMNS = [
    ("material_source", sa.String(20)),
    ("materialdb_id", sa.Integer()),
    ("material_ktx_number", sa.String(20)),
    ("material_label", sa.String(300)),
    ("material_synced_at", sa.DateTime()),
    ("material_new_text", sa.String(500)),
]
INDEX = "ix_parts_materialdb_id"


def upgrade() -> None:
    bind = op.get_bind()
    have = {c["name"] for c in inspect(bind).get_columns("parts")}
    missing = [(n, t) for n, t in COLUMNS if n not in have]
    if missing:
        with op.batch_alter_table("parts") as batch:
            for name, type_ in missing:
                batch.add_column(sa.Column(name, type_, nullable=True))
    if INDEX not in {i["name"] for i in inspect(bind).get_indexes("parts")}:
        op.create_index(INDEX, "parts", ["materialdb_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if INDEX in {i["name"] for i in inspect(bind).get_indexes("parts")}:
        op.drop_index(INDEX, table_name="parts")
    have = {c["name"] for c in inspect(bind).get_columns("parts")}
    present = [n for n, _ in COLUMNS if n in have]
    if present:
        with op.batch_alter_table("parts") as batch:
            for name in present:
                batch.drop_column(name)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_part_material.py tests/test_part_thumbnail.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 6: Check the migration chain on the scratch SQLite DB**

Run the Task 1 Step 7 commands again (same `ws082.db`). Expected: ends at `083 (head)`; the rerun is a no-op. If Task 1 has not landed yet in this lane, skip this step (083 revises 082) and run it after merging.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/models/part.py backend/app/schemas/part.py backend/alembic/versions/083_part_material.py backend/tests/test_part_material.py
git commit -m "feat(material): material columns on parts, migration 083

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: MaterialDB client, settings and proxy search

MaterialDB facts this task relies on (read from `/home/nitrolinux/claude/MaterialDB`): the service router is `APIRouter(prefix="/v1", dependencies=[require_service_token])` mounted at the app root; nginx strips `/materialdb/api`, so through the hub the list is `https://<hub>/materialdb/api/v1/materials` and inside the docker network `http://materialdb-backend:8000/v1/materials`. Only two machine routes exist: `GET /v1/materials` (full list of `serialize.summary`: `id`, `ktx_number`, `trade_name`, `grade`, `manufacturer`, `family`, `classification`, `iso_designation`, `supplier`, ... plus `props`) and `GET /v1/materials/{ktx_number}`. The text search `GET /search` is user-auth only, and research materials have no KTX number, so PLM searches and looks up by id in the cached full list.

**Files:**
- Modify: `backend/app/core/config.py` (after `hub_api_base`)
- Create: `backend/app/services/materialdb_client.py`
- Create: `backend/app/api/v1/items/materials.py` (search route; Task 5 adds the part routes)
- Modify: `backend/app/api/v1/__init__.py`
- Modify: `backend/tests/conftest.py` (append the `materialdb` fixture)
- Test: `backend/tests/test_materialdb_search.py`

**Interfaces:**
- Produces:
  - Settings `materialdb_base_url: str = ""`, `materialdb_service_token: str = ""`
  - `materialdb_client.TRANSPORT` (tests swap in `httpx.MockTransport`), `CACHE_SECONDS = 60.0`
  - `class MaterialDbUnavailable(Exception)` (message shown to the user)
  - `async fetch_all(force: bool = False) -> list[dict]`
  - `async search(q: str, limit: int = 20) -> list[dict]` (MaterialHit dicts)
  - `async find_by_id(material_id: int, force: bool = False) -> dict | None`
  - `label(m: dict) -> str`, `hit(m: dict) -> dict`, `clear_cache() -> None`
  - conftest fixture `materialdb` yielding `state = {"items": [...], "fail": None | "down" | "500", "calls": 0}`
  - Route `GET /api/v1/materials/search?q=`

- [ ] **Step 1: Add the conftest fixture**

Append to `backend/tests/conftest.py`:
```python
MATERIALDB_ITEMS = [
    {"id": 11, "ktx_number": "40-1234", "trade_name": "Ultramid B3WG6", "grade": "black 00564",
     "manufacturer": "BASF", "family": "PA6", "classification": "series", "iso_designation": "PA6-GF30",
     "supplier": None},
    {"id": 12, "ktx_number": None, "trade_name": "REZYcom PA6 RB122 F15", "grade": None,
     "manufacturer": "Polykemi", "family": "PA6", "classification": "research", "iso_designation": "PA6-GF15",
     "supplier": None},
    {"id": 13, "ktx_number": "40-2002", "trade_name": "Hostacom TRC 787N", "grade": None,
     "manufacturer": "LyondellBasell", "family": "PP", "classification": "series", "iso_designation": "PP-TD20",
     "supplier": None},
]


@pytest_asyncio.fixture
async def materialdb(monkeypatch):
    """MaterialDB configured and answered by an in-process mock. Mutate
    state["items"] to change what MaterialDB returns, set state["fail"] to
    "down" (connection error) or "500" (error answer)."""
    import copy
    import httpx
    from app.services import materialdb_client

    settings = get_settings()
    monkeypatch.setattr(settings, "materialdb_base_url", "http://materialdb.test/")
    monkeypatch.setattr(settings, "materialdb_service_token", "svc-token")
    state = {"items": copy.deepcopy(MATERIALDB_ITEMS), "fail": None, "calls": 0, "auth": None, "url": None}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        state["auth"] = request.headers.get("authorization")
        state["url"] = str(request.url)
        if state["fail"] == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if state["fail"] == "500":
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json=state["items"])

    monkeypatch.setattr(materialdb_client, "TRANSPORT", httpx.MockTransport(handler))
    materialdb_client.clear_cache()
    yield state
    materialdb_client.clear_cache()
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_materialdb_search.py`:
```python
"""PLM proxies MaterialDB search: the browser never sees the service token."""
import pytest

from app.core.config import get_settings
from app.services import materialdb_client

pytestmark = pytest.mark.asyncio


async def test_search_matches_all_tokens_and_puts_series_first(client, eng_auth, materialdb):
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()] == [11, 12]
    assert r.json()[0] == {"id": 11, "ktx_number": "40-1234", "trade_name": "Ultramid B3WG6",
                           "grade": "black 00564", "manufacturer": "BASF", "family": "PA6",
                           "classification": "series", "label": "40-1234 Ultramid B3WG6 black 00564"}
    r = await client.get("/api/v1/materials/search", params={"q": "polykemi gf15"}, headers=eng_auth)
    assert [m["label"] for m in r.json()] == ["REZYcom PA6 RB122 F15 (research)"]
    r = await client.get("/api/v1/materials/search", params={"q": "40-20"}, headers=eng_auth)
    assert [m["id"] for m in r.json()] == [13]
    assert materialdb["auth"] == "Bearer svc-token"
    assert materialdb["url"] == "http://materialdb.test/v1/materials"


async def test_search_uses_the_cached_list(client, eng_auth, materialdb):
    await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    await client.get("/api/v1/materials/search", params={"q": "pp"}, headers=eng_auth)
    assert materialdb["calls"] == 1


async def test_short_query_returns_nothing_without_calling(client, eng_auth, materialdb):
    r = await client.get("/api/v1/materials/search", params={"q": " p "}, headers=eng_auth)
    assert r.json() == []
    assert materialdb["calls"] == 0


async def test_search_not_configured_is_503(client, eng_auth, monkeypatch):
    monkeypatch.setattr(get_settings(), "materialdb_base_url", "")
    materialdb_client.clear_cache()
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


async def test_search_unreachable_is_503(client, eng_auth, materialdb):
    materialdb["fail"] = "down"
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503
    assert "unreachable" in r.json()["detail"]


async def test_search_non_200_is_503(client, eng_auth, materialdb):
    materialdb["fail"] = "500"
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503
    assert "500" in r.json()["detail"]


async def test_search_garbage_payload_is_503(client, eng_auth, materialdb):
    materialdb["items"] = {"not": "a list"}
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503


async def test_find_by_id_and_label(materialdb):
    assert (await materialdb_client.find_by_id(12))["trade_name"] == "REZYcom PA6 RB122 F15"
    assert await materialdb_client.find_by_id(999) is None
    assert materialdb_client.label({"ktx_number": "40-1", "trade_name": " X ", "grade": None}) == "40-1 X"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_materialdb_search.py -n 0 -q`
Expected: FAIL (`ImportError: cannot import name 'materialdb_client'`).

- [ ] **Step 4: Add the settings**

In `backend/app/core/config.py`, after `hub_api_base: str = ""`:
```python
    # MaterialDB service API (read only for PLM). Base is the API root that
    # holds /v1: http://materialdb-backend:8000 inside the docker network, or
    # https://<hub>/materialdb/api through nginx. Token is MaterialDB's
    # MATERIALDB_SERVICE_TOKEN. Both empty = material search answers 503.
    materialdb_base_url: str = ""
    materialdb_service_token: str = ""
```

- [ ] **Step 5: Write the client**

`backend/app/services/materialdb_client.py`:
```python
"""Read-only client for the MaterialDB service API (bearer MATERIALDB_SERVICE_TOKEN).

MaterialDB offers machine callers only GET /v1/materials (the full list) and
GET /v1/materials/{ktx_number}; research materials have no KTX number. PLM
therefore keeps the full list for CACHE_SECONDS and searches and looks up by
id here, so the browser never sees the token."""
import time
from typing import Optional

import httpx

from app.core.config import get_settings

CACHE_SECONDS = 60.0
TIMEOUT_SECONDS = 8.0
SEARCH_FIELDS = ("ktx_number", "trade_name", "grade", "manufacturer", "family", "iso_designation", "supplier")
# Tests swap in httpx.MockTransport; None uses the network.
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None
_cache: dict = {"at": 0.0, "items": None}


class MaterialDbUnavailable(Exception):
    """Not configured, unreachable or answering with an error. The message is shown to the user."""


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["items"] = None


def label(m: dict) -> str:
    text = " ".join(str(m.get(k)).strip() for k in ("ktx_number", "trade_name", "grade")
                    if m.get(k) and str(m.get(k)).strip())
    return text if m.get("ktx_number") else f"{text} (research)"


def hit(m: dict) -> dict:
    return {"id": m.get("id"), "ktx_number": m.get("ktx_number"), "trade_name": m.get("trade_name"),
            "grade": m.get("grade"), "manufacturer": m.get("manufacturer"), "family": m.get("family"),
            "classification": m.get("classification"), "label": label(m)}


async def fetch_all(force: bool = False) -> list[dict]:
    settings = get_settings()
    base = settings.materialdb_base_url.strip().rstrip("/")
    if not base or not settings.materialdb_service_token:
        raise MaterialDbUnavailable(
            "MaterialDB is not configured on this PLM server (MATERIALDB_BASE_URL, MATERIALDB_SERVICE_TOKEN)")
    now = time.monotonic()
    if not force and _cache["items"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["items"]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=TRANSPORT) as client:
            resp = await client.get(f"{base}/v1/materials",
                                    headers={"Authorization": f"Bearer {settings.materialdb_service_token}"})
    except httpx.HTTPError as e:
        raise MaterialDbUnavailable(f"MaterialDB is unreachable ({type(e).__name__}); try again later") from e
    if resp.status_code != 200:
        raise MaterialDbUnavailable(f"MaterialDB answered {resp.status_code}; try again later")
    try:
        items = resp.json()
    except ValueError as e:
        raise MaterialDbUnavailable("MaterialDB answered with something that is not JSON") from e
    if not isinstance(items, list) or not all(isinstance(m, dict) and "id" in m for m in items):
        raise MaterialDbUnavailable("MaterialDB answered with an unexpected material list")
    _cache["at"] = now
    _cache["items"] = items
    return items


def _haystack(m: dict) -> str:
    return " ".join(str(m.get(k) or "") for k in SEARCH_FIELDS).lower()


async def search(q: str, limit: int = 20) -> list[dict]:
    tokens = (q or "").lower().split()
    if len("".join(tokens)) < 2:
        return []
    items = await fetch_all()
    found = [m for m in items if all(t in _haystack(m) for t in tokens)]
    found.sort(key=lambda m: (m.get("ktx_number") is None, m.get("ktx_number") or "",
                              str(m.get("trade_name") or "").lower()))
    return [hit(m) for m in found[:limit]]


async def find_by_id(material_id: int, force: bool = False) -> Optional[dict]:
    for m in await fetch_all(force=force):
        if m.get("id") == material_id:
            return m
    return None
```

- [ ] **Step 6: Write the search route**

`backend/app/api/v1/items/materials.py`:
```python
"""Material on articles: search MaterialDB through PLM (the service token
stays on the server), link a MaterialDB material, or mark it new."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.models import User
from app.services import materialdb_client
from app.services.materialdb_client import MaterialDbUnavailable

router = APIRouter(tags=["materials"])


def _unavailable(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.get("/materials/search", response_model=List[dict])
async def search_materials(q: str = Query("", max_length=100), current_user: User = Depends(get_current_user)):
    try:
        return await materialdb_client.search(q)
    except MaterialDbUnavailable as e:
        raise _unavailable(e)
```

In `backend/app/api/v1/__init__.py` add `from app.api.v1.items.materials import router as materials_router` next to the other items imports and `api_router.include_router(materials_router)` after the field notes include.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_materialdb_search.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/core/config.py backend/app/services/materialdb_client.py backend/app/api/v1/items/materials.py backend/app/api/v1/__init__.py backend/tests/conftest.py backend/tests/test_materialdb_search.py
git commit -m "feat(material): MaterialDB proxy search with a short cache, 503 when down

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Pick, new material, clear and refresh endpoints

**Files:**
- Create: `backend/app/services/part_material_service.py`
- Modify: `backend/app/api/v1/items/materials.py`
- Test: `backend/tests/test_part_material.py` (append)

**Interfaces:**
- Consumes: Task 3 columns, Task 4 `materialdb_client`, `ChangelogService.log_action`, `_part_in_org`.
- Produces:
  - `MATERIAL_ONLY_ON_ARTICLES = "Material applies to articles only"`
  - `class MaterialNotInDb(ValueError)`, `class MaterialGone(Exception)`
  - `material_text(part) -> str | None` (changelog and import display)
  - `PartMaterialService.link(session, part, materialdb_id, user_id)`, `.set_new(session, part, text, user_id)`, `.clear(session, part, user_id)`, `.refresh(session, part, user_id)`; all return the part and flush, the caller commits
  - Routes `PUT /api/v1/parts/{id}/material`, `POST /api/v1/parts/{id}/material/refresh`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_part_material.py`:
```python
async def _changelog(client, auth, pid):
    return [e for e in (await client.get(f"/api/v1/parts/{pid}/changelog", headers=auth)).json()
            if e["action"].startswith("material_")]


async def test_pick_from_materialdb_stores_id_number_and_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                         headers=eng_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["material_source"] == "materialdb"
    assert (body["materialdb_id"], body["material_ktx_number"]) == (11, "40-1234")
    assert body["material_label"] == "40-1234 Ultramid B3WG6 black 00564"
    assert body["material_synced_at"] is not None and body["material_new_text"] is None
    log = await _changelog(client, eng_auth, pid)
    assert [(e["action"], e["new_value"]) for e in log] == [("material_set", "40-1234 Ultramid B3WG6 black 00564")]


async def test_pick_research_material_without_number(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 12},
                         headers=eng_auth)
    assert r.json()["material_ktx_number"] is None
    assert r.json()["material_label"] == "REZYcom PA6 RB122 F15 (research)"


async def test_new_material_is_marked_new(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    r = await client.put(f"/api/v1/parts/{pid}/material",
                         json={"source": "new", "new_text": "  PA6-GF15 acc. VW 50125 "}, headers=eng_auth)
    body = r.json()
    assert body["material_source"] == "new"
    assert body["material_new_text"] == "PA6-GF15 acc. VW 50125"
    assert (body["materialdb_id"], body["material_ktx_number"], body["material_label"]) == (None, None, None)
    log = await _changelog(client, eng_auth, pid)
    assert log[-1]["old_value"] == "40-1234 Ultramid B3WG6 black 00564"
    assert log[-1]["new_value"] == "NEW (not in MaterialDB): PA6-GF15 acc. VW 50125"


async def test_new_material_needs_text_and_materialdb_needs_an_id(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    assert (await client.put(f"/api/v1/parts/{pid}/material", json={"source": "new", "new_text": "  "},
                             headers=eng_auth)).status_code == 422
    assert (await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb"},
                             headers=eng_auth)).status_code == 422


async def test_clear_material(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "new", "new_text": "PP"}, headers=eng_auth)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": None}, headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["material_source"] is None and r.json()["material_new_text"] is None


async def test_tools_have_no_material(client, eng_auth, seed, materialdb):
    tid = await _part(client, eng_auth, seed, "T-1", "tool")
    r = await client.put(f"/api/v1/parts/{tid}/material", json={"source": "new", "new_text": "PP"}, headers=eng_auth)
    assert r.status_code == 400
    assert r.json()["detail"] == "Material applies to articles only"


async def test_unknown_materialdb_id_is_400(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 999},
                         headers=eng_auth)
    assert r.status_code == 400
    assert "999" in r.json()["detail"]


async def test_pick_when_unreachable_is_503_and_part_unchanged(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "new", "new_text": "PP"}, headers=eng_auth)
    materialdb["fail"] = "down"
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                         headers=eng_auth)
    assert r.status_code == 503
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert (body["material_source"], body["material_new_text"]) == ("new", "PP")


async def test_refresh_rereads_the_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    materialdb["items"][0]["grade"] = "black 00564 UV"
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["material_label"] == "40-1234 Ultramid B3WG6 black 00564 UV"
    assert [e["action"] for e in await _changelog(client, eng_auth, pid)] == ["material_set", "material_refreshed"]


async def test_refresh_unreachable_keeps_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    materialdb["fail"] = "500"
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 503
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert body["material_label"] == "40-1234 Ultramid B3WG6 black 00564"


async def test_refresh_when_gone_is_409_and_keeps_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    materialdb["items"] = [m for m in materialdb["items"] if m["id"] != 11]
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 409
    assert "no longer in MaterialDB" in r.json()["detail"]
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert body["material_label"] == "40-1234 Ultramid B3WG6 black 00564"


async def test_refresh_of_unlinked_material_is_400(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_part_material.py -n 0 -q`
Expected: FAIL (405/404 on `/material`).

- [ ] **Step 3: Write the service**

`backend/app/services/part_material_service.py`:
```python
"""Material of an article: linked to MaterialDB or explicitly new. Every change
is logged on the part's changelog with the old and new display text."""
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part
from app.services import materialdb_client
from app.services.part_service import ChangelogService

MATERIAL_ONLY_ON_ARTICLES = "Material applies to articles only"
LABEL_MAX = 300


class MaterialNotInDb(ValueError):
    """The picked MaterialDB id does not exist (a 400)."""


class MaterialGone(Exception):
    """A linked material vanished from MaterialDB; the cached label stays (a 409)."""


def material_text(part: Part) -> Optional[str]:
    if part.material_source == "materialdb":
        return part.material_label or f"MaterialDB #{part.materialdb_id}"
    if part.material_source == "new":
        return f"NEW (not in MaterialDB): {part.material_new_text}"
    return None


def _check(part: Part) -> None:
    if part.item_category != "article":
        raise ValueError(MATERIAL_ONLY_ON_ARTICLES)


def _apply_link(part: Part, m: dict) -> None:
    part.material_source = "materialdb"
    part.materialdb_id = m["id"]
    part.material_ktx_number = m.get("ktx_number")
    part.material_label = materialdb_client.label(m)[:LABEL_MAX]
    part.material_synced_at = datetime.utcnow()
    part.material_new_text = None


async def _finish(session: AsyncSession, part: Part, old: Optional[str], user_id: int,
                  action: str = "material_set") -> Part:
    part.updated_by = user_id
    part.updated_at = datetime.utcnow()
    await session.flush()
    new = material_text(part)
    if old != new:
        await ChangelogService.log_action(
            session, part_id=part.id, action=action,
            action_description=f"Material: {old or 'none'} to {new or 'none'}",
            performed_by=user_id, field_name="part.material", old_value=old, new_value=new)
    return part


class PartMaterialService:

    @staticmethod
    async def link(session: AsyncSession, part: Part, materialdb_id: int, user_id: int) -> Part:
        _check(part)
        m = await materialdb_client.find_by_id(materialdb_id, force=True)
        if m is None:
            raise MaterialNotInDb(f"Material {materialdb_id} is not in MaterialDB")
        old = material_text(part)
        _apply_link(part, m)
        return await _finish(session, part, old, user_id)

    @staticmethod
    async def set_new(session: AsyncSession, part: Part, text: str, user_id: int) -> Part:
        _check(part)
        clean = (text or "").strip()
        if not clean:
            raise ValueError("Describe the new material")
        old = material_text(part)
        part.material_source = "new"
        part.material_new_text = clean[:500]
        part.materialdb_id = None
        part.material_ktx_number = None
        part.material_label = None
        part.material_synced_at = None
        return await _finish(session, part, old, user_id)

    @staticmethod
    async def clear(session: AsyncSession, part: Part, user_id: int) -> Part:
        _check(part)
        old = material_text(part)
        part.material_source = None
        part.material_new_text = None
        part.materialdb_id = None
        part.material_ktx_number = None
        part.material_label = None
        part.material_synced_at = None
        return await _finish(session, part, old, user_id)

    @staticmethod
    async def refresh(session: AsyncSession, part: Part, user_id: int) -> Part:
        _check(part)
        if part.material_source != "materialdb" or part.materialdb_id is None:
            raise ValueError("Only a material linked to MaterialDB can be refreshed")
        m = await materialdb_client.find_by_id(part.materialdb_id, force=True)
        if m is None:
            raise MaterialGone(f"{part.material_label or part.materialdb_id} is no longer in MaterialDB; "
                               "the saved label is kept")
        old = material_text(part)
        _apply_link(part, m)
        return await _finish(session, part, old, user_id, action="material_refreshed")
```

- [ ] **Step 4: Add the part routes**

Append to `backend/app/api/v1/items/materials.py` (and extend its imports):
```python
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _part_in_org
from app.models import get_db
from app.models.part import Part
from app.schemas.part import PartResponse
from app.services.part_material_service import MaterialGone, PartMaterialService


class MaterialIn(BaseModel):
    source: Optional[Literal["materialdb", "new"]] = None
    materialdb_id: Optional[int] = None
    new_text: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.source == "materialdb" and self.materialdb_id is None:
            raise ValueError("materialdb_id is required for a MaterialDB material")
        if self.source == "new" and not (self.new_text or "").strip():
            raise ValueError("Describe the new material")
        return self


async def _article(db: AsyncSession, part_id: int, user: User) -> Part:
    await _part_in_org(db, part_id, user.organization_id)
    return await db.get(Part, part_id)


@router.put("/parts/{part_id}/material", response_model=PartResponse)
async def put_part_material(part_id: int, body: MaterialIn, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    part = await _article(db, part_id, current_user)
    try:
        if body.source == "materialdb":
            await PartMaterialService.link(db, part, body.materialdb_id, current_user.id)
        elif body.source == "new":
            await PartMaterialService.set_new(db, part, body.new_text, current_user.id)
        else:
            await PartMaterialService.clear(db, part, current_user.id)
    except MaterialDbUnavailable as e:
        await db.rollback()
        raise _unavailable(e)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return part


@router.post("/parts/{part_id}/material/refresh", response_model=PartResponse)
async def refresh_part_material(part_id: int, current_user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    part = await _article(db, part_id, current_user)
    try:
        await PartMaterialService.refresh(db, part, current_user.id)
    except MaterialDbUnavailable as e:
        await db.rollback()
        raise _unavailable(e)
    except MaterialGone as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return part
```
Note: after `db.rollback()` the `part` object is expired; the 503 path does not return it, so no lazy load happens.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_part_material.py tests/test_materialdb_search.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/services/part_material_service.py backend/app/api/v1/items/materials.py backend/tests/test_part_material.py
git commit -m "feat(material): link a MaterialDB material, mark it new, clear, refresh

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Worksheet rows endpoint

**Files:**
- Create: `backend/app/services/worksheet_service.py`
- Create: `backend/app/api/v1/items/worksheet.py`
- Modify: `backend/app/api/v1/__init__.py`
- Test: `backend/tests/test_worksheet.py`

**Interfaces:**
- Consumes: Task 3 columns; `flow_state(topic, today)` from `app/services/dfm_service.py`; `DFM_PARTIES`, `DFM_TOPIC_OPEN` from `app/models/dfm.py`; `_project_in_org`.
- Produces: `worksheet_rows(session, project_id, today=None) -> dict`, `dfm_status(topics, today=None) -> dict`, `material_dict(part) -> dict`; route `GET /api/v1/projects/{project_id}/worksheet`; the `router` in `worksheet.py` that Task 7 extends.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_worksheet.py`:
```python
"""Worksheet rows: one per article with the producing tool, revision,
material, paint and DFM status; purchased and tool-only rows marked."""
from datetime import date, datetime

import pytest

from app.models.dfm import DfmEntry, DfmTopic
from app.models.paint import Paint, PartPaint, PartPaintLayer
from app.models.part import Part, PartRelation, PartRevision
from app.models.supplier import Supplier

pytestmark = pytest.mark.asyncio


async def _build(session_factory, seed):
    uid = seed["engineer_id"]
    async with session_factory() as s:
        def part(number, category="article", part_type="internal_mfg", **kw):
            p = Part(project_id=seed["project_id"], part_number=number, name=f"Name {number}",
                     part_type=part_type, item_category=category, created_by=uid, **kw)
            s.add(p)
            return p
        maker = Supplier(name="Formenbau Nord")
        s.add(maker)
        await s.flush()
        lh = part("20-1994-001-0", customer_part_number="206.882.251", tier1_part_number="S00H4X-110",
                  material_source="new", material_new_text="PA6-GF15 acc. VW 50125")
        rh = part("20-1994-002-0", customer_part_number="206.882.252")
        bought = part("20-1994-050-0", part_type="purchased")
        tool = part("199401", "tool", "purchased", tool_cavities=2, tool_cycle_time_s=55.0, toolmaker_id=maker.id)
        spare = part("199413", "tool", "purchased")
        gauge = part("1994-G1", "gauge", "purchased")
        await s.flush()
        rev = PartRevision(part_id=lh.id, revision_name="E1", phase="review", status="approved",
                           customer_index="001", created_by=uid)
        s.add(rev)
        await s.flush()
        lh.active_revision_id = rev.id
        s.add_all([
            PartRelation(from_part_id=tool.id, to_part_id=lh.id, relation_type="produces", created_by=uid),
            PartRelation(from_part_id=tool.id, to_part_id=rh.id, relation_type="produces", created_by=uid),
            PartRelation(from_part_id=rh.id, to_part_id=lh.id, relation_type="mirror_of", created_by=uid),
        ])
        paint = Paint(organization_id=seed["org_id"], name="Skyscraper base", colour_code="VM0",
                      colour_name="Skyscraper", colour_hex="#aab0b5", created_by=uid)
        s.add(paint)
        await s.flush()
        setup = PartPaint(part_id=rh.id, paint_required=True)
        s.add(setup)
        await s.flush()
        s.add(PartPaintLayer(part_paint_id=setup.id, paint_id=paint.id, layer_order=1))
        topic = DfmTopic(tool_part_id=tool.id, title="Gate position", opened_by=uid)
        s.add(topic)
        await s.flush()
        s.add(DfmEntry(topic_id=topic.id, party="toolmaker", addressed_to=["ktx"], kind="original",
                       recorded_by=uid, recorded_at=datetime(2026, 9, 20), sent_at=date(2026, 9, 20)))
        await s.commit()
        return {"lh": lh.id, "rh": rh.id, "bought": bought.id, "tool": tool.id, "spare": spare.id,
                "gauge": gauge.id, "maker": maker.id}


async def test_rows_carry_article_tool_revision_material_paint_and_dfm(client, eng_auth, seed, session_factory):
    ids = await _build(session_factory, seed)
    r = await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)
    assert r.status_code == 200, r.text
    rows = {row["part_id"]: row for row in r.json()["rows"]}
    assert set(rows) == {ids["lh"], ids["rh"], ids["bought"], ids["spare"]}  # no gauge, no producing tool row

    lh = rows[ids["lh"]]
    assert lh["row_kind"] == "article"
    assert (lh["customer_part_number"], lh["tier1_part_number"]) == ("206.882.251", "S00H4X-110")
    assert lh["revision"] == {"revision_name": "E1", "customer_index": "001", "phase": "review"}
    assert lh["material"]["material_source"] == "new"
    assert lh["material"]["material_new_text"] == "PA6-GF15 acc. VW 50125"
    assert lh["paint"] == {"painted": False, "colour": None, "colour_hex": None, "paint_system": None}
    assert lh["tool"] == {"part_id": ids["tool"], "part_number": "199401", "name": "Name 199401", "cavities": 2,
                          "toolmaker_id": ids["maker"], "toolmaker_name": "Formenbau Nord",
                          "cycle_time_s": 55.0, "tonnage_class": None}
    assert lh["dfm"] == {"status": "waiting", "waiting_on": ["ktx"], "open_topics": 1}
    assert lh["other_tools"] == []

    rh = rows[ids["rh"]]
    assert rh["mirror_of"] == {"part_id": ids["lh"], "part_number": "20-1994-001-0",
                               "customer_part_number": "206.882.251"}
    assert rh["paint"] == {"painted": True, "colour": "VM0 Skyscraper", "colour_hex": "#aab0b5",
                           "paint_system": "Skyscraper base"}
    assert rh["tool"]["part_id"] == ids["tool"]
    assert rh["revision"] is None

    assert rows[ids["bought"]]["row_kind"] == "purchased"
    assert rows[ids["bought"]]["tool"] is None and rows[ids["bought"]]["dfm"] is None
    spare = rows[ids["spare"]]
    assert spare["row_kind"] == "tool_only"
    assert spare["tool"]["part_id"] == ids["spare"]
    assert spare["dfm"] == {"status": "no_topic", "waiting_on": [], "open_topics": 0}


async def test_dfm_status_variants(session_factory, seed):
    from app.services.worksheet_service import dfm_status
    uid = seed["engineer_id"]
    t_all = DfmTopic(id=1, tool_part_id=1, title="a", status="open", opened_by=uid)
    t_all.entries = [
        DfmEntry(id=1, topic_id=1, party="toolmaker", addressed_to=["ktx"], kind="original",
                 recorded_by=uid, recorded_at=datetime(2026, 9, 1)),
        DfmEntry(id=2, topic_id=1, party="ktx", addressed_to=["toolmaker"], kind="answer", reply_to_id=1,
                 recorded_by=uid, recorded_at=datetime(2026, 9, 2)),
    ]
    t_empty = DfmTopic(id=2, tool_part_id=1, title="b", status="open", opened_by=uid)
    t_empty.entries = []
    t_done = DfmTopic(id=3, tool_part_id=1, title="c", status="finished_confirmed", opened_by=uid)
    t_done.entries = []
    assert dfm_status([]) == {"status": "no_topic", "waiting_on": [], "open_topics": 0}
    assert dfm_status([t_all])["status"] == "all_answered"
    assert dfm_status([t_all, t_empty]) == {"status": "open", "waiting_on": [], "open_topics": 2}
    assert dfm_status([t_done]) == {"status": "finished", "waiting_on": [], "open_topics": 0}


async def test_empty_project_and_other_org(client, eng_auth, seed, session_factory):
    r = await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)
    assert r.json() == {"project_id": seed["project_id"], "rows": []}
    r = await client.get("/api/v1/projects/999999/worksheet", headers=eng_auth)
    assert r.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_worksheet.py -n 0 -q`
Expected: FAIL (404 route, `ModuleNotFoundError` for `worksheet_service`).

- [ ] **Step 3: Write the service**

`backend/app/services/worksheet_service.py`:
```python
"""Rows for the project worksheet: one per article with the producing tool's
values, the active revision, material, paint and the tool's DFM status.
Optional rows: purchased articles and tools that produce no article of the
project. A fixed number of queries regardless of project size."""
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dfm import DFM_PARTIES, DFM_TOPIC_OPEN, DfmTopic
from app.models.paint import PartPaint
from app.models.part import Part, PartRelation, PartRevision
from app.models.supplier import Supplier
from app.services.dfm_service import flow_state


def material_dict(p: Part) -> dict:
    return {"material_source": p.material_source, "materialdb_id": p.materialdb_id,
            "material_ktx_number": p.material_ktx_number, "material_label": p.material_label,
            "material_new_text": p.material_new_text,
            "material_synced_at": p.material_synced_at.isoformat() if p.material_synced_at else None}


def dfm_status(topics: list, today: Optional[date] = None) -> dict:
    """no_topic | finished (every topic finished confirmed) | waiting (someone
    owes an answer) | all_answered (every open topic answered) | open."""
    if not topics:
        return {"status": "no_topic", "waiting_on": [], "open_topics": 0}
    open_topics = [t for t in topics if t.status == DFM_TOPIC_OPEN]
    if not open_topics:
        return {"status": "finished", "waiting_on": [], "open_topics": 0}
    waiting: set = set()
    all_answered = True
    for t in open_topics:
        flow = flow_state(t, today)
        waiting.update(w["party"] for w in flow["waiting_on"])
        all_answered = all_answered and flow["all_answered"]
    parties = [p for p in DFM_PARTIES if p in waiting]
    status = "waiting" if parties else ("all_answered" if all_answered else "open")
    return {"status": status, "waiting_on": parties, "open_topics": len(open_topics)}


def _paint(setup: Optional[PartPaint]) -> dict:
    if setup is None or not setup.paint_required:
        return {"painted": False, "colour": None, "colour_hex": None, "paint_system": None}
    layers = sorted(setup.layers, key=lambda layer: layer.layer_order)
    top = layers[0].paint if layers else None
    colour = " ".join(x for x in (top.colour_code, top.colour_name) if x) if top else ""
    return {"painted": True, "colour": colour or None, "colour_hex": top.colour_hex if top else None,
            "paint_system": " / ".join(layer.paint.name for layer in layers) or None}


def _tool(t: Part, toolmakers: dict) -> dict:
    return {"part_id": t.id, "part_number": t.part_number, "name": t.name, "cavities": t.tool_cavities,
            "toolmaker_id": t.toolmaker_id, "toolmaker_name": toolmakers.get(t.toolmaker_id),
            "cycle_time_s": t.tool_cycle_time_s, "tonnage_class": t.tool_tonnage_class}


def _identity(p: Part, kind: str) -> dict:
    return {"part_id": p.id, "row_kind": kind, "part_number": p.part_number,
            "customer_part_number": p.customer_part_number, "tier1_part_number": p.tier1_part_number,
            "name": p.name, "part_type": p.part_type, "item_category": p.item_category,
            "thumbnail_url": p.thumbnail_url, "lifecycle_phase": p.lifecycle_phase}


async def worksheet_rows(session: AsyncSession, project_id: int, today: Optional[date] = None) -> dict:
    parts = (await session.execute(
        select(Part).where(Part.project_id == project_id).order_by(Part.part_number))).scalars().all()
    if not parts:
        return {"project_id": project_id, "rows": []}
    by_id = {p.id: p for p in parts}
    articles = [p for p in parts if p.item_category == "article"]
    tools = {p.id: p for p in parts if p.item_category == "tool"}

    rels = (await session.execute(select(PartRelation).where(
        PartRelation.from_part_id.in_(list(by_id)),
        PartRelation.relation_type.in_(("produces", "mirror_of"))))).scalars().all()
    rev_ids = [a.active_revision_id for a in articles if a.active_revision_id]
    revs = {r.id: r for r in (await session.execute(
        select(PartRevision).where(PartRevision.id.in_(rev_ids)))).scalars().all()} if rev_ids else {}
    article_ids = [a.id for a in articles]
    paints = {s.part_id: s for s in (await session.execute(
        select(PartPaint).where(PartPaint.part_id.in_(article_ids)))).scalars().all()} if article_ids else {}
    maker_ids = {t.toolmaker_id for t in tools.values() if t.toolmaker_id}
    toolmakers = dict((await session.execute(
        select(Supplier.id, Supplier.name).where(Supplier.id.in_(maker_ids)))).all()) if maker_ids else {}
    topics_by_tool: dict = defaultdict(list)
    if tools:
        for t in (await session.execute(
                select(DfmTopic).where(DfmTopic.tool_part_id.in_(list(tools))))).scalars().all():
            topics_by_tool[t.tool_part_id].append(t)

    tools_of: dict = defaultdict(list)
    producing: set = set()
    mirror_of: dict = {}
    for r in rels:
        src, dst = by_id.get(r.from_part_id), by_id.get(r.to_part_id)
        if src is None or dst is None:
            continue  # relation into another project
        if r.relation_type == "produces" and src.id in tools and dst.item_category == "article":
            tools_of[dst.id].append(src)
            producing.add(src.id)
        elif r.relation_type == "mirror_of":
            mirror_of[src.id] = {"part_id": dst.id, "part_number": dst.part_number,
                                 "customer_part_number": dst.customer_part_number}

    rows = []
    for a in articles:
        made_by = sorted(tools_of.get(a.id, []), key=lambda t: t.part_number)
        tool = made_by[0] if made_by else None
        rev = revs.get(a.active_revision_id)
        rows.append({
            **_identity(a, "purchased" if a.part_type == "purchased" else "article"),
            "mirror_of": mirror_of.get(a.id),
            "revision": {"revision_name": rev.revision_name, "customer_index": rev.customer_index,
                         "phase": rev.phase.value if hasattr(rev.phase, "value") else rev.phase} if rev else None,
            "material": material_dict(a),
            "paint": _paint(paints.get(a.id)),
            "tool": _tool(tool, toolmakers) if tool else None,
            "other_tools": [t.part_number for t in made_by[1:]],
            "dfm": dfm_status(topics_by_tool.get(tool.id, []), today) if tool else None,
        })
    for t in tools.values():
        if t.id in producing:
            continue
        rows.append({**_identity(t, "tool_only"), "mirror_of": None, "revision": None,
                     "material": material_dict(t), "paint": _paint(None), "tool": _tool(t, toolmakers),
                     "other_tools": [], "dfm": dfm_status(topics_by_tool.get(t.id, []), today)})
    return {"project_id": project_id, "rows": rows}
```

- [ ] **Step 4: Write the router**

`backend/app/api/v1/items/worksheet.py`:
```python
"""The project worksheet: rows (one per article with its tool) and the xlsx
export of what the browser shows. Org scoping as in part_paint.py."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.worksheet_service import worksheet_rows

router = APIRouter(tags=["worksheet"])


@router.get("/projects/{project_id}/worksheet", response_model=dict)
async def get_worksheet(project_id: int, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    return await worksheet_rows(db, project_id)
```
Register in `backend/app/api/v1/__init__.py`: `from app.api.v1.items.worksheet import router as worksheet_router` and `api_router.include_router(worksheet_router)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_worksheet.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/services/worksheet_service.py backend/app/api/v1/items/worksheet.py backend/app/api/v1/__init__.py backend/tests/test_worksheet.py
git commit -m "feat(worksheet): project worksheet rows with tool, revision, material, paint, DFM

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Worksheet xlsx export endpoint

**Files:**
- Create: `backend/app/services/worksheet_export.py`
- Modify: `backend/app/api/v1/items/worksheet.py`
- Test: `backend/tests/test_worksheet_export.py`

**Interfaces:**
- Produces: `build_xlsx(columns: list[dict], rows: list[list[dict]], frozen_columns: int, sheet_title: str) -> bytes`, `FLAG_FILLS`, `XLSX_MEDIA_TYPE`; route `POST /api/v1/projects/{project_id}/worksheet/export`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_worksheet_export.py`:
```python
"""xlsx export of the visible worksheet: typed numbers and dates, flag colours,
frozen identity columns, formula-like text kept as text."""
from datetime import date, datetime
from io import BytesIO

import openpyxl
import pytest

pytestmark = pytest.mark.asyncio

PAYLOAD = {
    "columns": [
        {"key": "part.part_number", "label": "KTX no.", "type": "text"},
        {"key": "part.customer_part_number", "label": "OEM no.", "type": "text"},
        {"key": "tool.cavities", "label": "Cavities", "type": "number"},
        {"key": "tool.cycle_time_s", "label": "Cycle time (s)", "type": "number"},
        {"key": "notes.summary", "label": "Notes", "type": "text"},
        {"key": "part.material_synced", "label": "Synced", "type": "date"},
    ],
    "rows": [
        {"cells": [{"value": "20-1994-001-0", "flag": None, "comments": 0},
                   {"value": "206.882.251", "flag": "confirmed", "comments": 0},
                   {"value": 2, "flag": "open", "comments": 1},
                   {"value": "55.5", "flag": None, "comments": 0},
                   {"value": "=1+1", "flag": "rejected", "comments": 2},
                   {"value": "2026-09-24T10:00:00", "flag": None, "comments": 0}]},
        {"cells": [{"value": "20-1994-002-0"}, {"value": None}, {"value": None},
                   {"value": "n/a"}, {"value": ""}, {"value": "not a date"}]},
    ],
    "frozen_columns": 2,
}


async def _export(client, auth, project_id, payload=PAYLOAD):
    return await client.post(f"/api/v1/projects/{project_id}/worksheet/export", json=payload, headers=auth)


async def test_export_writes_typed_cells_and_flag_colours(client, eng_auth, seed):
    r = await _export(client, eng_auth, seed["project_id"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    today = date.today().isoformat()
    assert r.headers["content-disposition"] == f'attachment; filename="proj-worksheet-{today}.xlsx"'
    ws = openpyxl.load_workbook(BytesIO(r.content)).active
    assert [c.value for c in ws[1]] == ["KTX no.", "OEM no.", "Cavities", "Cycle time (s)", "Notes", "Synced"]
    assert ws["C2"].value == 2 and isinstance(ws["C2"].value, int)
    assert ws["D2"].value == 55.5
    assert isinstance(ws["F2"].value, datetime) and ws["F2"].value.date() == date(2026, 9, 24)
    assert ws["B2"].fill.fgColor.rgb == "FFC6EFCE"
    assert ws["C2"].fill.fgColor.rgb == "FFFFFF00"
    assert ws["E2"].fill.fgColor.rgb == "FFF8CBAD"
    assert ws["C2"].comment is not None and "1 comment" in ws["C2"].comment.text
    assert ws["D3"].value == "n/a"            # a number column keeps unparsable text
    assert ws["F3"].value == "not a date"
    assert ws["B3"].value is None
    assert ws.freeze_panes == "C2"
    assert ws.auto_filter.ref == "A1:F3"


async def test_export_keeps_formula_like_text_as_text(client, eng_auth, seed):
    r = await _export(client, eng_auth, seed["project_id"])
    ws = openpyxl.load_workbook(BytesIO(r.content)).active
    assert ws["E2"].value == "=1+1"
    assert ws["E2"].data_type == "s"


async def test_export_rejects_ragged_rows_and_foreign_projects(client, eng_auth, seed):
    bad = {**PAYLOAD, "rows": [{"cells": [{"value": "x"}]}]}
    assert (await _export(client, eng_auth, seed["project_id"], bad)).status_code == 422
    assert (await _export(client, eng_auth, 999999)).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_worksheet_export.py -n 0 -q`
Expected: FAIL (405 on the export route).

- [ ] **Step 3: Write the xlsx builder**

`backend/app/services/worksheet_export.py`:
```python
"""xlsx of the worksheet as the browser shows it: visible columns and rows in
order, numbers and dates typed, flagged cells in the engineering Excel's
colours, the identity columns and header frozen. Text is never a formula."""
from datetime import date, datetime
from io import BytesIO
from typing import Optional

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FLAG_FILLS = {"open": "FFFFFF00", "confirmed": "FFC6EFCE", "rejected": "FFF8CBAD"}
HEADER_FILL = "FF305496"


def _number(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip().replace(",", "."))
    except ValueError:
        return str(v)
    return int(f) if f.is_integer() else f


def _date(v):
    try:
        return datetime.fromisoformat(str(v).strip()[:19])
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(str(v).strip()[:10]), datetime.min.time())
        except ValueError:
            return str(v)


def _typed(kind: str, v):
    if v is None or v == "":
        return None
    if kind == "number":
        return _number(v)
    if kind == "date":
        return _date(v)
    return str(v)


def build_xlsx(columns: list[dict], rows: list[list[dict]], frozen_columns: int,
               sheet_title: str = "Worksheet") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31] or "Worksheet"
    ws.append([c["label"] for c in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
    widths = [len(c["label"]) for c in columns]
    for i, cells in enumerate(rows, start=2):
        for j, (col, data) in enumerate(zip(columns, cells), start=1):
            value = _typed(col.get("type", "text"), data.get("value"))
            cell = ws.cell(row=i, column=j, value=value)
            if isinstance(value, str) and value.startswith("="):
                cell.data_type = "s"  # literal text, never a formula
            if isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd"
            flag: Optional[str] = data.get("flag")
            if flag in FLAG_FILLS:
                cell.fill = PatternFill("solid", fgColor=FLAG_FILLS[flag])
            n = int(data.get("comments") or 0)
            if n > 0:
                cell.comment = Comment(f"{n} comment{'s' if n != 1 else ''} in PLM", "PLM")
            widths[j - 1] = max(widths[j - 1], min(len(str(value)) if value is not None else 0, 60))
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = max(8, w + 2)
    ws.freeze_panes = f"{get_column_letter(frozen_columns + 1)}2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Add the export route**

Extend `backend/app/api/v1/items/worksheet.py` (imports at top, route at the end):
```python
import re
from datetime import date
from typing import List, Literal, Optional, Union

from fastapi import Response
from pydantic import BaseModel, Field, model_validator

from app.models.entities import Project
from app.services.worksheet_export import XLSX_MEDIA_TYPE, build_xlsx


class ExportColumn(BaseModel):
    key: str = Field(..., max_length=64)
    label: str = Field(..., max_length=100)
    type: Literal["text", "number", "date"] = "text"


class ExportCell(BaseModel):
    value: Union[int, float, str, None] = None
    flag: Optional[Literal["open", "confirmed", "rejected"]] = None
    comments: int = Field(0, ge=0)


class ExportRow(BaseModel):
    cells: List[ExportCell]


class ExportIn(BaseModel):
    columns: List[ExportColumn] = Field(..., min_length=1, max_length=60)
    rows: List[ExportRow] = Field(default_factory=list, max_length=5000)
    frozen_columns: int = Field(0, ge=0, le=10)

    @model_validator(mode="after")
    def _rectangular(self):
        n = len(self.columns)
        if any(len(r.cells) != n for r in self.rows):
            raise ValueError(f"every row needs exactly {n} cells, one per column")
        return self


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "project"


@router.post("/projects/{project_id}/worksheet/export")
async def export_worksheet(project_id: int, body: ExportIn, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    project = await db.get(Project, project_id)
    code = _safe(project.code)
    data = build_xlsx([c.model_dump() for c in body.columns],
                      [[cell.model_dump() for cell in r.cells] for r in body.rows],
                      body.frozen_columns, sheet_title=f"{code} worksheet")
    filename = f"{code}-worksheet-{date.today().isoformat()}.xlsx"
    return Response(content=data, media_type=XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_worksheet_export.py tests/test_worksheet.py -n 0 -q`
Expected: all PASS. If `ws["C2"].value` loads as a float, check `_number` keeps JSON ints as `int` (pydantic `Union[int, float, str, None]` keeps `2` an int in smart mode).

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/app/services/worksheet_export.py backend/app/api/v1/items/worksheet.py backend/tests/test_worksheet_export.py
git commit -m "feat(worksheet): typed xlsx export with flag colours and frozen identity columns

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Frontend api modules and query hooks

**Files:**
- Create: `frontend/src/api/fieldNotes.ts`, `frontend/src/api/materials.ts`, `frontend/src/api/worksheet.ts`
- Create: `frontend/src/hooks/queries/useFieldNotes.ts`, `frontend/src/hooks/queries/useWorksheet.ts`
- Create: `frontend/src/lib/fieldNotes.ts`, `frontend/src/lib/material.ts`
- Test: `frontend/src/api/fieldNotes.test.ts`, `frontend/src/lib/fieldNotes.test.ts`, `frontend/src/lib/material.test.ts`

**Interfaces:**
- Produces (exact names later tasks use):
  - `api/fieldNotes.ts`: types `FieldFlag`, `FieldNoteComment`, `FieldNoteSummary`, `FieldNoteThread`; `listPartFieldNotes(partId)`, `getFieldNoteThread(partId, fieldKey)`, `addFieldComment(partId, fieldKey, body)`, `setFieldFlag(partId, fieldKey, status)`, `listProjectFieldNotes(projectId)`
  - `api/materials.ts`: types `MaterialHit`, `MaterialSource`, `PartMaterial`, `MaterialInput`; `searchMaterials(q)`, `setPartMaterial(partId, input)`, `refreshPartMaterial(partId)`, `materialDbUrl(id)`
  - `api/worksheet.ts`: types `WorksheetTool`, `WorksheetDfm`, `DfmSheetStatus`, `WorksheetPaint`, `WorksheetRowKind`, `WorksheetRow`, `Worksheet`, `WorksheetExportColumn`, `WorksheetExportCell`, `WorksheetExportPayload`; `getWorksheet(projectId)`, `downloadWorksheetXlsx(projectId, payload)`
  - `hooks/queries/useFieldNotes.ts`: `FIELD_NOTES_KEY`, `usePartFieldNotes(partId)`, `usePartFieldNoteIndex(partId): Map<string, FieldNoteSummary>`, `useProjectFieldNotes(projectId)`, `useFieldNoteThread(partId, fieldKey, enabled)`, `useFieldNoteActions(partId, fieldKey): { addComment, setFlag }`
  - `hooks/queries/useWorksheet.ts`: `WORKSHEET_KEY`, `useWorksheet(projectId)`
  - `lib/fieldNotes.ts`: `FLAGS`, `FLAG_LABELS`, `FLAG_DOT`, `FLAG_TINT`, `FLAG_BUTTON`, `flagTint(flag)`, `noteKey(partId, fieldKey)`, `indexByField(notes)`, `FIELD_KEY_RE`, `popoverPosition(rect, viewport, size?)`
  - `lib/material.ts`: `materialOf(part)`, `materialText(m)`, `NEW_MATERIAL_BADGE`

- [ ] **Step 1: Write the failing tests**

`frontend/src/api/fieldNotes.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { addFieldComment, getFieldNoteThread, listProjectFieldNotes, setFieldFlag } from './fieldNotes'
import { downloadWorksheetXlsx, getWorksheet } from './worksheet'
import { searchMaterials, setPartMaterial, refreshPartMaterial, materialDbUrl } from './materials'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('./client', () => ({ default: clientMocks, API_BASE_URL: '' }))

describe('field notes, material and worksheet api', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockResolvedValue({ data: [] })
    clientMocks.post.mockResolvedValue({ data: {} })
    clientMocks.put.mockResolvedValue({ data: {} })
  })

  it('calls the field note routes with the key in the path', async () => {
    await getFieldNoteThread(7, 'tool.cavities')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities')
    await addFieldComment(7, 'tool.cavities', 'Excel says 4')
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/comments', { body: 'Excel says 4' })
    await setFieldFlag(7, 'tool.cavities', null)
    expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/flag', { status: null })
    await listProjectFieldNotes(35)
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/35/field-notes')
  })

  it('calls the material and worksheet routes', async () => {
    await searchMaterials('pa6')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/materials/search', { params: { q: 'pa6' } })
    await setPartMaterial(5, { source: 'new', new_text: 'PP' })
    expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5/material', { source: 'new', new_text: 'PP' })
    await refreshPartMaterial(5)
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/5/material/refresh')
    expect(materialDbUrl(11)).toBe('/materialdb/materials/11')
    await getWorksheet(35)
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/35/worksheet')
  })

  it('downloads the export under the server file name', async () => {
    const click = vi.fn()
    const anchor = { click, href: '', download: '' } as unknown as HTMLAnchorElement
    const create = vi.spyOn(document, 'createElement').mockReturnValue(anchor)
    const url = vi.fn(() => 'blob:x')
    const revoke = vi.fn()
    Object.assign(URL, { createObjectURL: url, revokeObjectURL: revoke })
    clientMocks.post.mockResolvedValue({ data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="1994-worksheet-2026-09-24.xlsx"' } })
    const payload = { columns: [{ key: 'part.part_number', label: 'KTX no.', type: 'text' as const }], rows: [], frozen_columns: 1 }
    await downloadWorksheetXlsx(35, payload)
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/projects/35/worksheet/export', payload, { responseType: 'blob' })
    expect(anchor.download).toBe('1994-worksheet-2026-09-24.xlsx')
    expect(click).toHaveBeenCalled()
    expect(revoke).toHaveBeenCalledWith('blob:x')
    create.mockRestore()
  })
})
```

`frontend/src/lib/fieldNotes.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { FIELD_KEY_RE, flagTint, indexByField, noteKey, popoverPosition } from './fieldNotes'
import type { FieldNoteSummary } from '../api/fieldNotes'

const note = (field_key: string, flag_status: FieldNoteSummary['flag_status'] = null): FieldNoteSummary => ({
  id: 1, part_id: 7, field_key, flag_status, flag_set_by: null, flag_set_by_name: null, flag_set_at: null,
  created_at: '2026-09-24T10:00:00', comment_count: 0, last_comment: null,
})

describe('field note helpers', () => {
  it('indexes notes by field key and builds part keys', () => {
    const idx = indexByField([note('tool.cavities', 'open'), note('part.name')])
    expect(idx.get('tool.cavities')?.flag_status).toBe('open')
    expect(indexByField(undefined).size).toBe(0)
    expect(noteKey(7, 'tool.cavities')).toBe('7:tool.cavities')
  })

  it('tints by flag and nothing without one', () => {
    expect(flagTint('open')).toContain('yellow')
    expect(flagTint('confirmed')).toContain('emerald')
    expect(flagTint('rejected')).toContain('red')
    expect(flagTint(null)).toBe('')
  })

  it('accepts only registry style keys', () => {
    expect(FIELD_KEY_RE.test('tool.cavities')).toBe(true)
    expect(FIELD_KEY_RE.test('Tool.cavities')).toBe(false)
    expect(FIELD_KEY_RE.test('x"]')).toBe(false)
  })

  it('keeps the popover inside the viewport', () => {
    expect(popoverPosition({ top: 100, bottom: 120, left: 50, right: 60 }, { width: 1200, height: 800 })).toEqual({ top: 124, left: 50 })
    // near the bottom: opens above the anchor
    expect(popoverPosition({ top: 700, bottom: 720, left: 50, right: 60 }, { width: 1200, height: 800 }).top).toBe(700 - 360 - 4)
    // near the right edge: shifted left
    expect(popoverPosition({ top: 100, bottom: 120, left: 1150, right: 1160 }, { width: 1200, height: 800 }).left).toBe(1200 - 320 - 8)
  })
})
```

`frontend/src/lib/material.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { materialOf, materialText } from './material'

describe('material helpers', () => {
  it('reads the material fields of a part, missing fields as null', () => {
    expect(materialOf({})).toEqual({ material_source: null, materialdb_id: null, material_ktx_number: null,
      material_label: null, material_new_text: null, material_synced_at: null })
  })

  it('shows linked, new and missing material as text', () => {
    expect(materialText({ ...materialOf({}), material_source: 'materialdb', materialdb_id: 11, material_label: '40-1234 Ultramid B3WG6' })).toBe('40-1234 Ultramid B3WG6')
    expect(materialText({ ...materialOf({}), material_source: 'materialdb', materialdb_id: 11 })).toBe('MaterialDB #11')
    expect(materialText({ ...materialOf({}), material_source: 'new', material_new_text: 'PA6-GF15' })).toBe('PA6-GF15 (NEW, not in MaterialDB)')
    expect(materialText(materialOf({}))).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/api/fieldNotes.test.ts src/lib/fieldNotes.test.ts src/lib/material.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the api modules**

`frontend/src/api/fieldNotes.ts`:
```ts
/**
 * Field notes: comments and a flag per field of a part (article or tool).
 * Mirrors backend/app/api/v1/items/field_notes.py.
 */
import client from './client';

export type FieldFlag = 'open' | 'confirmed' | 'rejected';

export interface FieldNoteComment {
  id: number;
  body: string;
  author_id: number;
  author_name: string | null;
  created_at: string;
}

export interface FieldNoteSummary {
  id: number;
  part_id: number;
  field_key: string;
  flag_status: FieldFlag | null;
  flag_set_by: number | null;
  flag_set_by_name: string | null;
  flag_set_at: string | null;
  created_at: string | null;
  comment_count: number;
  last_comment: FieldNoteComment | null;
}

export interface FieldNoteThread extends Omit<FieldNoteSummary, 'id'> {
  id: number | null;
  comments: FieldNoteComment[];
}

const base = (partId: number, fieldKey: string) => `/v1/parts/${partId}/field-notes/${encodeURIComponent(fieldKey)}`;

export const listPartFieldNotes = async (partId: number): Promise<FieldNoteSummary[]> =>
  (await client.get(`/v1/parts/${partId}/field-notes`)).data;

export const getFieldNoteThread = async (partId: number, fieldKey: string): Promise<FieldNoteThread> =>
  (await client.get(base(partId, fieldKey))).data;

export const addFieldComment = async (partId: number, fieldKey: string, body: string): Promise<FieldNoteThread> =>
  (await client.post(`${base(partId, fieldKey)}/comments`, { body })).data;

export const setFieldFlag = async (partId: number, fieldKey: string, status: FieldFlag | null): Promise<FieldNoteThread> =>
  (await client.put(`${base(partId, fieldKey)}/flag`, { status })).data;

export const listProjectFieldNotes = async (projectId: number): Promise<FieldNoteSummary[]> =>
  (await client.get(`/v1/projects/${projectId}/field-notes`)).data;
```

`frontend/src/api/materials.ts`:
```ts
/**
 * Material on the article: MaterialDB search (proxied by the PLM backend, the
 * service token never reaches the browser), link, new material, refresh.
 * Mirrors backend/app/api/v1/items/materials.py.
 */
import client from './client';

export type MaterialSource = 'materialdb' | 'new';

export interface MaterialHit {
  id: number;
  ktx_number: string | null;
  trade_name: string;
  grade: string | null;
  manufacturer: string | null;
  family: string | null;
  classification: string | null;
  label: string;
}

export interface PartMaterial {
  material_source: MaterialSource | null;
  materialdb_id: number | null;
  material_ktx_number: string | null;
  material_label: string | null;
  material_new_text: string | null;
  material_synced_at: string | null;
}

export type MaterialInput =
  | { source: 'materialdb'; materialdb_id: number }
  | { source: 'new'; new_text: string }
  | { source: null };

export const MATERIALDB_UI_BASE = '/materialdb/materials';

export function materialDbUrl(id: number): string {
  return `${MATERIALDB_UI_BASE}/${id}`;
}

export const searchMaterials = async (q: string): Promise<MaterialHit[]> =>
  (await client.get('/v1/materials/search', { params: { q } })).data;

export const setPartMaterial = async (partId: number, input: MaterialInput): Promise<PartMaterial> =>
  (await client.put(`/v1/parts/${partId}/material`, input)).data;

export const refreshPartMaterial = async (partId: number): Promise<PartMaterial> =>
  (await client.post(`/v1/parts/${partId}/material/refresh`)).data;
```

`frontend/src/api/worksheet.ts`:
```ts
/**
 * Project worksheet rows and the xlsx export. Mirrors
 * backend/app/api/v1/items/worksheet.py.
 */
import client from './client';
import type { DfmParty } from './dfm';
import type { FieldFlag } from './fieldNotes';
import type { PartMaterial } from './materials';

export interface WorksheetTool {
  part_id: number;
  part_number: string;
  name: string;
  cavities: number | null;
  toolmaker_id: number | null;
  toolmaker_name: string | null;
  cycle_time_s: number | null;
  tonnage_class: number | null;
}

export type DfmSheetStatus = 'no_topic' | 'waiting' | 'all_answered' | 'open' | 'finished';

export interface WorksheetDfm {
  status: DfmSheetStatus;
  waiting_on: DfmParty[];
  open_topics: number;
}

export interface WorksheetPaint {
  painted: boolean;
  colour: string | null;
  colour_hex: string | null;
  paint_system: string | null;
}

export type WorksheetRowKind = 'article' | 'purchased' | 'tool_only';

export interface WorksheetRow {
  part_id: number;
  row_kind: WorksheetRowKind;
  part_number: string;
  customer_part_number: string | null;
  tier1_part_number: string | null;
  name: string;
  part_type: string;
  item_category: string;
  thumbnail_url: string | null;
  lifecycle_phase: string;
  mirror_of: { part_id: number; part_number: string; customer_part_number: string | null } | null;
  revision: { revision_name: string; customer_index: string | null; phase: string } | null;
  material: PartMaterial;
  paint: WorksheetPaint;
  tool: WorksheetTool | null;
  other_tools: string[];
  dfm: WorksheetDfm | null;
}

export interface Worksheet {
  project_id: number;
  rows: WorksheetRow[];
}

export interface WorksheetExportColumn {
  key: string;
  label: string;
  type: 'text' | 'number' | 'date';
}

export interface WorksheetExportCell {
  value: string | number | null;
  flag: FieldFlag | null;
  comments: number;
}

export interface WorksheetExportPayload {
  columns: WorksheetExportColumn[];
  rows: { cells: WorksheetExportCell[] }[];
  frozen_columns: number;
}

export const getWorksheet = async (projectId: number): Promise<Worksheet> =>
  (await client.get(`/v1/projects/${projectId}/worksheet`)).data;

function filenameFrom(disposition: string | undefined, fallback: string): string {
  const m = /filename="?([^";]+)"?/i.exec(disposition ?? '');
  return m ? m[1] : fallback;
}

export async function downloadWorksheetXlsx(projectId: number, payload: WorksheetExportPayload): Promise<void> {
  const res = await client.post(`/v1/projects/${projectId}/worksheet/export`, payload, { responseType: 'blob' });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filenameFrom(res.headers?.['content-disposition'] as string | undefined, `worksheet-${projectId}.xlsx`);
  a.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Write the lib helpers**

`frontend/src/lib/fieldNotes.ts`:
```ts
/** Flag colours, lookup keys and popover placement for field notes. */
import type { FieldFlag, FieldNoteSummary } from '../api/fieldNotes';

export const FLAGS: FieldFlag[] = ['open', 'confirmed', 'rejected'];
export const FLAG_LABELS: Record<FieldFlag, string> = { open: 'Open', confirmed: 'Confirmed', rejected: 'Rejected' };
export const FLAG_DOT: Record<FieldFlag, string> = { open: 'bg-yellow-400', confirmed: 'bg-emerald-500', rejected: 'bg-red-500' };
export const FLAG_TINT: Record<FieldFlag, string> = { open: 'bg-yellow-500/20', confirmed: 'bg-emerald-500/20', rejected: 'bg-red-500/25' };
export const FLAG_BUTTON: Record<FieldFlag, string> = {
  open: 'border-yellow-400 bg-yellow-500/20 text-yellow-200',
  confirmed: 'border-emerald-500 bg-emerald-500/20 text-emerald-200',
  rejected: 'border-red-500 bg-red-500/20 text-red-200',
};

/** Same rule as the backend (field_note_service.FIELD_KEY_RE). */
export const FIELD_KEY_RE = /^[a-z][a-z0-9_]{0,30}\.[a-z][a-z0-9_]{0,30}$/;

export function flagTint(flag: FieldFlag | null | undefined): string {
  return flag ? FLAG_TINT[flag] : '';
}

export function noteKey(partId: number, fieldKey: string): string {
  return `${partId}:${fieldKey}`;
}

export function indexByField(notes: FieldNoteSummary[] | undefined): Map<string, FieldNoteSummary> {
  const map = new Map<string, FieldNoteSummary>();
  for (const n of notes ?? []) map.set(n.field_key, n);
  return map;
}

export const POPOVER_SIZE = { width: 320, height: 360 };

/** Below the anchor, above it when there is no room, never past the right edge. */
export function popoverPosition(
  rect: { top: number; bottom: number; left: number; right: number },
  viewport: { width: number; height: number },
  size: { width: number; height: number } = POPOVER_SIZE,
): { top: number; left: number } {
  let top = rect.bottom + 4;
  if (top + size.height > viewport.height) top = Math.max(4, rect.top - size.height - 4);
  const left = Math.max(8, Math.min(rect.left, viewport.width - size.width - 8));
  return { top, left };
}
```

`frontend/src/lib/material.ts`:
```ts
/** Material display rules shared by the article page and the worksheet. */
import type { PartMaterial } from '../api/materials';

export const NEW_MATERIAL_BADGE = 'NEW, not in MaterialDB';

export function materialOf(part: Partial<PartMaterial>): PartMaterial {
  return {
    material_source: part.material_source ?? null,
    materialdb_id: part.materialdb_id ?? null,
    material_ktx_number: part.material_ktx_number ?? null,
    material_label: part.material_label ?? null,
    material_new_text: part.material_new_text ?? null,
    material_synced_at: part.material_synced_at ?? null,
  };
}

/** Plain text for filtering, sorting and the export. */
export function materialText(m: PartMaterial): string | null {
  if (m.material_source === 'materialdb') return m.material_label ?? `MaterialDB #${m.materialdb_id}`;
  if (m.material_source === 'new') return `${m.material_new_text ?? ''} (${NEW_MATERIAL_BADGE})`;
  return null;
}
```

- [ ] **Step 5: Write the hooks**

`frontend/src/hooks/queries/useFieldNotes.ts`:
```ts
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  addFieldComment, getFieldNoteThread, listPartFieldNotes, listProjectFieldNotes, setFieldFlag,
  type FieldFlag, type FieldNoteSummary,
} from '../../api/fieldNotes';
import { apiErrorMessage } from '../../lib/apiError';
import { indexByField } from '../../lib/fieldNotes';

/** Every field note query starts with this key, so one invalidation refreshes markers everywhere. */
export const FIELD_NOTES_KEY = 'field-notes';

export function usePartFieldNotes(partId: number | null | undefined) {
  return useQuery({
    queryKey: [FIELD_NOTES_KEY, 'part', partId],
    queryFn: () => listPartFieldNotes(partId as number),
    enabled: !!partId,
  });
}

export function usePartFieldNoteIndex(partId: number | null | undefined): Map<string, FieldNoteSummary> {
  const { data } = usePartFieldNotes(partId);
  return useMemo(() => indexByField(Array.isArray(data) ? data : []), [data]);
}

export function useProjectFieldNotes(projectId: number) {
  return useQuery({
    queryKey: [FIELD_NOTES_KEY, 'project', projectId],
    queryFn: () => listProjectFieldNotes(projectId),
    enabled: !!projectId,
  });
}

export function useFieldNoteThread(partId: number, fieldKey: string, enabled: boolean) {
  return useQuery({
    queryKey: [FIELD_NOTES_KEY, 'thread', partId, fieldKey],
    queryFn: () => getFieldNoteThread(partId, fieldKey),
    enabled,
  });
}

export function useFieldNoteActions(partId: number, fieldKey: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: [FIELD_NOTES_KEY] });
  const addComment = useMutation({
    mutationFn: (body: string) => addFieldComment(partId, fieldKey, body),
    onSuccess: refresh,
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not add the comment')),
  });
  const setFlag = useMutation({
    mutationFn: (status: FieldFlag | null) => setFieldFlag(partId, fieldKey, status),
    onSuccess: refresh,
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not set the flag')),
  });
  return { addComment, setFlag };
}
```

`frontend/src/hooks/queries/useWorksheet.ts`:
```ts
import { useQuery } from '@tanstack/react-query';
import { getWorksheet } from '../../api/worksheet';

export const WORKSHEET_KEY = 'worksheet';

export function useWorksheet(projectId: number) {
  return useQuery({
    queryKey: [WORKSHEET_KEY, projectId],
    queryFn: () => getWorksheet(projectId),
    enabled: !!projectId,
  });
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/api/fieldNotes.test.ts src/lib/fieldNotes.test.ts src/lib/material.test.ts && npx tsc --noEmit`
Expected: PASS, tsc clean.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/api/fieldNotes.ts frontend/src/api/materials.ts frontend/src/api/worksheet.ts frontend/src/api/fieldNotes.test.ts frontend/src/hooks/queries/useFieldNotes.ts frontend/src/hooks/queries/useWorksheet.ts frontend/src/lib/fieldNotes.ts frontend/src/lib/fieldNotes.test.ts frontend/src/lib/material.ts frontend/src/lib/material.test.ts
git commit -m "feat(ui): api modules and hooks for field notes, material and worksheet

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: FieldNoteMarker and popover

**Files:**
- Create: `frontend/src/components/fieldNotes/FieldNotePopover.tsx`
- Create: `frontend/src/components/fieldNotes/FieldNoteMarker.tsx`
- Test: `frontend/src/components/fieldNotes/FieldNoteMarker.test.tsx`

**Interfaces:**
- Consumes: Task 8 hooks and `lib/fieldNotes.ts`.
- Produces: `FieldNoteMarker` props `{ partId: number; fieldKey: string; label: string; note?: FieldNoteSummary; open?: boolean; onOpenChange?(open: boolean): void; quietWhenEmpty?: boolean }`. Test ids: `note-marker-<fieldKey>`, `note-dot-<fieldKey>`, `note-count-<fieldKey>`, `note-popover-<fieldKey>`, `flag-open|confirmed|rejected`, `flag-clear`, `note-comment-input`, `note-comment-add`, `note-comments`. The marker button carries `data-note-marker`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/fieldNotes/FieldNoteMarker.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FieldNoteMarker from './FieldNoteMarker'
import type { FieldNoteSummary } from '../../api/fieldNotes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const comment = { id: 1, body: 'Excel BOM says 4 cavities', author_id: 2, author_name: 'Engineer', created_at: '2026-09-24T10:12:00' }
const note: FieldNoteSummary = {
  id: 3, part_id: 7, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: 2, flag_set_by_name: 'Engineer',
  flag_set_at: '2026-09-24T10:12:00', created_at: '2026-09-24T10:11:00', comment_count: 1, last_comment: comment,
}

function mount(props: Partial<React.ComponentProps<typeof FieldNoteMarker>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  render(<QueryClientProvider client={qc}><FieldNoteMarker partId={7} fieldKey="tool.cavities" label="Cavities" {...props} /></QueryClientProvider>)
  return { invalidate }
}

describe('FieldNoteMarker', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockResolvedValue({ data: { ...note, comments: [comment] } })
    clientMocks.post.mockResolvedValue({ data: {} })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows the flag colour and the comment count', () => {
    mount({ note })
    expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('bg-yellow-400')
    expect(screen.getByTestId('note-count-tool.cavities').textContent).toBe('1')
  })

  it('shows an empty ring and no count without a note', () => {
    mount()
    expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('border')
    expect(screen.queryByTestId('note-count-tool.cavities')).toBeNull()
  })

  it('opens the thread, adds a comment and refreshes every field note query', async () => {
    const { invalidate } = mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    expect(await screen.findByText('Excel BOM says 4 cavities')).toBeTruthy()
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities')
    fireEvent.change(screen.getByTestId('note-comment-input'), { target: { value: '  PLM 2 is the sold state  ' } })
    fireEvent.click(screen.getByTestId('note-comment-add'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/comments', { body: 'PLM 2 is the sold state' }))
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['field-notes'] }))
  })

  it('sets and clears the flag', async () => {
    mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    await screen.findByText('Excel BOM says 4 cavities')
    expect(screen.getByTestId('flag-open').getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByTestId('flag-confirmed'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/flag', { status: 'confirmed' }))
    fireEvent.click(screen.getByTestId('flag-clear'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/flag', { status: null }))
  })

  it('can be opened from outside and closes on Escape', async () => {
    const onOpenChange = vi.fn()
    mount({ note, open: true, onOpenChange })
    expect(await screen.findByTestId('note-popover-tool.cavities')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('does not send an empty comment', async () => {
    mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    await screen.findByText('Excel BOM says 4 cavities')
    fireEvent.change(screen.getByTestId('note-comment-input'), { target: { value: '   ' } })
    expect((screen.getByTestId('note-comment-add') as HTMLButtonElement).disabled).toBe(true)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/fieldNotes/FieldNoteMarker.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the popover**

`frontend/src/components/fieldNotes/FieldNotePopover.tsx`:
```tsx
/**
 * FieldNotePopover - the comment thread and flag of one field, opened from a
 * FieldNoteMarker. Comments are append only; the flag is open, confirmed,
 * rejected or cleared.
 */
import { useEffect, useRef, useState } from 'react';
import { useFieldNoteActions, useFieldNoteThread } from '../../hooks/queries/useFieldNotes';
import { FLAG_BUTTON, FLAG_LABELS, FLAGS } from '../../lib/fieldNotes';

export interface FieldNotePopoverProps {
  partId: number;
  fieldKey: string;
  label: string;
  position: { top: number; left: number };
  onClose(): void;
}

export default function FieldNotePopover({ partId, fieldKey, label, position, onClose }: FieldNotePopoverProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState('');
  const { data: thread, isLoading } = useFieldNoteThread(partId, fieldKey, true);
  const { addComment, setFlag } = useFieldNoteActions(partId, fieldKey);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (ref.current?.contains(target)) return;
      if (target?.closest?.('[data-note-marker]')) return; // the marker toggles itself
      onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const submit = () => {
    const body = draft.trim();
    if (!body) return;
    addComment.mutate(body, { onSuccess: () => setDraft('') });
  };
  const current = thread?.flag_status ?? null;
  const comments = thread?.comments ?? [];

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={`Notes on ${label}`}
      data-testid={`note-popover-${fieldKey}`}
      style={{ top: position.top, left: position.left }}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
      className="fixed z-50 w-80 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-3 text-sm text-left font-normal normal-case"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-slate-100">{label}</span>
        <button type="button" aria-label="Close" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-lg leading-none">×</button>
      </div>
      <div className="flex flex-wrap gap-1 mb-1">
        {FLAGS.map((f) => (
          <button
            key={f}
            type="button"
            data-testid={`flag-${f}`}
            aria-pressed={current === f}
            disabled={setFlag.isPending}
            onClick={() => setFlag.mutate(f)}
            className={`px-2 py-0.5 rounded text-xs border ${current === f ? FLAG_BUTTON[f] : 'border-slate-600 text-slate-300 hover:bg-slate-700'}`}
          >
            {FLAG_LABELS[f]}
          </button>
        ))}
        <button
          type="button"
          data-testid="flag-clear"
          disabled={!current || setFlag.isPending}
          onClick={() => setFlag.mutate(null)}
          className="px-2 py-0.5 rounded text-xs border border-slate-600 text-slate-400 hover:bg-slate-700 disabled:opacity-40"
        >
          Clear flag
        </button>
      </div>
      {current && thread?.flag_set_by_name && (
        <p className="text-[11px] text-slate-500 mb-2">
          {FLAG_LABELS[current]} by {thread.flag_set_by_name}{thread.flag_set_at ? `, ${thread.flag_set_at.slice(0, 10)}` : ''}
        </p>
      )}
      <div data-testid="note-comments" className="max-h-56 overflow-y-auto space-y-2 my-2">
        {isLoading ? (
          <p className="text-slate-500">Loading...</p>
        ) : comments.length === 0 ? (
          <p className="text-slate-500">No comments yet</p>
        ) : (
          comments.map((c) => (
            <div key={c.id} className="bg-slate-900/60 rounded px-2 py-1">
              <div className="text-[11px] text-slate-500">{c.author_name ?? 'Unknown'}, {c.created_at.slice(0, 16).replace('T', ' ')}</div>
              <div className="text-slate-200 whitespace-pre-wrap break-words">{c.body}</div>
            </div>
          ))
        )}
      </div>
      <textarea
        aria-label="New comment"
        data-testid="note-comment-input"
        value={draft}
        rows={2}
        placeholder="Add a comment (Ctrl+Enter to add)"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(); }}
        className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 placeholder-slate-500"
      />
      <div className="flex justify-end mt-1">
        <button
          type="button"
          data-testid="note-comment-add"
          disabled={!draft.trim() || addComment.isPending}
          onClick={submit}
          className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs"
        >
          Add comment
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Write the marker**

`frontend/src/components/fieldNotes/FieldNoteMarker.tsx`:
```tsx
/**
 * FieldNoteMarker - a dot coloured by the field's flag and a speech bubble
 * count of its comments, next to any value. Click opens the thread popover.
 * The same (part, field) key is used in the worksheet and on the article,
 * tool and paint pages, so a flag set in one place shows in the other.
 */
import { useLayoutEffect, useRef, useState } from 'react';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import { FLAG_DOT, FLAG_LABELS, popoverPosition } from '../../lib/fieldNotes';
import FieldNotePopover from './FieldNotePopover';

export interface FieldNoteMarkerProps {
  partId: number;
  fieldKey: string;
  label: string;
  note?: FieldNoteSummary;
  /** Controlled open state (the worksheet's "Comment" menu item); omit for self-managed. */
  open?: boolean;
  onOpenChange?(open: boolean): void;
  /** Hidden until hover or focus while the field has no comment and no flag (worksheet cells). */
  quietWhenEmpty?: boolean;
}

export default function FieldNoteMarker({
  partId, fieldKey, label, note, open, onOpenChange, quietWhenEmpty = false,
}: FieldNoteMarkerProps) {
  const button = useRef<HTMLButtonElement>(null);
  const [ownOpen, setOwnOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const isOpen = open ?? ownOpen;
  const setOpen = (next: boolean) => {
    if (open === undefined) setOwnOpen(next);
    onOpenChange?.(next);
  };

  useLayoutEffect(() => {
    if (!isOpen || !button.current) return;
    setPosition(popoverPosition(button.current.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }));
  }, [isOpen]);

  const flag = note?.flag_status ?? null;
  const count = note?.comment_count ?? 0;
  const empty = !flag && count === 0;
  const title = [flag ? FLAG_LABELS[flag] : null, count ? `${count} comment${count === 1 ? '' : 's'}` : null]
    .filter(Boolean).join(', ') || 'Comment or flag';

  return (
    <>
      <button
        ref={button}
        type="button"
        data-note-marker=""
        data-testid={`note-marker-${fieldKey}`}
        aria-label={`Comments and flag: ${label}`}
        aria-expanded={isOpen}
        title={title}
        onClick={(e) => { e.stopPropagation(); setOpen(!isOpen); }}
        className={`inline-flex items-center gap-0.5 align-middle ml-1 text-[10px] leading-none text-slate-400 hover:text-slate-100 ${
          quietWhenEmpty && empty && !isOpen ? 'opacity-0 group-hover:opacity-100 focus:opacity-100' : ''
        }`}
      >
        <span data-testid={`note-dot-${fieldKey}`} className={`inline-block w-2 h-2 rounded-full ${flag ? FLAG_DOT[flag] : 'border border-slate-500'}`} />
        {count > 0 && (
          <span data-testid={`note-count-${fieldKey}`} className="inline-flex items-center gap-px">
            <svg aria-hidden="true" viewBox="0 0 16 16" className="w-3 h-3" fill="currentColor"><path d="M2 3h12v8H6l-3 3v-3H2z" /></svg>
            {count}
          </span>
        )}
      </button>
      {isOpen && position && (
        <FieldNotePopover partId={partId} fieldKey={fieldKey} label={label} position={position} onClose={() => setOpen(false)} />
      )}
    </>
  );
}
```
Note: the count span's `textContent` must be exactly the number (the svg has no text), which the test asserts.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/fieldNotes/FieldNoteMarker.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/components/fieldNotes
git commit -m "feat(ui): field note marker with comment thread and flag popover

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Material field on the article page

**Files:**
- Create: `frontend/src/components/materials/MaterialValue.tsx`
- Create: `frontend/src/components/materials/MaterialField.tsx`
- Modify: `frontend/src/pages/PartDetail.tsx` (the `Part` interface and the "Part Information" card)
- Test: `frontend/src/components/materials/MaterialField.test.tsx`

**Interfaces:**
- Consumes: `api/materials.ts`, `lib/material.ts`.
- Produces: `MaterialValue` props `{ material: PartMaterial; testId?: string }` (link test id `<testId>`, new badge test id `<testId>-new`); `MaterialField` props `{ partId: number; material: PartMaterial }`. Test ids: `material-value`, `material-value-new`, `material-change`, `material-mode-search`, `material-mode-new`, `material-search-input`, `material-hit-<id>`, `material-search-error`, `material-new-input`, `material-new-save`, `material-clear`, `material-refresh`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/materials/MaterialField.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MaterialField from './MaterialField'
import { materialOf } from '../../lib/material'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const hits = [{ id: 11, ktx_number: '40-1234', trade_name: 'Ultramid B3WG6', grade: 'black 00564', manufacturer: 'BASF',
  family: 'PA6', classification: 'series', label: '40-1234 Ultramid B3WG6 black 00564' }]

function mount(material = materialOf({})) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MaterialField partId={5} material={material} /></QueryClientProvider>)
}

describe('MaterialField', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockResolvedValue({ data: hits })
    clientMocks.put.mockResolvedValue({ data: {} })
    clientMocks.post.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows a linked material as a MaterialDB link', () => {
    mount({ ...materialOf({}), material_source: 'materialdb', materialdb_id: 11, material_label: '40-1234 Ultramid B3WG6 black 00564' })
    const link = screen.getByTestId('material-value') as HTMLAnchorElement
    expect(link.textContent).toBe('40-1234 Ultramid B3WG6 black 00564')
    expect(link.getAttribute('href')).toBe('/materialdb/materials/11')
    expect(screen.getByTestId('material-refresh')).toBeTruthy()
  })

  it('marks a new material clearly', () => {
    mount({ ...materialOf({}), material_source: 'new', material_new_text: 'PA6-GF15 acc. VW 50125' })
    expect(screen.getByTestId('material-value').textContent).toContain('PA6-GF15 acc. VW 50125')
    expect(screen.getByTestId('material-value-new').textContent).toBe('NEW, not in MaterialDB')
  })

  it('searches MaterialDB and links the pick', async () => {
    mount()
    fireEvent.click(screen.getByTestId('material-change'))
    fireEvent.change(screen.getByTestId('material-search-input'), { target: { value: 'ultramid' } })
    fireEvent.click(await screen.findByTestId('material-hit-11', {}, { timeout: 2000 }))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/materials/search', { params: { q: 'ultramid' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5/material', { source: 'materialdb', materialdb_id: 11 }))
  })

  it('saves a new material that is not in MaterialDB', async () => {
    mount()
    fireEvent.click(screen.getByTestId('material-change'))
    fireEvent.click(screen.getByTestId('material-mode-new'))
    fireEvent.change(screen.getByTestId('material-new-input'), { target: { value: ' PP-TD20 ' } })
    fireEvent.click(screen.getByTestId('material-new-save'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5/material', { source: 'new', new_text: 'PP-TD20' }))
  })

  it('says clearly when MaterialDB is not reachable', async () => {
    clientMocks.get.mockRejectedValue({ response: { status: 503, data: { detail: 'MaterialDB is unreachable (ConnectError); try again later' } } })
    mount()
    fireEvent.click(screen.getByTestId('material-change'))
    fireEvent.change(screen.getByTestId('material-search-input'), { target: { value: 'ultramid' } })
    expect((await screen.findByTestId('material-search-error', {}, { timeout: 2000 })).textContent).toContain('MaterialDB is unreachable')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/materials/MaterialField.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Write MaterialValue**

`frontend/src/components/materials/MaterialValue.tsx`:
```tsx
/** A material as shown on the article and in the worksheet: a MaterialDB link, or the text with a NEW badge. */
import { materialDbUrl, type PartMaterial } from '../../api/materials';
import { NEW_MATERIAL_BADGE } from '../../lib/material';

export default function MaterialValue({ material, testId }: { material: PartMaterial; testId?: string }) {
  if (material.material_source === 'materialdb' && material.materialdb_id != null) {
    return (
      <a data-testid={testId} href={materialDbUrl(material.materialdb_id)} target="_blank" rel="noreferrer"
        title="Open in MaterialDB" className="text-sky-300 hover:underline">
        {material.material_label ?? `MaterialDB #${material.materialdb_id}`}
      </a>
    );
  }
  if (material.material_source === 'new') {
    return (
      <span data-testid={testId} className="inline-flex items-center gap-1.5">
        <span className="text-slate-100">{material.material_new_text}</span>
        <span data-testid={testId ? `${testId}-new` : undefined}
          className="px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-300 text-[10px] font-semibold uppercase whitespace-nowrap">
          {NEW_MATERIAL_BADGE}
        </span>
      </span>
    );
  }
  return <span data-testid={testId} className="text-slate-500">not set</span>;
}
```

- [ ] **Step 4: Write MaterialField**

`frontend/src/components/materials/MaterialField.tsx`:
```tsx
/**
 * MaterialField - the article's material: picked from MaterialDB (the PLM
 * backend proxies the search) or explicitly new, not in MaterialDB yet.
 * Creating materials happens in MaterialDB, never here.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { refreshPartMaterial, searchMaterials, setPartMaterial, type MaterialInput, type PartMaterial } from '../../api/materials';
import { WORKSHEET_KEY } from '../../hooks/queries/useWorksheet';
import { apiErrorMessage } from '../../lib/apiError';
import MaterialValue from './MaterialValue';

type Mode = 'view' | 'search' | 'new';

export default function MaterialField({ partId, material }: { partId: number; material: PartMaterial }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>('view');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [newText, setNewText] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const search = useQuery({
    queryKey: ['materialdb-search', debounced],
    queryFn: () => searchMaterials(debounced),
    enabled: mode === 'search' && debounced.length >= 2,
    retry: false,
  });

  const refetchPart = () => {
    qc.invalidateQueries({ queryKey: ['part', String(partId)] });
    qc.invalidateQueries({ queryKey: [WORKSHEET_KEY] });
  };
  const save = useMutation({
    mutationFn: (input: MaterialInput) => setPartMaterial(partId, input),
    onSuccess: () => {
      toast.success('Material saved');
      setMode('view');
      setQuery('');
      setNewText('');
      refetchPart();
    },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not save the material')),
  });
  const refresh = useMutation({
    mutationFn: () => refreshPartMaterial(partId),
    onSuccess: () => { toast.success('Material refreshed from MaterialDB'); refetchPart(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not refresh from MaterialDB')),
  });

  const tab = (m: Mode, label: string, testId: string) => (
    <button type="button" data-testid={testId} aria-pressed={mode === m} onClick={() => setMode(m)}
      className={`px-2 py-0.5 rounded text-xs ${mode === m ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}>
      {label}
    </button>
  );

  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <MaterialValue material={material} testId="material-value" />
        {mode === 'view' && (
          <button type="button" data-testid="material-change" onClick={() => setMode('search')}
            className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200">
            {material.material_source ? 'Change' : '+ set'}
          </button>
        )}
        {mode === 'view' && material.material_source === 'materialdb' && (
          <button type="button" data-testid="material-refresh" disabled={refresh.isPending} onClick={() => refresh.mutate()}
            title="Read the label again from MaterialDB"
            className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-50">Refresh</button>
        )}
      </div>

      {mode !== 'view' && (
        <div className="mt-2 p-3 bg-slate-900 border border-slate-700 rounded space-y-2">
          <div className="flex gap-1">
            {tab('search', 'From MaterialDB', 'material-mode-search')}
            {tab('new', 'New material, not in MaterialDB', 'material-mode-new')}
          </div>
          {mode === 'search' ? (
            <div>
              <input data-testid="material-search-input" autoFocus type="search" value={query}
                placeholder="KTX number, trade name, grade, manufacturer"
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-500" />
              {search.isError && (
                <p data-testid="material-search-error" className="text-amber-300 text-xs mt-1">
                  {apiErrorMessage(search.error, 'MaterialDB search failed')}
                </p>
              )}
              {search.data && search.data.length === 0 && <p className="text-slate-500 text-xs mt-1">No material matches</p>}
              <div className="mt-1 max-h-48 overflow-y-auto">
                {search.data?.map((m) => (
                  <button key={m.id} type="button" data-testid={`material-hit-${m.id}`} disabled={save.isPending}
                    onClick={() => save.mutate({ source: 'materialdb', materialdb_id: m.id })}
                    className="block w-full text-left px-2 py-1 rounded text-sm text-slate-100 hover:bg-slate-700">
                    {m.label}
                    <span className="text-slate-500 text-xs"> {[m.manufacturer, m.family].filter(Boolean).join(', ')}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <input data-testid="material-new-input" autoFocus value={newText} maxLength={500}
                placeholder="e.g. PA6-GF15 acc. VW 50125"
                onChange={(e) => setNewText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && newText.trim()) save.mutate({ source: 'new', new_text: newText.trim() }); }}
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-500" />
              <button type="button" data-testid="material-new-save" disabled={!newText.trim() || save.isPending}
                onClick={() => save.mutate({ source: 'new', new_text: newText.trim() })}
                className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
            </div>
          )}
          <div className="flex justify-between">
            {material.material_source ? (
              <button type="button" data-testid="material-clear" disabled={save.isPending} onClick={() => save.mutate({ source: null })}
                className="text-xs text-red-300 hover:text-red-200">Remove material</button>
            ) : <span />}
            <button type="button" onClick={() => setMode('view')} className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Put the field on the article page**

In `frontend/src/pages/PartDetail.tsx`:
- import `MaterialField from '../components/materials/MaterialField'`, `{ materialOf } from '../lib/material'` and `type { PartMaterial } from '../api/materials'`;
- change `interface Part {` to `interface Part extends Partial<PartMaterial> {`;
- in the "Part Information" card, after the Classification cell inside the `grid grid-cols-2 gap-4` div, add:
```tsx
            <div className="col-span-2" data-field-key="part.material">
              <div className="text-sm text-slate-400">Material</div>
              <MaterialField partId={part.id} material={materialOf(part)} />
            </div>
```
(Task 11 adds the marker next to the "Material" label.)

- [ ] **Step 6: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/materials src/pages/PartDetail.test.tsx src/pages/PartDetail.tool.test.tsx src/pages/PartDetail.files.test.tsx`
Expected: PASS (the existing PartDetail tests keep passing; their part mock has no material fields, `materialOf` fills nulls).

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/components/materials frontend/src/pages/PartDetail.tsx
git commit -m "feat(ui): material field on the article, MaterialDB link or NEW badge

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Field markers and focus highlight on article, tool and paint

The worksheet's Edit navigates to `/parts/<id>?focus=<field_key>`. The part page finds `[data-field-key="<field_key>"]`, scrolls it into view, rings it for 2.5 s and focuses its first control. Each field the registry lists gets a `data-field-key` wrapper and a `FieldNoteMarker`.

Field keys placed here (same strings as the registry in Task 12): article page `part.part_number`, `part.customer_part_number`, `part.tier1_part_number`, `part.name`, `part.part_type`, `part.lifecycle_phase`, `part.material`, `revision.level`; paint card `paint.painted`, `paint.colour`; tool page `tool.number`, `tool.cavities`, `tool.tonnage_class`, `tool.cycle_time_s`, `tool.toolmaker`, `dfm.status`.

**Files:**
- Create: `frontend/src/hooks/useFieldFocus.ts`
- Modify: `frontend/src/pages/PartDetail.tsx`, `frontend/src/pages/ToolDetail.tsx`, `frontend/src/components/tools/ToolFieldsCard.tsx`, `frontend/src/components/paint/PartPaintCard.tsx`
- Test: `frontend/src/hooks/useFieldFocus.test.ts`, `frontend/src/pages/PartDetail.fieldNotes.test.tsx`, append to `frontend/src/components/tools/ToolFieldsCard.test.tsx`

**Interfaces:**
- Consumes: `FieldNoteMarker` (Task 9), `usePartFieldNoteIndex` (Task 8), `FIELD_KEY_RE`.
- Produces: `FOCUS_PARAM = 'focus'`, `FOCUS_HIGHLIGHT`, `FOCUS_HIGHLIGHT_MS`, `focusField(fieldKey, doc?) -> boolean`, `useFieldFocus(ready: boolean)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/hooks/useFieldFocus.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { FOCUS_HIGHLIGHT, focusField } from './useFieldFocus'

describe('focusField', () => {
  afterEach(() => { document.body.innerHTML = ''; vi.useRealTimers() })

  it('rings the field, focuses its control (not the marker) and removes the ring later', () => {
    vi.useFakeTimers()
    document.body.innerHTML = `<div data-field-key="tool.cavities"><button data-note-marker="">m</button><button id="edit">4</button></div>`
    const el = document.querySelector<HTMLElement>('[data-field-key="tool.cavities"]')!
    el.scrollIntoView = vi.fn()
    expect(focusField('tool.cavities')).toBe(true)
    expect(el.classList.contains(FOCUS_HIGHLIGHT[0])).toBe(true)
    expect(document.activeElement?.id).toBe('edit')
    vi.advanceTimersByTime(3000)
    expect(el.classList.contains(FOCUS_HIGHLIGHT[0])).toBe(false)
  })

  it('ignores unknown and malformed keys', () => {
    document.body.innerHTML = `<div data-field-key="part.name"></div>`
    expect(focusField('part.material')).toBe(false)
    expect(focusField('x"] , body')).toBe(false)
  })
})
```

`frontend/src/pages/PartDetail.fieldNotes.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PartDetail from './PartDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/changes/StartChangeModal', () => stub('start-change'))
vi.mock('../components/changes/StartChangeButton', () => stub('start-change-button'))
vi.mock('../components/parts/RevisionTimeline', () => stub('timeline'))
vi.mock('../components/parts/CustomerDataDialog', () => stub('customer-data'))
vi.mock('../components/parts/CustomerPackageDialog', () => stub('customer-package'))
vi.mock('../components/parts/BomTree', () => stub('bom-tree'))
vi.mock('../components/dfm/DfmArchive', () => stub('dfm-archive'))

const article = { id: 5, part_number: '20-1994-005-0', customer_part_number: '206.887.233', tier1_part_number: 'S00H54-110',
  name: 'ISOFIX Cover', part_type: 'internal_mfg', data_classification: 'confidential', item_category: 'article',
  project_id: 2, active_revision_id: null, lifecycle_phase: 'rfq', revisions: [],
  material_source: 'new', material_new_text: 'PA6-GF15 acc. VW 50125' }
const tool = { ...article, id: 9, part_number: '199403', item_category: 'tool', tool_cavities: 4, material_source: null }
const note = (part_id: number, field_key: string, flag_status: string | null, comment_count = 0) => ({
  id: part_id * 100, part_id, field_key, flag_status, flag_set_by: null, flag_set_by_name: null, flag_set_at: null,
  created_at: null, comment_count, last_comment: null })

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/parts/:partId" element={<PartDetail />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('PartDetail field notes', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: article })
      if (url === '/v1/parts/9') return Promise.resolve({ data: tool })
      if (url === '/v1/parts/5/field-notes') return Promise.resolve({ data: [note(5, 'part.material', 'rejected', 2), note(5, 'paint.colour', 'confirmed')] })
      if (url === '/v1/parts/9/field-notes') return Promise.resolve({ data: [note(9, 'tool.cavities', 'open', 1)] })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows worksheet flags next to the article and paint fields', async () => {
    renderAt('/parts/5')
    await waitFor(() => expect(screen.getByTestId('note-dot-part.material').className).toContain('bg-red-500'))
    expect(screen.getByTestId('note-count-part.material').textContent).toBe('2')
    // the paint card renders after its own query
    await waitFor(() => expect(screen.getByTestId('note-dot-paint.colour').className).toContain('bg-emerald-500'))
    for (const key of ['part.part_number', 'part.customer_part_number', 'part.tier1_part_number', 'part.name',
      'part.part_type', 'part.lifecycle_phase', 'revision.level', 'paint.painted']) {
      expect(screen.getByTestId(`note-marker-${key}`)).toBeTruthy()
    }
  })

  it('highlights the field named by ?focus=', async () => {
    renderAt('/parts/5?focus=part.material')
    await waitFor(() => expect(document.querySelector('[data-field-key="part.material"]')!.className).toContain('ring-2'))
  })

  it('shows the tool flags on the tool page', async () => {
    renderAt('/parts/9?focus=tool.cavities')
    await waitFor(() => expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('bg-yellow-400'))
    for (const key of ['tool.number', 'tool.tonnage_class', 'tool.cycle_time_s', 'tool.toolmaker', 'dfm.status']) {
      expect(screen.getByTestId(`note-marker-${key}`)).toBeTruthy()
    }
    await waitFor(() => expect(document.querySelector('[data-field-key="tool.cavities"]')!.className).toContain('ring-2'))
  })
})
```

Append to `frontend/src/components/tools/ToolFieldsCard.test.tsx` inside the `describe`:
```tsx
  it('puts a note marker on every tool field', async () => {
    clientMocks.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/v1/parts/7/field-notes'
      ? [{ id: 1, part_id: 7, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null, flag_set_by_name: null,
          flag_set_at: null, created_at: null, comment_count: 0, last_comment: null }]
      : [{ id: 3, name: 'Toolshop Sued' }] }))
    wrap()
    await waitFor(() => expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('bg-yellow-400'))
    for (const key of ['tool.tonnage_class', 'tool.cycle_time_s', 'tool.toolmaker']) {
      expect(screen.getByTestId(`note-marker-${key}`)).toBeTruthy()
    }
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/hooks/useFieldFocus.test.ts src/pages/PartDetail.fieldNotes.test.tsx src/components/tools/ToolFieldsCard.test.tsx`
Expected: FAIL (hook module missing, markers missing).

- [ ] **Step 3: Write the focus hook**

`frontend/src/hooks/useFieldFocus.ts`:
```ts
/**
 * ?focus=<field_key> on a part page: scroll to the element carrying
 * data-field-key, ring it for a moment and focus its first control. The
 * worksheet's "Edit" navigates here. Sections load at different times (paint,
 * tool relations), so the lookup retries for up to two seconds.
 */
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FIELD_KEY_RE } from '../lib/fieldNotes';

export const FOCUS_PARAM = 'focus';
export const FOCUS_HIGHLIGHT = ['ring-2', 'ring-amber-400', 'ring-offset-2', 'ring-offset-slate-900', 'rounded'];
export const FOCUS_HIGHLIGHT_MS = 2500;
const RETRY_MS = 100;
const RETRIES = 20;

export function focusField(fieldKey: string, doc: Document = document): boolean {
  if (!FIELD_KEY_RE.test(fieldKey)) return false;
  const el = doc.querySelector<HTMLElement>(`[data-field-key="${fieldKey}"]`);
  if (!el) return false;
  el.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  el.classList.add(...FOCUS_HIGHLIGHT);
  window.setTimeout(() => el.classList.remove(...FOCUS_HIGHLIGHT), FOCUS_HIGHLIGHT_MS);
  const control = el.matches('input, select, textarea, button:not([data-note-marker])')
    ? el
    : el.querySelector<HTMLElement>('input, select, textarea, button:not([data-note-marker])');
  control?.focus();
  return true;
}

export function useFieldFocus(ready: boolean): void {
  const [params] = useSearchParams();
  const key = params.get(FOCUS_PARAM);
  useEffect(() => {
    if (!ready || !key) return;
    let tries = 0;
    let timer = 0;
    const tick = () => {
      if (focusField(key) || ++tries >= RETRIES) return;
      timer = window.setTimeout(tick, RETRY_MS);
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [ready, key]);
}
```

- [ ] **Step 4: Markers on the tool card**

In `frontend/src/components/tools/ToolFieldsCard.tsx`:
- imports: `import FieldNoteMarker from '../fieldNotes/FieldNoteMarker';` and `import { usePartFieldNoteIndex } from '../../hooks/queries/useFieldNotes';`
- extend the `NUMERIC` entries with a `fieldKey`: type becomes `{ key: NumericKey; fieldKey: string; id: string; ... }[]` and the three entries get `fieldKey: 'tool.cavities'`, `fieldKey: 'tool.tonnage_class'`, `fieldKey: 'tool.cycle_time_s'` respectively;
- in the component body after `useSuppliers()`: `const notes = usePartFieldNoteIndex(partId);`
- the numeric field wrapper `<div key={field.key}>` becomes `<div key={field.key} data-field-key={field.fieldKey}>` and its label line becomes:
```tsx
              <div className="text-sm text-slate-400">
                {field.label}{field.unit ? ` (${field.unit})` : ''}
                <FieldNoteMarker partId={partId} fieldKey={field.fieldKey} label={field.label} note={notes.get(field.fieldKey)} />
              </div>
```
- the toolmaker wrapper `<div>` becomes `<div data-field-key="tool.toolmaker">` and its label:
```tsx
          <div className="text-sm text-slate-400">
            Toolmaker
            <FieldNoteMarker partId={partId} fieldKey="tool.toolmaker" label="Toolmaker" note={notes.get('tool.toolmaker')} />
          </div>
```

- [ ] **Step 5: Markers on the tool page**

In `frontend/src/pages/ToolDetail.tsx`:
- imports: `FieldNoteMarker` and `usePartFieldNoteIndex` (paths `../components/fieldNotes/FieldNoteMarker`, `../hooks/queries/useFieldNotes`);
- first line of the component body: `const notes = usePartFieldNoteIndex(part.id);`
- the h1 becomes:
```tsx
              <h1 data-field-key="tool.number" className="text-4xl font-bold text-slate-100 mb-1">
                {part.part_number}
                <FieldNoteMarker partId={part.id} fieldKey="tool.number" label="Tool no." note={notes.get('tool.number')} />
              </h1>
```
- directly before `<DfmArchive partId={part.id} onOpenPdf={setOpenDoc} />` insert:
```tsx
        <div data-field-key="dfm.status" className="flex items-center gap-1 mb-2 text-sm text-slate-400">
          DFM status notes
          <FieldNoteMarker partId={part.id} fieldKey="dfm.status" label="DFM status" note={notes.get('dfm.status')} />
        </div>
```

- [ ] **Step 6: Markers on the paint card**

In `frontend/src/components/paint/PartPaintCard.tsx`:
- imports: `FieldNoteMarker from '../fieldNotes/FieldNoteMarker'`, `{ usePartFieldNoteIndex } from '../../hooks/queries/useFieldNotes'`;
- after the two `useQuery` calls: `const fieldNotes = usePartFieldNoteIndex(partId);` (name `fieldNotes`, the component already has a `notes` state);
- the `<label className="flex items-center gap-2 text-sm text-slate-200">` holding the `paint-required-toggle` gets wrapped:
```tsx
        <div data-field-key="paint.painted" className="flex items-center">
          <label className="flex items-center gap-2 text-sm text-slate-200">
            {/* existing checkbox input and "Paint required" text unchanged */}
          </label>
          <FieldNoteMarker partId={partId} fieldKey="paint.painted" label="Painted" note={fieldNotes.get('paint.painted')} />
        </div>
```
- directly after the header `div` (before `{missingSpec && ...}`) add:
```tsx
      <div data-field-key="paint.colour" className="flex items-center gap-1 text-sm text-slate-400 mb-2">
        Colour / paint system
        <FieldNoteMarker partId={partId} fieldKey="paint.colour" label="Colour / paint system" note={fieldNotes.get('paint.colour')} />
      </div>
```

- [ ] **Step 7: Markers and focus on the article page**

In `frontend/src/pages/PartDetail.tsx`:
- imports: `FieldNoteMarker from '../components/fieldNotes/FieldNoteMarker'`, `{ usePartFieldNoteIndex } from '../hooks/queries/useFieldNotes'`, `{ useFieldFocus } from '../hooks/useFieldFocus'`;
- after the `files` query (before any early return): 
```tsx
  const fieldNotes = usePartFieldNoteIndex(part?.id);
  useFieldFocus(!!part);
```
  `useFieldFocus` runs here for tools too, because `ToolDetail` renders inside `PartDetail`.
- small helper inside the component body, after the early returns and before `return (`:
```tsx
  const marker = (fieldKey: string, label: string) => (
    <FieldNoteMarker partId={part.id} fieldKey={fieldKey} label={label} note={fieldNotes.get(fieldKey)} />
  );
```
- h1: `<h1 data-field-key="part.part_number" className="text-4xl font-bold text-slate-100 mb-1">{part.part_number}{marker('part.part_number', 'KTX no.')}</h1>`
- the customer number view branch (the `edit-customer-part-number` button) is wrapped in `<div data-field-key="part.customer_part_number" className="flex items-center mb-1">` with `{marker('part.customer_part_number', 'OEM no.')}` after the button; move the button's `mb-1` to the wrapper. Same for the Tier 1 branch: wrapper `data-field-key="part.tier1_part_number"`, `{marker('part.tier1_part_number', 'Tier 1 no.')}`.
- name: `<p data-field-key="part.name" className="text-slate-300 mb-2">{part.name}{marker('part.name', 'Name')}</p>`
- lifecycle badge: wrap the `lifecycle-phase` span as `<span data-field-key="part.lifecycle_phase" className="inline-flex items-center">{/* existing span */}{marker('part.lifecycle_phase', 'Phase')}</span>`
- Type cell: `<div data-field-key="part.part_type"><div className="text-sm text-slate-400">Type{marker('part.part_type', 'Type')}</div>...`
- Material cell from Task 10: label line becomes `<div className="text-sm text-slate-400">Material{marker('part.material', 'Material')}</div>`
- Revisions card heading: `<h2 data-field-key="revision.level" className="text-xl font-bold text-slate-100 mb-6">Revisions{marker('revision.level', 'E level')}</h2>`

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/hooks/useFieldFocus.test.ts src/pages src/components/tools src/components/paint src/components/project`
Expected: all PASS. If an existing test uses `getByText('Paint required')` or `getByRole('heading', { name: 'Revisions' })` and now fails because the marker adds an accessible name, change the query to `{ name: /Revisions/ }` in that test.

- [ ] **Step 9: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/hooks/useFieldFocus.ts frontend/src/hooks/useFieldFocus.test.ts frontend/src/pages/PartDetail.tsx frontend/src/pages/PartDetail.fieldNotes.test.tsx frontend/src/pages/ToolDetail.tsx frontend/src/components/tools/ToolFieldsCard.tsx frontend/src/components/tools/ToolFieldsCard.test.tsx frontend/src/components/paint/PartPaintCard.tsx
git commit -m "feat(ui): field note markers and focus highlight on article, tool and paint

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Column registry

**Files:**
- Create: `frontend/src/components/worksheet/worksheetColumns.ts`
- Create: `frontend/src/components/worksheet/worksheetFixtures.ts` (test data factory shared by the worksheet tests; imported only by tests)
- Test: `frontend/src/components/worksheet/worksheetColumns.test.ts`

**Interfaces:**
- Consumes: `WorksheetRow` (Task 8), `FieldNoteSummary`, `noteKey`, `FIELD_KEY_RE`, `materialText`, `PARTY_LABELS` from `api/dfm.ts`.
- Produces:
  - types `ColumnGroup`, `CellDisplay`, `WorksheetContext { byKey: Map<string, FieldNoteSummary>; byPart: Map<number, FieldNoteSummary[]> }`, `EditTarget { partId: number; focus: string }`, `WorksheetColumn`
  - `WORKSHEET_COLUMNS: WorksheetColumn[]`
  - `buildContext(notes: FieldNoteSummary[] | undefined): WorksheetContext`
  - `notePartId(col, row): number | null`, `noteFor(col, row, ctx): FieldNoteSummary | undefined`
  - `rowNotes(row, ctx): FieldNoteSummary[]`, `notesSummary(row, ctx): string | null`, `dfmLabel(dfm): string | null`

`WorksheetColumn`:
```ts
export interface WorksheetColumn {
  key: string;                 // = field_key
  label: string;
  group: ColumnGroup;
  filter: 'text' | 'enum' | 'none';
  exportType: 'text' | 'number';
  display: CellDisplay;
  noteOwner: 'row' | 'tool' | null;   // whose part id the note lives on
  editableOn: 'article' | 'tool' | 'paint' | null;
  defaultVisible: boolean;
  frozenWidth?: number;        // px; set on the first three identity columns
  value(row: WorksheetRow, ctx: WorksheetContext): string | number | null;
  edit(row: WorksheetRow): EditTarget | null;
}
```

- [ ] **Step 1: Write the fixture and the failing test**

`frontend/src/components/worksheet/worksheetFixtures.ts`:
```ts
/** Worksheet test data: one 1994 style article row made by tool 199401. Imported only by tests. */
import type { WorksheetRow } from '../../api/worksheet';
import { materialOf } from '../../lib/material';

const tool = {
  part_id: 90, part_number: '199401', name: 'TOOL Handle', cavities: 2, toolmaker_id: 3,
  toolmaker_name: 'Formenbau Nord', cycle_time_s: 55, tonnage_class: null,
};

export const row = (over: Partial<WorksheetRow> = {}): WorksheetRow => ({
  part_id: 1, row_kind: 'article', part_number: '20-1994-001-0', customer_part_number: '206.882.251',
  tier1_part_number: 'S00H4X-110', name: 'Handle LH', part_type: 'internal_mfg', item_category: 'article',
  thumbnail_url: null, lifecycle_phase: 'rfq', mirror_of: null,
  revision: { revision_name: 'E1', customer_index: '001', phase: 'review' },
  material: { ...materialOf({}), material_source: 'new', material_new_text: 'PA6-GF15' },
  paint: { painted: true, colour: 'VM0 Skyscraper', colour_hex: null, paint_system: 'Base / Clear' },
  tool, other_tools: ['199409'], dfm: { status: 'waiting', waiting_on: ['ktx', 'tier1'], open_topics: 1 }, ...over,
});
```

`frontend/src/components/worksheet/worksheetColumns.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { WORKSHEET_COLUMNS, buildContext, dfmLabel, noteFor, notePartId, notesSummary, rowNotes } from './worksheetColumns'
import { FIELD_KEY_RE } from '../../lib/fieldNotes'
import { row } from './worksheetFixtures'
import type { FieldNoteSummary } from '../../api/fieldNotes'

const note = (part_id: number, field_key: string, flag_status: FieldNoteSummary['flag_status'], body?: string, at = '2026-09-24T10:00:00'): FieldNoteSummary => ({
  id: part_id * 1000 + field_key.length, part_id, field_key, flag_status, flag_set_by: null, flag_set_by_name: null,
  flag_set_at: null, created_at: at, comment_count: body ? 1 : 0,
  last_comment: body ? { id: 1, body, author_id: 1, author_name: 'Eng', created_at: at } : null,
})
const col = (key: string) => WORKSHEET_COLUMNS.find((c) => c.key === key)!
const empty = buildContext([])

describe('worksheet column registry', () => {
  it('has unique keys in backend field key format and three frozen identity columns first', () => {
    const keys = WORKSHEET_COLUMNS.map((c) => c.key)
    expect(new Set(keys).size).toBe(keys.length)
    for (const k of keys) expect(FIELD_KEY_RE.test(k)).toBe(true)
    expect(WORKSHEET_COLUMNS.slice(0, 3).map((c) => c.key)).toEqual(['part.thumbnail', 'part.part_number', 'part.customer_part_number'])
    expect(WORKSHEET_COLUMNS.filter((c) => c.frozenWidth).length).toBe(3)
  })

  it('reads the values PLM holds', () => {
    const r = row()
    expect(col('part.part_number').value(r, empty)).toBe('20-1994-001-0')
    expect(col('part.tier1_part_number').value(r, empty)).toBe('S00H4X-110')
    expect(col('revision.level').value(r, empty)).toBe('E1 · 001')
    expect(col('part.material').value(r, empty)).toBe('PA6-GF15 (NEW, not in MaterialDB)')
    expect(col('paint.painted').value(r, empty)).toBe('yes')
    expect(col('paint.colour').value(r, empty)).toBe('VM0 Skyscraper / Base / Clear')
    expect(col('tool.number').value(r, empty)).toBe('199401, 199409')
    expect(col('tool.cavities').value(r, empty)).toBe(2)
    expect(col('tool.toolmaker').value(r, empty)).toBe('Formenbau Nord')
    expect(col('dfm.status').value(r, empty)).toBe('Waiting on KTX, Tier 1')
    expect(col('tool.cavities').value(row({ tool: null, dfm: null }), empty)).toBeNull()
    expect(col('part.mirror_of').value(row({ mirror_of: { part_id: 2, part_number: '20-1994-002-0', customer_part_number: '206.882.252' } }), empty)).toBe('206.882.252')
  })

  it('tool columns read and edit the tool, shared by rows of the same tool', () => {
    const lh = row(), rh = row({ part_id: 2, part_number: '20-1994-002-0' })
    const ctx = buildContext([note(90, 'tool.cavities', 'open', 'Excel says 4')])
    expect(notePartId(col('tool.cavities'), lh)).toBe(90)
    expect(noteFor(col('tool.cavities'), lh, ctx)?.flag_status).toBe('open')
    expect(noteFor(col('tool.cavities'), rh, ctx)?.flag_status).toBe('open')
    expect(col('tool.cavities').edit(lh)).toEqual({ partId: 90, focus: 'tool.cavities' })
    expect(col('dfm.status').edit(lh)).toEqual({ partId: 90, focus: 'dfm.status' })
    expect(col('tool.cavities').edit(row({ tool: null }))).toBeNull()
  })

  it('article columns read and edit the row part', () => {
    const r = row()
    expect(notePartId(col('part.material'), r)).toBe(1)
    expect(col('part.material').edit(r)).toEqual({ partId: 1, focus: 'part.material' })
    expect(col('paint.colour').edit(r)).toEqual({ partId: 1, focus: 'paint.colour' })
    expect(col('paint.colour').edit(row({ row_kind: 'tool_only' }))).toBeNull()
    expect(col('part.mirror_of').edit(r)).toBeNull()
    expect(notePartId(col('part.thumbnail'), r)).toBeNull()
    expect(notePartId(col('notes.summary'), r)).toBeNull()
  })

  it('summarises open flags and the latest comment of a row, tool notes included', () => {
    const ctx = buildContext([
      note(1, 'part.material', 'open', 'Resin to be nominated', '2026-09-23T09:00:00'),
      note(90, 'tool.cavities', 'open', 'Excel BOM says 4 cavities, PLM has 2 for the 1+1 tool', '2026-09-24T09:00:00'),
      note(90, 'part.name', 'open'),  // a tool's own name note is not an article row note
      note(1, 'paint.colour', 'confirmed'),
    ])
    expect(rowNotes(row(), ctx).map((n) => n.field_key).sort()).toEqual(['paint.colour', 'part.material', 'tool.cavities'])
    expect(notesSummary(row(), ctx)).toBe('2 open · Excel BOM says 4 cavities, PLM has 2...')
    expect(notesSummary(row(), empty)).toBeNull()
    expect(col('notes.summary').value(row(), ctx)).toBe(notesSummary(row(), ctx))
  })

  it('labels every DFM state', () => {
    expect(dfmLabel(null)).toBeNull()
    expect(dfmLabel({ status: 'no_topic', waiting_on: [], open_topics: 0 })).toBe('No topic')
    expect(dfmLabel({ status: 'all_answered', waiting_on: [], open_topics: 1 })).toBe('All answered')
    expect(dfmLabel({ status: 'open', waiting_on: [], open_topics: 1 })).toBe('Open')
    expect(dfmLabel({ status: 'finished', waiting_on: [], open_topics: 0 })).toBe('Finished')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet/worksheetColumns.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the registry**

`frontend/src/components/worksheet/worksheetColumns.ts`:
```ts
/**
 * The worksheet's column registry. key is the field_key used by field notes
 * (backend rule: <group>.<field>, lower case), so a comment or flag set in
 * the worksheet is the same note the article, tool and paint pages show.
 * Values are only read here; edit() says where the value is changed.
 */
import { PARTY_LABELS } from '../../api/dfm';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import type { WorksheetDfm, WorksheetRow } from '../../api/worksheet';
import { noteKey } from '../../lib/fieldNotes';
import { materialText } from '../../lib/material';

export type ColumnGroup = 'Identity' | 'Revision' | 'Material' | 'Paint' | 'Tool' | 'DFM' | 'Notes';
export type CellDisplay = 'thumbnail' | 'text' | 'mono' | 'number' | 'revision' | 'material' | 'dfm' | 'notes';

export interface WorksheetContext {
  byKey: Map<string, FieldNoteSummary>;
  byPart: Map<number, FieldNoteSummary[]>;
}

export interface EditTarget {
  partId: number;
  focus: string;
}

export interface WorksheetColumn {
  key: string;
  label: string;
  group: ColumnGroup;
  filter: 'text' | 'enum' | 'none';
  exportType: 'text' | 'number';
  display: CellDisplay;
  noteOwner: 'row' | 'tool' | null;
  editableOn: 'article' | 'tool' | 'paint' | null;
  defaultVisible: boolean;
  frozenWidth?: number;
  value(row: WorksheetRow, ctx: WorksheetContext): string | number | null;
  edit(row: WorksheetRow): EditTarget | null;
}

export function buildContext(notes: FieldNoteSummary[] | undefined): WorksheetContext {
  const byKey = new Map<string, FieldNoteSummary>();
  const byPart = new Map<number, FieldNoteSummary[]>();
  for (const n of Array.isArray(notes) ? notes : []) {
    byKey.set(noteKey(n.part_id, n.field_key), n);
    byPart.set(n.part_id, [...(byPart.get(n.part_id) ?? []), n]);
  }
  return { byKey, byPart };
}

const TOOL_KEY = /^(tool|dfm)\./;

export function notePartId(col: WorksheetColumn, row: WorksheetRow): number | null {
  if (col.noteOwner === 'row') return row.part_id;
  if (col.noteOwner === 'tool') return row.tool?.part_id ?? null;
  return null;
}

export function noteFor(col: WorksheetColumn, row: WorksheetRow, ctx: WorksheetContext): FieldNoteSummary | undefined {
  const partId = notePartId(col, row);
  return partId === null ? undefined : ctx.byKey.get(noteKey(partId, col.key));
}

/** The row's own notes plus its tool's tool./dfm. notes. */
export function rowNotes(row: WorksheetRow, ctx: WorksheetContext): FieldNoteSummary[] {
  const own = ctx.byPart.get(row.part_id) ?? [];
  const toolId = row.tool?.part_id;
  const fromTool = toolId !== undefined && toolId !== row.part_id
    ? (ctx.byPart.get(toolId) ?? []).filter((n) => TOOL_KEY.test(n.field_key))
    : [];
  return [...own, ...fromTool];
}

const EXCERPT = 40;

export function notesSummary(row: WorksheetRow, ctx: WorksheetContext): string | null {
  const notes = rowNotes(row, ctx);
  const open = notes.filter((n) => n.flag_status === 'open').length;
  const last = notes
    .map((n) => n.last_comment)
    .filter((c): c is NonNullable<FieldNoteSummary['last_comment']> => !!c)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const parts: string[] = [];
  if (open) parts.push(`${open} open`);
  if (last) parts.push(last.body.length > EXCERPT ? `${last.body.slice(0, EXCERPT - 3).trimEnd()}...` : last.body);
  return parts.length ? parts.join(' · ') : null;
}

export function dfmLabel(dfm: WorksheetDfm | null): string | null {
  if (!dfm) return null;
  switch (dfm.status) {
    case 'waiting': return `Waiting on ${dfm.waiting_on.map((p) => PARTY_LABELS[p]).join(', ')}`;
    case 'all_answered': return 'All answered';
    case 'no_topic': return 'No topic';
    case 'finished': return 'Finished';
    default: return 'Open';
  }
}

const onRow = (key: string) => (row: WorksheetRow): EditTarget => ({ partId: row.part_id, focus: key });
const onArticle = (key: string) => (row: WorksheetRow): EditTarget | null =>
  row.row_kind === 'tool_only' ? null : { partId: row.part_id, focus: key };
const onTool = (key: string) => (row: WorksheetRow): EditTarget | null =>
  row.tool ? { partId: row.tool.part_id, focus: key } : null;
const nowhere = (): EditTarget | null => null;

type Def = Omit<WorksheetColumn, 'defaultVisible' | 'exportType' | 'display' | 'filter'>
  & Partial<Pick<WorksheetColumn, 'defaultVisible' | 'exportType' | 'display' | 'filter'>>;

const def = (d: Def): WorksheetColumn => ({
  defaultVisible: true, exportType: 'text', display: 'text', filter: 'text', ...d,
});

export const WORKSHEET_COLUMNS: WorksheetColumn[] = [
  def({ key: 'part.thumbnail', label: 'Image', group: 'Identity', display: 'thumbnail', filter: 'none',
    noteOwner: null, editableOn: null, frozenWidth: 44, value: () => null, edit: nowhere }),
  def({ key: 'part.part_number', label: 'KTX no.', group: 'Identity', display: 'mono', noteOwner: 'row',
    editableOn: 'article', frozenWidth: 128, value: (r) => r.part_number, edit: onRow('part.part_number') }),
  def({ key: 'part.customer_part_number', label: 'OEM no.', group: 'Identity', display: 'mono', noteOwner: 'row',
    editableOn: 'article', frozenWidth: 116, value: (r) => r.customer_part_number, edit: onArticle('part.customer_part_number') }),
  def({ key: 'part.tier1_part_number', label: 'Tier 1 no.', group: 'Identity', display: 'mono', noteOwner: 'row',
    editableOn: 'article', value: (r) => r.tier1_part_number, edit: onArticle('part.tier1_part_number') }),
  def({ key: 'part.name', label: 'Name', group: 'Identity', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.name, edit: onRow('part.name') }),
  def({ key: 'part.part_type', label: 'Type', group: 'Identity', filter: 'enum', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.part_type.replace(/_/g, ' '), edit: onArticle('part.part_type') }),
  def({ key: 'part.mirror_of', label: 'Mirror of', group: 'Identity', display: 'mono', noteOwner: 'row', editableOn: null,
    defaultVisible: false, value: (r) => r.mirror_of ? (r.mirror_of.customer_part_number ?? r.mirror_of.part_number) : null,
    edit: nowhere }),
  def({ key: 'revision.level', label: 'E level', group: 'Revision', display: 'revision', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.revision ? `${r.revision.revision_name}${r.revision.customer_index ? ` · ${r.revision.customer_index}` : ''}` : null,
    edit: onArticle('revision.level') }),
  def({ key: 'part.lifecycle_phase', label: 'Phase', group: 'Revision', filter: 'enum', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.lifecycle_phase, edit: onRow('part.lifecycle_phase') }),
  def({ key: 'part.material', label: 'Material', group: 'Material', display: 'material', noteOwner: 'row', editableOn: 'article',
    value: (r) => materialText(r.material), edit: onArticle('part.material') }),
  def({ key: 'paint.painted', label: 'Painted', group: 'Paint', filter: 'enum', noteOwner: 'row', editableOn: 'paint',
    value: (r) => r.row_kind === 'tool_only' ? null : (r.paint.painted ? 'yes' : 'no'), edit: onArticle('paint.painted') }),
  def({ key: 'paint.colour', label: 'Colour / paint system', group: 'Paint', noteOwner: 'row', editableOn: 'paint',
    value: (r) => [r.paint.colour, r.paint.paint_system].filter(Boolean).join(' / ') || null, edit: onArticle('paint.colour') }),
  def({ key: 'tool.number', label: 'Tool no.', group: 'Tool', display: 'mono', noteOwner: 'tool', editableOn: 'tool',
    value: (r) => r.tool ? [r.tool.part_number, ...r.other_tools].join(', ') : null, edit: onTool('tool.number') }),
  def({ key: 'tool.cavities', label: 'Cavities', group: 'Tool', display: 'number', exportType: 'number', noteOwner: 'tool',
    editableOn: 'tool', value: (r) => r.tool?.cavities ?? null, edit: onTool('tool.cavities') }),
  def({ key: 'tool.toolmaker', label: 'Toolmaker', group: 'Tool', filter: 'enum', noteOwner: 'tool', editableOn: 'tool',
    value: (r) => r.tool?.toolmaker_name ?? null, edit: onTool('tool.toolmaker') }),
  def({ key: 'tool.cycle_time_s', label: 'Cycle time (s)', group: 'Tool', display: 'number', exportType: 'number',
    noteOwner: 'tool', editableOn: 'tool', value: (r) => r.tool?.cycle_time_s ?? null, edit: onTool('tool.cycle_time_s') }),
  def({ key: 'tool.tonnage_class', label: 'Tonnage (t)', group: 'Tool', display: 'number', exportType: 'number',
    noteOwner: 'tool', editableOn: 'tool', defaultVisible: false, value: (r) => r.tool?.tonnage_class ?? null,
    edit: onTool('tool.tonnage_class') }),
  def({ key: 'dfm.status', label: 'DFM', group: 'DFM', display: 'dfm', filter: 'enum', noteOwner: 'tool', editableOn: 'tool',
    value: (r) => dfmLabel(r.dfm), edit: onTool('dfm.status') }),
  def({ key: 'notes.summary', label: 'Notes', group: 'Notes', display: 'notes', noteOwner: null, editableOn: null,
    value: (r, ctx) => notesSummary(r, ctx), edit: nowhere }),
];
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet/worksheetColumns.test.ts`
Expected: PASS (the excerpt is the first 37 characters, trailing space trimmed, plus `...`).

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/components/worksheet/worksheetColumns.ts frontend/src/components/worksheet/worksheetFixtures.ts frontend/src/components/worksheet/worksheetColumns.test.ts
git commit -m "feat(worksheet): column registry with values, note owners and edit targets

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Worksheet table: filter, sort, hide, freeze, flag filter, page toggle

**Files:**
- Create: `frontend/src/components/worksheet/worksheetTable.ts`
- Create: `frontend/src/components/worksheet/WorksheetCell.tsx`
- Create: `frontend/src/components/worksheet/WorksheetView.tsx`
- Modify: `frontend/src/components/project/ItemsPane.tsx` (prop `onShowWorksheet`)
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (`?view=worksheet`)
- Test: `frontend/src/components/worksheet/worksheetTable.test.ts`, `frontend/src/components/worksheet/WorksheetView.test.tsx`

**Interfaces:**
- Consumes: Tasks 8, 9, 12.
- Produces:
  - `worksheetTable.ts`: `HIDDEN_COLUMNS_KEY = 'plm2.worksheet.hiddenColumns'`, `type SortState = { key: string; dir: 'asc' | 'desc' }`, `type RowKindFilter = { purchased: boolean; toolOnly: boolean }`, `loadHiddenColumns(): Set<string>`, `saveHiddenColumns(hidden: Set<string>): void`, `visibleColumns(hidden): WorksheetColumn[]`, `rowKindVisible(row, kinds): boolean`, `compareValues(a, b): number`, `applyFilters(rows, cols, filters, ctx, onlyOpenFlags): WorksheetRow[]`, `sortRows(rows, col | undefined, dir, ctx): WorksheetRow[]`, `enumOptions(col, rows, ctx): string[]`, `frozenOffsets(cols): Map<string, number>`
  - `WorksheetView` props `{ projectId: number; onClose(): void }`; test ids `worksheet-view`, `ws-row-<part_id>`, `ws-cell-<part_id>-<key>`, `sort-<key>`, `filter-<key>`, `ws-columns-toggle`, `ws-column-<key>`, `ws-only-open`, `ws-kind-purchased`, `ws-kind-tool-only`, `ws-close`, `ws-count`
  - `WorksheetCell` props `{ row; col; ctx; note?; noteOpen: boolean; onNoteOpenChange(open: boolean): void; onMenu(rect: DOMRect): void }`
  - `ItemsPane` optional prop `onShowWorksheet?: () => void`, button test id `show-worksheet`

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/worksheet/worksheetTable.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  HIDDEN_COLUMNS_KEY, applyFilters, compareValues, enumOptions, frozenOffsets, loadHiddenColumns,
  rowKindVisible, saveHiddenColumns, sortRows, visibleColumns,
} from './worksheetTable'
import { WORKSHEET_COLUMNS, buildContext } from './worksheetColumns'
import { row } from './worksheetFixtures'

const col = (key: string) => WORKSHEET_COLUMNS.find((c) => c.key === key)!
const ctx = buildContext([])
const a = row({ part_id: 1, part_number: '20-1994-010-0', name: 'Side shield', part_type: 'internal_mfg' })
const b = row({ part_id: 2, part_number: '20-1994-002-0', name: 'Handle RH', part_type: 'purchased', row_kind: 'purchased',
  tool: { part_id: 91, part_number: '199409', name: 't', cavities: 8, toolmaker_id: null, toolmaker_name: null, cycle_time_s: null, tonnage_class: null } })
const c = row({ part_id: 3, part_number: '199413', name: 'Tool only', row_kind: 'tool_only', tool: null, dfm: null })

describe('worksheet table helpers', () => {
  afterEach(() => { window.localStorage.clear(); vi.restoreAllMocks() })

  it('filters text case-insensitively and enums exactly, on visible columns only', () => {
    const cols = [col('part.name'), col('part.part_type')]
    expect(applyFilters([a, b], cols, { 'part.name': 'HANDLE' }, ctx, false)).toEqual([b])
    expect(applyFilters([a, b], cols, { 'part.part_type': 'purchased' }, ctx, false)).toEqual([b])
    expect(applyFilters([a, b], [col('part.name')], { 'part.part_type': 'purchased' }, ctx, false)).toEqual([a, b])
    expect(applyFilters([a, b], cols, { 'part.name': '   ' }, ctx, false)).toEqual([a, b])
  })

  it('keeps only rows with an open flag, tool flags included', () => {
    const flagged = buildContext([{ id: 1, part_id: 91, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null,
      flag_set_by_name: null, flag_set_at: null, created_at: null, comment_count: 0, last_comment: null }])
    expect(applyFilters([a, b], [col('part.name')], {}, flagged, true)).toEqual([b])
  })

  it('sorts numbers numerically with empty values last, and part numbers by default', () => {
    const none = row({ part_id: 4, tool: null })
    expect(sortRows([b, none, a], col('tool.cavities'), 'asc', ctx).map((r) => r.part_id)).toEqual([1, 2, 4])
    expect(sortRows([b, none, a], col('tool.cavities'), 'desc', ctx).map((r) => r.part_id)).toEqual([2, 1, 4])
    expect(sortRows([a, b], undefined, 'asc', ctx).map((r) => r.part_id)).toEqual([2, 1])
    expect(compareValues('E10', 'E9')).toBeGreaterThan(0)
  })

  it('shows purchased and tool-only rows only when asked', () => {
    const none = { purchased: false, toolOnly: false }
    expect([a, b, c].filter((r) => rowKindVisible(r, none))).toEqual([a])
    expect([a, b, c].filter((r) => rowKindVisible(r, { purchased: true, toolOnly: true }))).toEqual([a, b, c])
  })

  it('lists enum options from the rows', () => {
    expect(enumOptions(col('part.part_type'), [a, b, a], ctx)).toEqual(['internal mfg', 'purchased'])
  })

  it('remembers hidden columns and falls back to the defaults', () => {
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
    saveHiddenColumns(new Set(['part.name']))
    expect(window.localStorage.getItem(HIDDEN_COLUMNS_KEY)).toBe('["part.name"]')
    expect(loadHiddenColumns()).toEqual(new Set(['part.name']))
    expect(visibleColumns(new Set(['part.name'])).some((x) => x.key === 'part.name')).toBe(false)
  })

  it('hidden columns fall back to defaults on bad storage', () => {
    window.localStorage.setItem(HIDDEN_COLUMNS_KEY, '{not json')
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
    window.localStorage.setItem(HIDDEN_COLUMNS_KEY, '{"a":1}')
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
  })

  it('stacks the frozen columns from the left', () => {
    const offsets = frozenOffsets(visibleColumns(new Set()))
    expect([...offsets.entries()]).toEqual([['part.thumbnail', 0], ['part.part_number', 44], ['part.customer_part_number', 172]])
    expect([...frozenOffsets(visibleColumns(new Set(['part.thumbnail']))).entries()]).toEqual([['part.part_number', 0], ['part.customer_part_number', 128]])
  })
})
```

`frontend/src/components/worksheet/WorksheetView.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import WorksheetView from './WorksheetView'
import { row } from './worksheetFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const rows = [
  row({ part_id: 1, part_number: '20-1994-010-0', name: 'Side shield' }),
  row({ part_id: 2, part_number: '20-1994-002-0', name: 'Handle RH', part_type: 'purchased', row_kind: 'purchased' }),
  row({ part_id: 3, part_number: '20-1994-005-0', name: 'ISOFIX Cover',
    tool: { part_id: 93, part_number: '199403', name: 't', cavities: 4, toolmaker_id: null, toolmaker_name: null, cycle_time_s: null, tonnage_class: null } }),
]
const notes = [{ id: 1, part_id: 93, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null, flag_set_by_name: null,
  flag_set_at: null, created_at: null, comment_count: 1, last_comment: { id: 1, body: 'Excel says 2', author_id: 1, author_name: 'E', created_at: '2026-09-24T09:00:00' } }]

function mount(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><WorksheetView projectId={35} onClose={onClose} /></MemoryRouter></QueryClientProvider>)
  return onClose
}

describe('WorksheetView', () => {
  beforeEach(() => {
    window.localStorage.clear()
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows } })
      if (url === '/v1/projects/35/field-notes') return Promise.resolve({ data: notes })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists articles sorted by part number, purchased rows only on request', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3', 'ws-row-1'])
    fireEvent.click(screen.getByTestId('ws-kind-purchased'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-2', 'ws-row-3', 'ws-row-1'])
    expect(screen.getByTestId('ws-count').textContent).toBe('3 rows')
  })

  it('tints a flagged cell and filters to rows with open flags', async () => {
    mount()
    const cell = await screen.findByTestId('ws-cell-3-tool.cavities')
    expect(cell.dataset.flag).toBe('open')
    expect(within(cell).getByTestId('ws-tint-3-tool.cavities').className).toContain('bg-yellow-500/20')
    fireEvent.click(screen.getByTestId('ws-only-open'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3'])
  })

  it('filters by column text and sorts by a column header', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: 'isofix' } })
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3'])
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('sort-tool.cavities'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-1', 'ws-row-3'])
    fireEvent.click(screen.getByTestId('sort-tool.cavities'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3', 'ws-row-1'])
  })

  it('hides a column and remembers it', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.click(screen.getByTestId('ws-columns-toggle'))
    fireEvent.click(screen.getByTestId('ws-column-part.name'))
    expect(screen.queryByTestId('sort-part.name')).toBeNull()
    expect(JSON.parse(window.localStorage.getItem('plm2.worksheet.hiddenColumns')!)).toContain('part.name')
  })

  it('freezes the first identity columns', async () => {
    mount()
    const cell = await screen.findByTestId('ws-cell-1-part.part_number')
    expect(cell.className).toContain('sticky')
    expect(cell.style.left).toBe('44px')
  })

  it('goes back to the item list', async () => {
    const onClose = mount()
    fireEvent.click(await screen.findByTestId('ws-close'))
    expect(onClose).toHaveBeenCalled()
  })
})
```

Append to `frontend/src/components/project/ItemsPane.test.tsx` inside the `describe`:
```tsx
  it('offers the worksheet when the page supports it', () => {
    const onShowWorksheet = vi.fn()
    mount({ onShowWorksheet })
    fireEvent.click(screen.getByTestId('show-worksheet'))
    expect(onShowWorksheet).toHaveBeenCalled()
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet src/components/project/ItemsPane.test.tsx`
Expected: FAIL (modules missing, no `show-worksheet`).

- [ ] **Step 3: Write the table helpers**

`frontend/src/components/worksheet/worksheetTable.ts`:
```ts
/** Pure worksheet table logic: row kinds, filters, sort, hidden columns, frozen offsets. */
import type { WorksheetRow } from '../../api/worksheet';
import { comparePartNumbers } from '../../lib/partDisplay';
import { readStored, writeStored } from '../../lib/safeStorage';
import { WORKSHEET_COLUMNS, rowNotes, type WorksheetColumn, type WorksheetContext } from './worksheetColumns';

export const HIDDEN_COLUMNS_KEY = 'plm2.worksheet.hiddenColumns';

export type SortState = { key: string; dir: 'asc' | 'desc' };
export type RowKindFilter = { purchased: boolean; toolOnly: boolean };

const DEFAULT_HIDDEN = () => new Set(WORKSHEET_COLUMNS.filter((c) => !c.defaultVisible).map((c) => c.key));

export function loadHiddenColumns(): Set<string> {
  const raw = readStored(HIDDEN_COLUMNS_KEY);
  if (raw === null) return DEFAULT_HIDDEN();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((k) => typeof k === 'string')) return new Set(parsed);
  } catch {
    // corrupt value: defaults below
  }
  return DEFAULT_HIDDEN();
}

export function saveHiddenColumns(hidden: Set<string>): void {
  writeStored(HIDDEN_COLUMNS_KEY, JSON.stringify([...hidden]));
}

export function visibleColumns(hidden: Set<string>): WorksheetColumn[] {
  return WORKSHEET_COLUMNS.filter((c) => !hidden.has(c.key));
}

export function rowKindVisible(row: WorksheetRow, kinds: RowKindFilter): boolean {
  if (row.row_kind === 'purchased') return kinds.purchased;
  if (row.row_kind === 'tool_only') return kinds.toolOnly;
  return true;
}

/** Empty values last; numbers numerically; text with embedded numbers naturally. */
export function compareValues(a: string | number | null, b: string | number | null): number {
  const ea = a === null || a === '';
  const eb = b === null || b === '';
  if (ea || eb) return ea === eb ? 0 : ea ? 1 : -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

export function applyFilters(
  rows: WorksheetRow[], cols: WorksheetColumn[], filters: Record<string, string>,
  ctx: WorksheetContext, onlyOpenFlags: boolean,
): WorksheetRow[] {
  const active = cols
    .map((c) => ({ c, f: (filters[c.key] ?? '').trim() }))
    .filter(({ c, f }) => f !== '' && c.filter !== 'none');
  return rows.filter((row) => {
    if (onlyOpenFlags && !rowNotes(row, ctx).some((n) => n.flag_status === 'open')) return false;
    return active.every(({ c, f }) => {
      const v = c.value(row, ctx);
      const text = v === null ? '' : String(v);
      return c.filter === 'enum' ? text === f : text.toLowerCase().includes(f.toLowerCase());
    });
  });
}

export function sortRows(
  rows: WorksheetRow[], col: WorksheetColumn | undefined, dir: 'asc' | 'desc', ctx: WorksheetContext,
): WorksheetRow[] {
  const out = [...rows];
  if (!col) return out.sort((x, y) => comparePartNumbers(x.part_number, y.part_number));
  const sign = dir === 'asc' ? 1 : -1;
  return out.sort((x, y) => {
    const vx = col.value(x, ctx);
    const vy = col.value(y, ctx);
    const emptyX = vx === null || vx === '';
    const emptyY = vy === null || vy === '';
    if (emptyX || emptyY) return compareValues(vx, vy); // empties stay last in both directions
    return sign * compareValues(vx, vy) || comparePartNumbers(x.part_number, y.part_number);
  });
}

export function enumOptions(col: WorksheetColumn, rows: WorksheetRow[], ctx: WorksheetContext): string[] {
  const values = new Set<string>();
  for (const r of rows) {
    const v = col.value(r, ctx);
    if (v !== null && v !== '') values.add(String(v));
  }
  return [...values].sort((x, y) => compareValues(x, y));
}

export function frozenOffsets(cols: WorksheetColumn[]): Map<string, number> {
  const out = new Map<string, number>();
  let left = 0;
  for (const c of cols) {
    if (!c.frozenWidth) continue;
    out.set(c.key, left);
    left += c.frozenWidth;
  }
  return out;
}
```

- [ ] **Step 4: Write the cell**

`frontend/src/components/worksheet/WorksheetCell.tsx`:
```tsx
/** One worksheet cell: the value by display kind, the field note marker, and a "..." menu button for touch and keyboard. */
import PartThumbnail from '../parts/PartThumbnail';
import RevisionLabel from '../parts/RevisionLabel';
import MaterialValue from '../materials/MaterialValue';
import FieldNoteMarker from '../fieldNotes/FieldNoteMarker';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import type { WorksheetRow } from '../../api/worksheet';
import { notePartId, type WorksheetColumn, type WorksheetContext } from './worksheetColumns';

export interface WorksheetCellProps {
  row: WorksheetRow;
  col: WorksheetColumn;
  ctx: WorksheetContext;
  note?: FieldNoteSummary;
  noteOpen: boolean;
  onNoteOpenChange(open: boolean): void;
  onMenu(rect: DOMRect): void;
}

const DFM_TONE: Record<string, string> = { waiting: 'text-amber-300', all_answered: 'text-emerald-300', finished: 'text-slate-400' };

export default function WorksheetCell({ row, col, ctx, note, noteOpen, onNoteOpenChange, onMenu }: WorksheetCellProps) {
  const value = col.value(row, ctx);
  const partId = notePartId(col, row);
  let body: React.ReactNode;
  switch (col.display) {
    case 'thumbnail':
      body = <PartThumbnail url={row.thumbnail_url} name={row.name} />;
      break;
    case 'revision':
      body = row.revision ? <RevisionLabel name={row.revision.revision_name} index={row.revision.customer_index} /> : null;
      break;
    case 'material':
      body = row.row_kind === 'tool_only' ? null : <MaterialValue material={row.material} testId={`ws-material-${row.part_id}`} />;
      break;
    case 'dfm':
      body = value === null ? null : <span className={DFM_TONE[row.dfm?.status ?? ''] ?? 'text-slate-300'}>{value}</span>;
      break;
    case 'notes':
      body = value === null ? null : <span className="text-slate-400">{value}</span>;
      break;
    default:
      body = value === null ? null : (
        <span className={col.display === 'mono' ? 'font-mono text-slate-200' : col.display === 'number' ? 'tabular-nums text-slate-200' : 'text-slate-100'}>
          {value}
        </span>
      );
  }
  return (
    <span className="inline-flex items-center gap-0.5">
      {body}
      {partId !== null && (
        <FieldNoteMarker partId={partId} fieldKey={col.key} label={col.label} note={note}
          open={noteOpen} onOpenChange={onNoteOpenChange} quietWhenEmpty />
      )}
      <button
        type="button"
        aria-label={`Actions for ${col.label}`}
        data-testid={`cell-menu-${row.part_id}-${col.key}`}
        onClick={(e) => { e.stopPropagation(); onMenu((e.currentTarget as HTMLElement).getBoundingClientRect()); }}
        className="ml-0.5 px-0.5 text-slate-500 hover:text-slate-200 opacity-0 group-hover:opacity-100 focus:opacity-100"
      >
        ⋯
      </button>
    </span>
  );
}
```
(The spec names the hover button "⋯"; that glyph is U+22EF, not a dash.)

- [ ] **Step 5: Write the view**

`frontend/src/components/worksheet/WorksheetView.tsx`:
```tsx
/**
 * WorksheetView - the project overview table: one row per article with the
 * producing tool's values, columns from worksheetColumns.ts. Values are
 * changed where they live (article, tool, paint); here a cell is only read,
 * commented and flagged. Full width while active; the detail pane is hidden.
 */
import { useMemo, useState } from 'react';
import { useProjectFieldNotes } from '../../hooks/queries/useFieldNotes';
import { useWorksheet } from '../../hooks/queries/useWorksheet';
import { flagTint } from '../../lib/fieldNotes';
import { WORKSHEET_COLUMNS, buildContext, noteFor, type WorksheetColumn } from './worksheetColumns';
import {
  applyFilters, enumOptions, frozenOffsets, loadHiddenColumns, rowKindVisible, saveHiddenColumns,
  sortRows, visibleColumns, type RowKindFilter, type SortState,
} from './worksheetTable';
import WorksheetCell from './WorksheetCell';

export interface WorksheetViewProps {
  projectId: number;
  onClose(): void;
}

const GROUPS = ['Identity', 'Revision', 'Material', 'Paint', 'Tool', 'DFM', 'Notes'] as const;

export default function WorksheetView({ projectId, onClose }: WorksheetViewProps) {
  const { data, isLoading, isError } = useWorksheet(projectId);
  const { data: notes } = useProjectFieldNotes(projectId);
  const [hidden, setHidden] = useState<Set<string>>(loadHiddenColumns);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<SortState | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [kinds, setKinds] = useState<RowKindFilter>({ purchased: false, toolOnly: false });
  const [showColumns, setShowColumns] = useState(false);
  const [openNote, setOpenNote] = useState<string | null>(null); // `${row.part_id}|${col.key}`

  const ctx = useMemo(() => buildContext(notes), [notes]);
  const cols = useMemo(() => visibleColumns(hidden), [hidden]);
  const offsets = useMemo(() => frozenOffsets(cols), [cols]);
  const kindRows = useMemo(() => (data?.rows ?? []).filter((r) => rowKindVisible(r, kinds)), [data, kinds]);
  const shown = useMemo(() => {
    const filtered = applyFilters(kindRows, cols, filters, ctx, onlyOpen);
    const sortCol = sort ? cols.find((c) => c.key === sort.key) : undefined;
    return sortRows(filtered, sortCol, sort?.dir ?? 'asc', ctx);
  }, [kindRows, cols, filters, ctx, onlyOpen, sort]);

  const toggleHidden = (key: string) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key); else next.add(key);
    setHidden(next);
    saveHiddenColumns(next);
  };
  const toggleSort = (key: string) =>
    setSort((s) => (!s || s.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null));
  const frozenStyle = (c: WorksheetColumn) =>
    offsets.has(c.key) ? { left: offsets.get(c.key), minWidth: c.frozenWidth, maxWidth: c.frozenWidth } : undefined;
  const frozenClass = (c: WorksheetColumn) => (offsets.has(c.key) ? 'sticky z-10 bg-slate-900' : '');

  return (
    <div data-testid="worksheet-view" className="h-full flex flex-col min-h-0">
      <div className="flex-shrink-0 flex flex-wrap items-center gap-3 px-3 py-2 border-b border-slate-800 text-xs text-slate-300">
        <h2 className="font-semibold uppercase tracking-wide text-slate-300">Worksheet</h2>
        <span data-testid="ws-count" className="text-slate-500">{shown.length} rows</span>
        <label className="flex items-center gap-1">
          <input type="checkbox" data-testid="ws-only-open" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
          Only rows with open flags
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" data-testid="ws-kind-purchased" checked={kinds.purchased}
            onChange={(e) => setKinds((k) => ({ ...k, purchased: e.target.checked }))} />
          Purchased parts
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" data-testid="ws-kind-tool-only" checked={kinds.toolOnly}
            onChange={(e) => setKinds((k) => ({ ...k, toolOnly: e.target.checked }))} />
          Tools without article
        </label>
        <div className="relative">
          <button type="button" data-testid="ws-columns-toggle" aria-expanded={showColumns} onClick={() => setShowColumns((v) => !v)}
            className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Columns</button>
          {showColumns && (
            <div className="absolute z-30 mt-1 w-64 max-h-96 overflow-y-auto bg-slate-800 border border-slate-600 rounded shadow-lg p-2">
              {GROUPS.map((g) => (
                <div key={g} className="mb-1">
                  <div className="text-[10px] uppercase text-slate-500">{g}</div>
                  {WORKSHEET_COLUMNS.filter((c) => c.group === g).map((c) => (
                    <label key={c.key} className="flex items-center gap-2 py-0.5">
                      <input type="checkbox" data-testid={`ws-column-${c.key}`} checked={!hidden.has(c.key)} onChange={() => toggleHidden(c.key)} />
                      {c.label}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
        {/* Task 15 puts the export button here */}
        <button type="button" data-testid="ws-close" onClick={onClose}
          className="ml-auto px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Back to list</button>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading...</p>
        ) : isError ? (
          <p className="p-4 text-sm text-red-400">Could not load the worksheet</p>
        ) : (
          <table className="text-xs border-separate border-spacing-0">
            <thead className="sticky top-0 z-20 bg-slate-900 text-left text-slate-400">
              <tr>
                {cols.map((c) => (
                  <th key={c.key} style={frozenStyle(c)} className={`px-2 py-1 font-medium whitespace-nowrap border-b border-slate-700 ${frozenClass(c)}`}>
                    {c.display === 'thumbnail' ? <span className="sr-only">{c.label}</span> : (
                      <button type="button" data-testid={`sort-${c.key}`} onClick={() => toggleSort(c.key)} className="hover:text-slate-100">
                        {c.label}{sort?.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
              <tr>
                {cols.map((c) => (
                  <th key={c.key} style={frozenStyle(c)} className={`px-1 pb-1 border-b border-slate-700 ${frozenClass(c)}`}>
                    {c.filter === 'text' && (
                      <input data-testid={`filter-${c.key}`} aria-label={`Filter ${c.label}`} value={filters[c.key] ?? ''}
                        onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                        className="w-full min-w-[4rem] bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100 font-normal" />
                    )}
                    {c.filter === 'enum' && (
                      <select data-testid={`filter-${c.key}`} aria-label={`Filter ${c.label}`} value={filters[c.key] ?? ''}
                        onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                        className="w-full bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100 font-normal">
                        <option value="">All</option>
                        {enumOptions(c, kindRows, ctx).map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.part_id} data-testid={`ws-row-${row.part_id}`} className="hover:bg-slate-800/40">
                  {cols.map((c) => {
                    const note = noteFor(c, row, ctx);
                    const id = `${row.part_id}|${c.key}`;
                    return (
                      <td key={c.key} data-testid={`ws-cell-${row.part_id}-${c.key}`} data-flag={note?.flag_status ?? ''}
                        style={frozenStyle(c)}
                        className={`group p-0 border-b border-slate-800 whitespace-nowrap ${frozenClass(c)}`}>
                        <div data-testid={`ws-tint-${row.part_id}-${c.key}`} className={`px-2 py-1 ${flagTint(note?.flag_status)}`}>
                          <WorksheetCell row={row} col={c} ctx={ctx} note={note}
                            noteOpen={openNote === id}
                            onNoteOpenChange={(open) => setOpenNote(open ? id : null)}
                            onMenu={() => { /* Task 14 opens the cell menu */ }} />
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={cols.length} className="p-4 text-sm text-slate-500">No rows match</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Toggle from the items pane and the project page**

In `frontend/src/components/project/ItemsPane.tsx`:
- add to `ItemsPaneProps`: `/** Opens the project worksheet (full width). */ onShowWorksheet?: () => void;` and destructure it;
- replace `<span className="text-[11px] text-slate-500">Drag onto a ★ sub-assembly to restructure</span>` with:
```tsx
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500">Drag onto a ★ sub-assembly to restructure</span>
            {onShowWorksheet && (
              <button type="button" data-testid="show-worksheet" onClick={onShowWorksheet}
                className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-700 hover:bg-slate-600 text-slate-100">
                Worksheet
              </button>
            )}
          </div>
```

In `frontend/src/pages/ProjectDetailPage.tsx`:
- import `WorksheetView from '../components/worksheet/WorksheetView';`
- `const [searchParams] = useSearchParams();` becomes `const [searchParams, setSearchParams] = useSearchParams();`
- after `initialPartId`:
```tsx
  const showWorksheet = searchParams.get('view') === 'worksheet';
  const setWorksheet = useCallback((on: boolean) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (on) next.set('view', 'worksheet');
      else next.delete('view');
      return next;
    }, { replace: true });
  }, [setSearchParams]);
```
  (place it above the early returns, next to the other hooks)
- pass `onShowWorksheet={() => setWorksheet(true)}` to `ItemsPane`;
- wrap the `SplitPane` block: 
```tsx
      <div className="flex-1 min-h-0">
        {showWorksheet ? (
          <WorksheetView projectId={id} onClose={() => setWorksheet(false)} />
        ) : (
          <SplitPane ... unchanged ... />
        )}
      </div>
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet src/components/project src/pages/ProjectDetailPage.layout.test.tsx src/pages/ProjectDetailPage.article.test.tsx src/pages/ProjectDetailPage.files.test.tsx src/pages/ProjectDetailPage.upload.test.tsx`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/components/worksheet frontend/src/components/project/ItemsPane.tsx frontend/src/components/project/ItemsPane.test.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(worksheet): worksheet view with filters, sort, columns, frozen identity, flag tint

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Cell context menu: edit, comment, flag

**Files:**
- Create: `frontend/src/components/worksheet/WorksheetCellMenu.tsx`
- Modify: `frontend/src/components/worksheet/WorksheetView.tsx`
- Test: append to `frontend/src/components/worksheet/WorksheetView.test.tsx`

**Interfaces:**
- Consumes: `col.edit(row)`, `notePartId`, `noteFor`, `setFieldFlag`, `FIELD_NOTES_KEY`, `FOCUS_PARAM`.
- Produces: `WorksheetCellMenu` props `{ menu: CellMenuState | null; flag: FieldFlag | null; onClose(): void; onEdit(): void; onComment(): void; onFlag(flag: FieldFlag | null): void }`, type `CellMenuState = { x: number; y: number; row: WorksheetRow; col: WorksheetColumn }`; menu test ids `ws-menu`, `ws-menu-edit`, `ws-menu-comment`, `ws-menu-flag-open|confirmed|rejected`, `ws-menu-flag-clear`. Edit navigates to `/parts/<id>?focus=<key>`.

- [ ] **Step 1: Write the failing tests**

Append to `WorksheetView.test.tsx` (add `waitFor` to the testing-library import and `Routes, Route, useLocation` to the router import):
```tsx
function Where() {
  const loc = useLocation()
  return <div data-testid="where">{loc.pathname}{loc.search}</div>
}

function mountRouted() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={['/projects/35?view=worksheet']}>
    <Routes>
      <Route path="/projects/:id" element={<WorksheetView projectId={35} onClose={vi.fn()} />} />
      <Route path="/parts/:partId" element={<Where />} />
    </Routes>
  </MemoryRouter></QueryClientProvider>)
}

describe('WorksheetView cell menu', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows } })
      if (url === '/v1/projects/35/field-notes') return Promise.resolve({ data: notes })
      return Promise.resolve({ data: { ...notes[0], comments: [] } })
    })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('Edit on a tool field opens the tool page with the field focused', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-3-tool.cavities'), { clientX: 10, clientY: 10 })
    fireEvent.click(screen.getByTestId('ws-menu-edit'))
    expect((await screen.findByTestId('where')).textContent).toBe('/parts/93?focus=tool.cavities')
  })

  it('Edit on the material opens the article', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-1-part.material'))
    fireEvent.click(screen.getByTestId('ws-menu-edit'))
    expect((await screen.findByTestId('where')).textContent).toBe('/parts/1?focus=part.material')
  })

  it('Edit is disabled where no page changes the value', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-1-notes.summary'))
    expect((screen.getByTestId('ws-menu-edit') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId('ws-menu-comment') as HTMLButtonElement).disabled).toBe(true)
  })

  it('Flag sets the flag on the owning part and Comment opens the popover', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-1-part.name'))
    fireEvent.click(screen.getByTestId('ws-menu-flag-rejected'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/1/field-notes/part.name/flag', { status: 'rejected' }))
    fireEvent.contextMenu(screen.getByTestId('ws-cell-3-tool.cavities'))
    expect((screen.getByTestId('ws-menu-flag-clear') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('ws-menu-comment'))
    expect(await screen.findByTestId('note-popover-tool.cavities')).toBeTruthy()
  })

  it('the hover button opens the same menu', async () => {
    mountRouted()
    await screen.findByTestId('ws-cell-1-part.name')
    fireEvent.click(screen.getByTestId('cell-menu-1-part.name'))
    expect(screen.getByTestId('ws-menu')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('ws-menu')).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet/WorksheetView.test.tsx`
Expected: the new tests FAIL (no `ws-menu`).

- [ ] **Step 3: Write the menu**

`frontend/src/components/worksheet/WorksheetCellMenu.tsx`:
```tsx
/** Right-click (or "⋯") menu on a worksheet cell: Edit where the value lives, Comment, Flag. */
import { useEffect, useRef } from 'react';
import type { FieldFlag } from '../../api/fieldNotes';
import type { WorksheetRow } from '../../api/worksheet';
import { FLAG_LABELS, FLAGS } from '../../lib/fieldNotes';
import { notePartId, type WorksheetColumn } from './worksheetColumns';

export interface CellMenuState {
  x: number;
  y: number;
  row: WorksheetRow;
  col: WorksheetColumn;
}

export interface WorksheetCellMenuProps {
  menu: CellMenuState | null;
  flag: FieldFlag | null;
  onClose(): void;
  onEdit(): void;
  onComment(): void;
  onFlag(flag: FieldFlag | null): void;
}

const item = 'w-full text-left px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:text-slate-500 disabled:hover:bg-transparent';

export default function WorksheetCellMenu({ menu, flag, onClose, onEdit, onComment, onFlag }: WorksheetCellMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menu, onClose]);
  if (!menu) return null;

  const canEdit = !!menu.col.edit(menu.row);
  const canNote = notePartId(menu.col, menu.row) !== null;
  const act = (fn: () => void) => () => { fn(); onClose(); };

  return (
    <div ref={ref} role="menu" data-testid="ws-menu" aria-label={`${menu.col.label} actions`}
      className="fixed z-50 min-w-[11rem] bg-slate-700 border border-slate-600 rounded-lg shadow-lg py-1"
      style={{ top: menu.y, left: menu.x }}>
      <button role="menuitem" type="button" data-testid="ws-menu-edit" disabled={!canEdit} onClick={act(onEdit)} className={item}
        title={canEdit ? 'Open the page where this value is changed' : 'This value is not changed on a page'}>
        Edit
      </button>
      <button role="menuitem" type="button" data-testid="ws-menu-comment" disabled={!canNote} onClick={act(onComment)} className={item}>
        Comment
      </button>
      <div className="border-t border-slate-600 my-1" />
      {FLAGS.map((f) => (
        <button key={f} role="menuitem" type="button" data-testid={`ws-menu-flag-${f}`} disabled={!canNote || flag === f}
          onClick={act(() => onFlag(f))} className={item}>
          Flag {FLAG_LABELS[f].toLowerCase()}
        </button>
      ))}
      <button role="menuitem" type="button" data-testid="ws-menu-flag-clear" disabled={!canNote || !flag}
        onClick={act(() => onFlag(null))} className={item}>
        Clear flag
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Wire the menu into the view**

In `frontend/src/components/worksheet/WorksheetView.tsx`:
- imports:
```tsx
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { setFieldFlag, type FieldFlag } from '../../api/fieldNotes';
import { FIELD_NOTES_KEY } from '../../hooks/queries/useFieldNotes';
import { FOCUS_PARAM } from '../../hooks/useFieldFocus';
import { apiErrorMessage } from '../../lib/apiError';
import WorksheetCellMenu, { type CellMenuState } from './WorksheetCellMenu';
```
- state and actions inside the component:
```tsx
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [menu, setMenu] = useState<CellMenuState | null>(null);
  const flagMutation = useMutation({
    mutationFn: ({ partId, key, flag }: { partId: number; key: string; flag: FieldFlag | null }) => setFieldFlag(partId, key, flag),
    onSuccess: () => qc.invalidateQueries({ queryKey: [FIELD_NOTES_KEY] }),
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not set the flag')),
  });
  const menuNote = menu ? noteFor(menu.col, menu.row, ctx) : undefined;
  const closeMenu = useCallback(() => setMenu(null), []);
```
  (add `useCallback` to the react import)
- on each `<td>` add:
```tsx
                        onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, row, col: c }); }}
```
- the `WorksheetCell` `onMenu` becomes `onMenu={(rect) => setMenu({ x: rect.left, y: rect.bottom, row, col: c })}`
- before the closing `</div>` of the view root:
```tsx
      <WorksheetCellMenu
        menu={menu}
        flag={menuNote?.flag_status ?? null}
        onClose={closeMenu}
        onEdit={() => {
          const target = menu?.col.edit(menu.row);
          if (target) navigate(`/parts/${target.partId}?${FOCUS_PARAM}=${encodeURIComponent(target.focus)}`);
        }}
        onComment={() => { if (menu) setOpenNote(`${menu.row.part_id}|${menu.col.key}`); }}
        onFlag={(flag) => {
          const partId = menu ? notePartId(menu.col, menu.row) : null;
          if (menu && partId !== null) flagMutation.mutate({ partId, key: menu.col.key, flag });
        }}
      />
```
- extend the `./worksheetColumns` import with `notePartId` (used by `onFlag`; `tsconfig.json` has `noUnusedLocals`, so it is only imported now).

Note on the Comment item: the menu closes (`act`) after `onComment`, then the cell's marker receives `open` and positions its popover on its own button, so the popover appears next to the cell.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/components/worksheet/WorksheetCellMenu.tsx frontend/src/components/worksheet/WorksheetView.tsx frontend/src/components/worksheet/WorksheetView.test.tsx
git commit -m "feat(worksheet): cell menu with edit navigation, comment and flag

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: Export button

**Files:**
- Modify: `frontend/src/components/worksheet/worksheetTable.ts` (add `buildExportPayload`)
- Modify: `frontend/src/components/worksheet/WorksheetView.tsx`
- Test: append to `worksheetTable.test.ts` and `WorksheetView.test.tsx`

**Interfaces:**
- Consumes: `downloadWorksheetXlsx(projectId, payload)` (Task 8), `noteFor`.
- Produces: `buildExportPayload(cols, rows, ctx): WorksheetExportPayload` (thumbnail columns left out; `frozen_columns` = visible frozen columns without the thumbnail); button test id `ws-export`.

- [ ] **Step 1: Write the failing tests**

Append to `worksheetTable.test.ts` (import `buildExportPayload` too):
```ts
  it('builds the export from visible columns and rows with types and flags', () => {
    const flagged = buildContext([{ id: 1, part_id: 90, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null,
      flag_set_by_name: null, flag_set_at: null, created_at: null, comment_count: 2, last_comment: null }])
    const cols = visibleColumns(new Set()).filter((x) => ['part.thumbnail', 'part.part_number', 'part.customer_part_number', 'tool.cavities'].includes(x.key))
    const payload = buildExportPayload(cols, [a], flagged)
    expect(payload.columns).toEqual([
      { key: 'part.part_number', label: 'KTX no.', type: 'text' },
      { key: 'part.customer_part_number', label: 'OEM no.', type: 'text' },
      { key: 'tool.cavities', label: 'Cavities', type: 'number' },
    ])
    expect(payload.frozen_columns).toBe(2)
    expect(payload.rows[0].cells).toEqual([
      { value: '20-1994-010-0', flag: null, comments: 0 },
      { value: '206.882.251', flag: null, comments: 0 },
      { value: 2, flag: 'open', comments: 2 },
    ])
  })
```
Append to the first `describe('WorksheetView', ...)` in `WorksheetView.test.tsx`:
```tsx
  it('exports the visible rows as xlsx', async () => {
    clientMocks.post.mockResolvedValue({ data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="1994-worksheet.xlsx"' } })
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() })
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: 'isofix' } })
    fireEvent.click(screen.getByTestId('ws-export'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const [url, payload] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/projects/35/worksheet/export')
    expect(payload.rows).toHaveLength(1)
    expect(payload.columns.some((c: { key: string }) => c.key === 'part.thumbnail')).toBe(false)
  })
```
(add `waitFor` to that file's imports if Task 14 did not already).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet`
Expected: FAIL (`buildExportPayload` not exported, no `ws-export`).

- [ ] **Step 3: Add the payload builder**

Append to `frontend/src/components/worksheet/worksheetTable.ts` (extend imports with `import type { WorksheetExportPayload } from '../../api/worksheet';` and `noteFor` from `./worksheetColumns`):
```ts
/** What the xlsx gets: the visible columns (no images) and rows, in order, typed, with flags. */
export function buildExportPayload(
  cols: WorksheetColumn[], rows: WorksheetRow[], ctx: WorksheetContext,
): WorksheetExportPayload {
  const exported = cols.filter((c) => c.display !== 'thumbnail');
  return {
    columns: exported.map((c) => ({ key: c.key, label: c.label, type: c.exportType })),
    rows: rows.map((row) => ({
      cells: exported.map((c) => {
        const note = noteFor(c, row, ctx);
        return { value: c.value(row, ctx), flag: note?.flag_status ?? null, comments: note?.comment_count ?? 0 };
      }),
    })),
    frozen_columns: exported.filter((c) => c.frozenWidth).length,
  };
}
```

- [ ] **Step 4: Add the button**

In `WorksheetView.tsx`: import `downloadWorksheetXlsx` from `../../api/worksheet` and `buildExportPayload` from `./worksheetTable`; add
```tsx
  const exportXlsx = useMutation({
    mutationFn: () => downloadWorksheetXlsx(projectId, buildExportPayload(cols, shown, ctx)),
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not export the worksheet')),
  });
```
and replace the `{/* Task 15 puts the export button here */}` comment with:
```tsx
        <button type="button" data-testid="ws-export" disabled={exportXlsx.isPending || shown.length === 0}
          onClick={() => exportXlsx.mutate()}
          className="px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-600 text-white">
          {exportXlsx.isPending ? 'Exporting...' : 'Export xlsx'}
        </button>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/nitrolinux/claude/plm2-integ/frontend && npx vitest run src/components/worksheet`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add frontend/src/components/worksheet
git commit -m "feat(worksheet): export the visible worksheet as xlsx

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: 1994 import script (dry run default)

Source Excel: `/mnt/c/Users/christoph.demmler/OneDrive - KTX America Corporation/Desktop/Brose 1994 RFQ26 BOM clean with open points 2026-09-23.xlsx`, sheet `BOM`, header in row 3, data rows 4 to 15. Columns: A project, B tool no. (PLM), C cavities (PLM), D part no. (OEM, matches `parts.customer_part_number`), E BS part no. (Tier 1), F designation, G type, H drawing, I material acc. drawing, J proposed resin, K resin status, L painted, M color, N MIC / color change, O weight drawing, P weight RFQ, Q peak annual pcs, R open question, S answer, T grain drawing, U grain frozen RFQ 26, V gloss drawing, W grain question, X grain answer. Fills: yellow `FFFFFF00` open, green `FFC6EFCE` confirmed, salmon `FFF8CBAD` rejected. In `plm_integ` project 35 (code 1994) the tools are `199401` to `199413` and the articles carry the OEM numbers; PLM cavities are 2/2/4 for 199401/199402/199403 against the Excel's 4/4/2.

Mapping decisions (the spec says "on the matching part and field"):
- K resin status and J proposed resin: one comment on `part.material`, flag from K's fill.
- I: material `new` with the I text where the article has no material.
- C differs from the tool's `tool_cavities`: open flag and comment on the tool's `tool.cavities`; C yellow with no difference: open flag and a comment that the Excel marks it open. PLM is never overwritten.
- E: Tier 1 number set only for the four the spec lists, only where PLM has none.
- F yellow: comment on `part.name` with the drawing designation, open flag.
- L, M, N coloured cells: comment on `paint.painted` (L) or `paint.colour` (M, N) with the cell's flag.
- R/S question and answer: comment on the field they are about (`QUESTION_FIELD` below, default `paint.colour` since the 1994 questions are all about colour, paint or MIC), flag from S's fill (or R's).
- T to X grain: grain is not a PLM field (ruling: comments), and grain codes come from the drawing, so one comment on the article's `revision.level`, open flag when any grain cell is yellow.
- Weights and volume (O, P, Q): no comment (out of the spec's list).

**Files:**
- Create: `backend/scripts/import_1994_worksheet_notes.py`
- Test: `backend/tests/test_import_1994_worksheet_notes.py`

**Interfaces:**
- Consumes: `FieldNoteService.add_comment`, `.set_flag`, `.get` (Task 1); `PartMaterialService.set_new` (Task 5); `ChangelogService.log_action`.
- Produces: `read_rows(path) -> list[dict[str, Cell]]`, `async plan_actions(session, project_id, rows) -> tuple[list[Action], list[str]]`, `async apply_actions(session, actions, user_id) -> int`, `main()`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_import_1994_worksheet_notes.py`:
```python
"""The 1994 Excel import: plans comments, flags, material and Tier 1 numbers;
applies them once (a rerun adds nothing); never overwrites PLM cavities."""
import importlib.util
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import PatternFill
from sqlalchemy import select

from app.models.field_note import FieldNote
from app.models.part import Part

pytestmark = pytest.mark.asyncio

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_1994_worksheet_notes.py"
YELLOW, GREEN, SALMON = "FFFFFF00", "FFC6EFCE", "FFF8CBAD"


def _load():
    spec = importlib.util.spec_from_file_location("import_1994_worksheet_notes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _xlsx(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws["A1"] = "Brose Seat Trim 1994"
    ws.append([])
    ws.append(["Project", "Tool no. (PLM)", "Cavities (PLM)", "Part no.", "BS part no."])
    row4 = {"A": "1994", "B": "199401", "C": "4", "D": "206.882.251", "E": "S00H4X-110",
            "F": "Handle, height adjustment LH", "I": "PA6-GF15 acc. VW 50125",
            "J": "Polykemi REZYcom PA6 RB122 F15", "K": "NOT OK: recycled; virgin grade to nominate",
            "L": "no", "M": "NM0", "N": "no", "T": "KF8", "U": "Stipple 4", "V": "2 ±0.3"}
    row5 = {"A": "1994", "B": "199403", "C": "2", "D": "206.887.233", "E": "S00H54-110",
            "F": "Isofix Cover", "I": "PA6-GF15 acc. VW 50125", "J": "Polykemi REZYcom PA6 RB122 F15",
            "K": "NOT OK: recycled", "L": "no", "M": "NM0", "N": "no (confirmed)",
            "R": "1 or 3 colors?", "S": "Confirmed 2026-09-23: no MIC, NM0 only",
            "T": "KF8", "U": "Stipple 2", "V": "2 ±0.3", "W": "RFQ has Stipple 2, drawing KF8"}
    fills = {4: {"K": SALMON}, 5: {"C": YELLOW, "K": SALMON, "N": GREEN, "R": GREEN, "S": GREEN, "U": YELLOW, "W": YELLOW}}
    for r, data in ((4, row4), (5, row5)):
        for col, value in data.items():
            ws[f"{col}{r}"] = value
        for col, rgb in fills[r].items():
            ws[f"{col}{r}"].fill = PatternFill("solid", fgColor=rgb)
    path = tmp_path / "bom.xlsx"
    wb.save(path)
    return path


async def _parts(session_factory, seed):
    uid = seed["engineer_id"]
    async with session_factory() as s:
        def part(number, category, **kw):
            p = Part(project_id=seed["project_id"], part_number=number, name=number, part_type="internal_mfg",
                     item_category=category, created_by=uid, **kw)
            s.add(p)
            return p
        ids = {
            "lh": part("20-1994-001-0", "article", customer_part_number="206.882.251"),
            "iso": part("20-1994-005-0", "article", customer_part_number="206.887.233", tier1_part_number="S00H54-110"),
            "t01": part("199401", "tool", tool_cavities=2),
            "t03": part("199403", "tool", tool_cavities=4),
        }
        await s.commit()
        return {k: p.id for k, p in ids.items()}


async def test_plan_then_apply_once(session_factory, seed, tmp_path):
    mod = _load()
    ids = await _parts(session_factory, seed)
    rows = mod.read_rows(_xlsx(tmp_path))
    assert len(rows) == 2 and rows[1]["C"].flag == "open"

    async with session_factory() as s:
        actions, warnings = await mod.plan_actions(s, seed["project_id"], rows)
    assert warnings == []
    kinds = [(a.kind, a.part_id, a.field_key, a.flag) for a in actions]
    assert ("tier1", ids["lh"], None, None) in kinds
    assert not any(k == "tier1" and p == ids["iso"] for k, p, _, _ in kinds)  # already set in PLM
    assert ("material_new", ids["lh"], None, None) in kinds
    assert ("flag", ids["lh"], "part.material", "rejected") in kinds
    assert ("flag", ids["t01"], "tool.cavities", "open") in kinds
    assert ("flag", ids["t03"], "tool.cavities", "open") in kinds
    assert ("flag", ids["iso"], "paint.colour", "confirmed") in kinds
    assert ("flag", ids["iso"], "revision.level", "open") in kinds
    cav = [a.text for a in actions if a.kind == "comment" and a.field_key == "tool.cavities" and a.part_id == ids["t01"]]
    assert cav == ["Excel BOM 2026-09-23 says 4 cavities, PLM has 2. Check against RFQ 26 loop 37; PLM not changed."]

    async with session_factory() as s:
        written = await mod.apply_actions(s, actions, seed["engineer_id"])
        await s.commit()
    assert written == len(actions)
    async with session_factory() as s:
        lh = await s.get(Part, ids["lh"])
        t01 = await s.get(Part, ids["t01"])
        assert lh.tier1_part_number == "S00H4X-110"
        assert (lh.material_source, lh.material_new_text) == ("new", "PA6-GF15 acc. VW 50125")
        assert t01.tool_cavities == 2  # never overwritten
        notes = (await s.execute(select(FieldNote))).scalars().all()
        count = sum(len(n.comments) for n in notes)

    async with session_factory() as s:  # rerun: nothing new
        actions2, _ = await mod.plan_actions(s, seed["project_id"], rows)
        await mod.apply_actions(s, actions2, seed["engineer_id"])
        await s.commit()
        notes = (await s.execute(select(FieldNote))).scalars().all()
        assert sum(len(n.comments) for n in notes) == count
    assert not any(a.kind in ("tier1", "material_new") for a in actions2)


async def test_unknown_rows_are_warnings(session_factory, seed, tmp_path):
    mod = _load()
    rows = mod.read_rows(_xlsx(tmp_path))
    async with session_factory() as s:
        actions, warnings = await mod.plan_actions(s, seed["project_id"], rows)
    assert actions == []
    assert warnings == ["row 4: no article with OEM number 206.882.251", "row 5: no article with OEM number 206.887.233"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_import_1994_worksheet_notes.py -n 0 -q`
Expected: FAIL (`FileNotFoundError` for the script).

- [ ] **Step 3: Write the script**

`backend/scripts/import_1994_worksheet_notes.py`:
```python
"""One-time: turn the 1994 engineering Excel (Brose 1994 RFQ26 BOM clean with
open points 2026-09-23.xlsx, sheet BOM) into PLM field notes. Dry run by default.

    docker cp "<xlsx>" plm2-integ-backend:/tmp/bom-1994.xlsx
    docker exec -i -e PYTHONPATH=/app plm2-integ-backend \
        python scripts/import_1994_worksheet_notes.py --xlsx /tmp/bom-1994.xlsx [--user <id>] [--apply]

Per Excel row (article by the OEM number in column D, tool by column B):
- Tier 1 numbers: the four the Excel resolves, only where PLM has none.
- Material: new with the "Material acc. drawing" text where no material is set.
- Proposed resin and resin status: a comment on part.material, flag from the colour.
- Cavities differing from PLM (or marked yellow): open flag and a comment on the
  tool's tool.cavities; PLM cavities are never overwritten.
- Painted, colour, MIC cells with a colour: comments on paint.painted / paint.colour.
- Open question and answer: comments on the field they are about.
- Grain (drawing, frozen RFQ, gloss, question, answer): one comment on revision.level.
Colours: yellow = open, green = confirmed, salmon = rejected. A rerun skips
comments that already exist and flags that are already set.
"""
import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Optional

import openpyxl
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.field_note_service import FieldNoteService
from app.services.part_material_service import PartMaterialService
from app.services.part_service import ChangelogService

SHEET = "BOM"
FIRST_DATA_ROW = 4
FILL_FLAG = {"FFFFFF00": "open", "FFC6EFCE": "confirmed", "FFF8CBAD": "rejected"}
FLAG_RANK = {"confirmed": 1, "open": 2, "rejected": 3}  # the stronger flag wins on one field
TIER1 = {"206.882.251": "S00H4X-110", "206.882.252": "S00H4W-110",
         "206.885.967": "S00G0E-110", "206.885.968": "S00G0D-110"}
# Which field each row's open question (R/S) is about; default paint.colour.
QUESTION_FIELD = {"206.887.233": "paint.colour", "206.883.607": "paint.painted",
                  "206.881.479": "paint.colour", "206.881.793": "paint.colour"}


@dataclass
class Cell:
    value: object
    flag: Optional[str]


@dataclass
class Action:
    kind: str                 # tier1 | material_new | comment | flag
    part_id: int
    label: str                # part number, for the printout
    field_key: Optional[str] = None
    text: Optional[str] = None
    flag: Optional[str] = None


def _flag(cell) -> Optional[str]:
    fill = cell.fill
    if fill is None or fill.fill_type != "solid":
        return None
    rgb = fill.fgColor.rgb if fill.fgColor is not None else None
    return FILL_FLAG.get(rgb) if isinstance(rgb, str) else None


def read_rows(path) -> list[dict]:
    ws = openpyxl.load_workbook(path, data_only=True)[SHEET]
    rows = []
    for r in ws.iter_rows(min_row=FIRST_DATA_ROW):
        cells = {get_column_letter(c.column): Cell(c.value, _flag(c)) for c in r if c.value not in (None, "")}
        if "B" in cells and "D" in cells:
            cells["_row"] = Cell(r[0].row, None)
            rows.append(cells)
    return rows


def _s(cells: dict, col: str) -> str:
    c = cells.get(col)
    return str(c.value).strip() if c is not None and c.value is not None else ""


def _f(cells: dict, col: str) -> Optional[str]:
    c = cells.get(col)
    return c.flag if c is not None else None


async def plan_actions(session: AsyncSession, project_id: int, rows: list[dict]) -> tuple[list, list]:
    parts = (await session.execute(select(Part).where(Part.project_id == project_id))).scalars().all()
    articles = {p.customer_part_number: p for p in parts if p.item_category == "article" and p.customer_part_number}
    tools = {p.part_number: p for p in parts if p.item_category == "tool"}
    comments: list[Action] = []
    seen: set = set()
    flags: dict = {}
    other: list[Action] = []
    warnings: list[str] = []

    def want_flag(part: Part, key: str, flag: Optional[str]):
        current = flags.get((part.id, key), (None, None))[1]
        if flag and FLAG_RANK[flag] > FLAG_RANK.get(current, 0):
            flags[(part.id, key)] = (part, flag)

    def comment(part: Part, key: str, text: str, flag: Optional[str] = None):
        if (part.id, key, text) not in seen:
            seen.add((part.id, key, text))
            comments.append(Action("comment", part.id, part.part_number, key, text))
        want_flag(part, key, flag)

    for cells in rows:
        row_no = cells["_row"].value
        oem = _s(cells, "D")
        article = articles.get(oem)
        if article is None:
            warnings.append(f"row {row_no}: no article with OEM number {oem}")
            continue
        tool = tools.get(_s(cells, "B"))
        if tool is None:
            warnings.append(f"row {row_no}: no tool {_s(cells, 'B')}")

        if oem in TIER1 and not article.tier1_part_number:
            other.append(Action("tier1", article.id, article.part_number, text=TIER1[oem]))
        if _s(cells, "I") and article.material_source is None:
            other.append(Action("material_new", article.id, article.part_number, text=_s(cells, "I")))
        if _s(cells, "J") or _s(cells, "K"):
            comment(article, "part.material",
                    f"Proposed resin: {_s(cells, 'J') or 'none'}. Resin status: {_s(cells, 'K') or 'none'}",
                    _f(cells, "K") or _f(cells, "J"))
        if tool is not None and _s(cells, "C"):
            excel = int(float(_s(cells, "C")))
            if tool.tool_cavities is not None and excel != tool.tool_cavities:
                comment(tool, "tool.cavities",
                        f"Excel BOM 2026-09-23 says {excel} cavities, PLM has {tool.tool_cavities}. "
                        "Check against RFQ 26 loop 37; PLM not changed.", "open")
            elif _f(cells, "C") == "open":
                comment(tool, "tool.cavities", f"Excel BOM 2026-09-23 marks the cavities ({excel}) as open.", "open")
        if _f(cells, "F"):
            comment(article, "part.name", f"Designation on the drawing: {_s(cells, 'F')}", _f(cells, "F"))
        if _f(cells, "L"):
            comment(article, "paint.painted", f"Painted: {_s(cells, 'L')}", _f(cells, "L"))
        if _f(cells, "M"):
            comment(article, "paint.colour", f"Colour: {_s(cells, 'M')}", _f(cells, "M"))
        if _f(cells, "N"):
            comment(article, "paint.colour", f"MIC / colour change: {_s(cells, 'N')}", _f(cells, "N"))
        if _s(cells, "R") or _s(cells, "S"):
            key = QUESTION_FIELD.get(oem, "paint.colour")
            if _s(cells, "R"):
                comment(article, key, f"Question: {_s(cells, 'R')}")
            if _s(cells, "S"):
                comment(article, key, f"Answer: {_s(cells, 'S')}")
            want_flag(article, key, _f(cells, "S") or _f(cells, "R"))
        grain = [f"{label} {_s(cells, col)}" for col, label in
                 (("T", "drawing"), ("U", "RFQ 26 frozen"), ("V", "gloss"))
                 if _s(cells, col)]
        if grain or _s(cells, "W") or _s(cells, "X"):
            text = "Grain: " + ", ".join(grain) + "."
            if _s(cells, "W"):
                text += f" Question: {_s(cells, 'W')}"
            if _s(cells, "X"):
                text += f" Answer: {_s(cells, 'X')}"
            grain_flag = "open" if any(_f(cells, c) == "open" for c in "TUVWX") else None
            comment(article, "revision.level", text, grain_flag)

    flag_actions = [Action("flag", part.id, part.part_number, key[1], flag=flag)
                    for key, (part, flag) in flags.items()]
    return other + comments + flag_actions, warnings


async def apply_actions(session: AsyncSession, actions: list, user_id: int) -> int:
    written = 0
    for a in actions:
        part = await session.get(Part, a.part_id)
        if a.kind == "tier1":
            if part.tier1_part_number:
                continue
            old = part.tier1_part_number
            part.tier1_part_number = a.text
            await ChangelogService.log_action(
                session, part_id=part.id, action="metadata_updated",
                action_description=f"Tier 1 part number set to {a.text} from the 1994 Excel BOM 2026-09-23",
                performed_by=user_id, field_name="tier1_part_number", old_value=old, new_value=a.text)
        elif a.kind == "material_new":
            if part.material_source is not None:
                continue
            await PartMaterialService.set_new(session, part, a.text, user_id)
        elif a.kind == "comment":
            note = await FieldNoteService.get(session, part.id, a.field_key)
            if note is not None and any(c.body == a.text for c in note.comments):
                continue
            await FieldNoteService.add_comment(session, part, a.field_key, a.text, user_id)
        elif a.kind == "flag":
            note = await FieldNoteService.get(session, part.id, a.field_key)
            if note is not None and note.flag_status == a.flag:
                continue
            await FieldNoteService.set_flag(session, part, a.field_key, a.flag, user_id)
        written += 1
    await session.flush()
    return written


def _print(actions: list, warnings: list) -> None:
    for w in warnings:
        print(f"   ! {w}")
    for a in actions:
        if a.kind == "comment":
            print(f"   comment  {a.label:<16} {a.field_key:<22} {a.text}")
        elif a.kind == "flag":
            print(f"   flag     {a.label:<16} {a.field_key:<22} {a.flag}")
        else:
            print(f"   {a.kind:<8} {a.label:<16} {'':<22} {a.text}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, required=True, help="PLM user id the notes are written as")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.xlsx)
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        actions, warnings = await plan_actions(s, project.id, rows)
        print(f"{len(rows)} Excel rows, {len(actions)} actions for project {project.code} (id {project.id})")
        _print(actions, warnings)
        if not args.apply:
            print("DRY RUN - nothing written. Rerun with --apply after checking the list.")
            return
        written = await apply_actions(s, actions, args.user)
        await s.commit()
        print(f"Applied: {written} changes written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest tests/test_import_1994_worksheet_notes.py -n 0 -q`
Expected: PASS.

- [ ] **Step 5: Dry run against a copy of the integ database (no writes anywhere)**

The live `plm_integ` stays at 081 until Task 17 (do not restart `plm2-integ-backend` before then: its start command runs `alembic upgrade head`). The dry run needs 083, so it runs on a throwaway copy:
```bash
docker cp "/mnt/c/Users/christoph.demmler/OneDrive - KTX America Corporation/Desktop/Brose 1994 RFQ26 BOM clean with open points 2026-09-23.xlsx" plm2-integ-backend:/tmp/bom-1994.xlsx
docker exec claude-plm2-db-1 dropdb -U plm --if-exists plm_integ_importdry
docker exec claude-plm2-db-1 createdb -U plm plm_integ_importdry
docker exec claude-plm2-db-1 sh -c 'pg_dump -U plm plm_integ | psql -q -U plm -d plm_integ_importdry' > /dev/null
URL=postgresql+asyncpg://plm:plm@plm2-db:5432/plm_integ_importdry
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic upgrade head
docker exec claude-plm2-db-1 psql -U plm -d plm_integ_importdry -c "select id, email from users order by id limit 10"
docker exec -i -e PYTHONPATH=/app -e DATABASE_URL=$URL plm2-integ-backend \
  python scripts/import_1994_worksheet_notes.py --xlsx /tmp/bom-1994.xlsx --user <an id from the list>
docker exec claude-plm2-db-1 dropdb -U plm plm_integ_importdry
```
Expected: `12 Excel rows ... for project 1994 (id 35)`, no `!` warnings (all twelve OEM numbers exist in project 35), four `tier1` actions (206.882.251/.252, 206.885.967/.968), twelve `material_new` actions, open `tool.cavities` flags with a difference comment for 199401, 199402 (Excel 4, PLM 2) and 199403 (Excel 2, PLM 4), open flags for the yellow cavities of 199404, 199409, 199410, and the last line `DRY RUN - nothing written. ...`.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add backend/scripts/import_1994_worksheet_notes.py backend/tests/test_import_1994_worksheet_notes.py
git commit -m "feat(scripts): import the 1994 Excel open points as field notes, dry run by default

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 17: Verification

**Files:** none new (fixes go into the task that owns the code, committed separately).

- [ ] **Step 1: Backend suite**

Run: `cd /home/nitrolinux/claude/plm2-integ/backend && python3 -m pytest -q`
Expected: all PASS (xdist on), including `test_field_notes.py`, `test_field_notes_api.py`, `test_part_material.py`, `test_materialdb_search.py`, `test_worksheet.py`, `test_worksheet_export.py`, `test_import_1994_worksheet_notes.py`.

- [ ] **Step 2: Frontend suite, types, lint on touched files**

```bash
cd /home/nitrolinux/claude/plm2-integ/frontend
npx vitest run
npx tsc --noEmit
npx eslint --max-warnings 0 --report-unused-disable-directives \
  src/api/fieldNotes.ts src/api/materials.ts src/api/worksheet.ts \
  src/hooks/queries/useFieldNotes.ts src/hooks/queries/useWorksheet.ts src/hooks/useFieldFocus.ts \
  src/lib/fieldNotes.ts src/lib/material.ts \
  src/components/fieldNotes src/components/materials src/components/worksheet \
  src/pages/PartDetail.tsx src/pages/ToolDetail.tsx src/pages/ProjectDetailPage.tsx \
  src/components/tools/ToolFieldsCard.tsx src/components/paint/PartPaintCard.tsx src/components/project/ItemsPane.tsx
```
Expected: vitest all PASS, tsc clean, eslint 0 problems (in particular no `react-refresh/only-export-components` warning: every `.tsx` exports only components and types).

- [ ] **Step 3: No em dashes in what this branch added**

Run: `cd /home/nitrolinux/claude/plm2-integ && git diff main --unified=0 -- backend frontend/src | grep '^+' | grep -nP '\x{2014}' ; git log main..HEAD --format=%B | grep -nP '\x{2014}'`
Expected: no output from either command.

- [ ] **Step 4: Migrations up and down on a scratch SQLite DB**

```bash
cd /home/nitrolinux/claude/plm2-integ/backend
DB=sqlite+aiosqlite:////tmp/claude-1000/-home-nitrolinux-claude-plm2/682e27d6-86ce-49d1-8aa2-d85ccfa61993/scratchpad/verify-ws.db
rm -f /tmp/claude-1000/-home-nitrolinux-claude-plm2/682e27d6-86ce-49d1-8aa2-d85ccfa61993/scratchpad/verify-ws.db
DATABASE_URL=$DB python3 -m alembic upgrade head
DATABASE_URL=$DB python3 -m alembic downgrade 081
DATABASE_URL=$DB python3 -m alembic upgrade head
DATABASE_URL=$DB python3 -m alembic upgrade head
DATABASE_URL=$DB python3 -m alembic current
```
Expected: ends at `083 (head)`, no errors on the downgrade, the second upgrade is a no-op.

- [ ] **Step 5: Migrations up and down on a dump copy of plm_integ (Postgres)**

```bash
docker exec claude-plm2-db-1 dropdb -U plm --if-exists plm_integ_migcheck
docker exec claude-plm2-db-1 createdb -U plm plm_integ_migcheck
docker exec claude-plm2-db-1 sh -c 'pg_dump -U plm plm_integ | psql -q -U plm -d plm_integ_migcheck' > /dev/null
URL=postgresql+asyncpg://plm:plm@plm2-db:5432/plm_integ_migcheck
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic current
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic downgrade 081
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic upgrade head
docker exec claude-plm2-db-1 psql -U plm -d plm_integ_migcheck -c "\d field_notes" -c "select count(*) from parts where material_source is not null"
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic downgrade 081
docker exec claude-plm2-db-1 psql -U plm -d plm_integ_migcheck -c "select count(*) from parts" -c "\d field_notes"
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic upgrade head
docker exec -e DATABASE_URL=$URL plm2-integ-backend alembic current
docker exec claude-plm2-db-1 dropdb -U plm plm_integ_migcheck
```
Expected: `current` shows `081` (if someone restarted the integ backend earlier it shows `083`; the first `downgrade 081` then brings the copy back so the upgrade is still exercised on real data); upgrade to `083 (head)`; `\d field_notes` shows the table with `uq_field_note_part_field`; material count 0; after the second downgrade the parts count is unchanged and `\d field_notes` reports `Did not find any relation`; the final upgrade ends at `083 (head)`; the scratch database is dropped. The live `plm_integ` is not touched in this step.

- [ ] **Step 6: Apply to the integ stack and run the 1994 import**

```bash
docker exec plm2-integ-backend alembic upgrade head
docker restart plm2-integ-backend
docker exec claude-plm2-db-1 psql -U plm -d plm_integ -c "select id, email from users order by id limit 10"
docker exec -i -e PYTHONPATH=/app plm2-integ-backend python scripts/import_1994_worksheet_notes.py --xlsx /tmp/bom-1994.xlsx --user <your user id>
```
Show the dry-run list to the user. Only after they confirm, rerun with `--apply` (plm_integ is the local test database, not production). Without confirmation, continue the browser check with notes created by hand.

- [ ] **Step 7: Browser check on http://localhost:5181/plm2/projects/35**

Use the `playwright-cli` skill (the integ Vite server auto-logs in). Do not stop the Vite server.
1. Open `http://localhost:5181/plm2/projects/35`; click "Worksheet" in the items header: the URL gains `?view=worksheet`, the table is full width, no detail pane.
2. Rows: one per 1994 article, sorted by KTX number; the first three columns (image, KTX no., OEM no.) stay put when scrolling right; Tool no., Cavities (2 for 199401), DFM column shows a status.
3. Tick "Purchased parts" and "Tools without article": tool rows 199411 to 199413 appear.
4. Filter Name with `cover`, sort by Cavities twice, hide "Toolmaker" via Columns, reload: Toolmaker stays hidden.
5. Right click the Cavities cell of 20-1994-001-0, "Flag open": the cell turns yellow; the row of 20-1994-002-0 (same tool 199401) is yellow in Cavities too. "Comment", add "Excel says 4"; the marker shows 1.
6. Tick "Only rows with open flags": only the flagged rows remain.
7. Right click that cell, "Edit": the tool page `/plm2/parts/2295?focus=tool.cavities` opens, the Cavities field is ringed and focused, its marker is yellow with count 1. Back to the worksheet.
8. Right click the Material cell of 20-1994-005-0, "Edit": the article page with the Material field ringed; "Change", "New material, not in MaterialDB", enter `PA6-GF15 acc. VW 50125`, Save: the amber `NEW, not in MaterialDB` badge shows; the worksheet shows the same after going back.
9. "Change", "From MaterialDB", type `pa6`: with MATERIALDB_* unset on the integ backend, the amber message says MaterialDB is not configured (503) and nothing breaks.
10. "Export xlsx": a file `1994-worksheet-<date>.xlsx` downloads; open it with openpyxl in the scratchpad and check the header, a typed Cavities number, the yellow fill on the flagged cell, and `freeze_panes == "C2"`.
11. Changelog of tool 199401 lists `field flag set` and `field comment added`.
Take one screenshot of the worksheet with flags into the scratchpad for the report.

- [ ] **Step 8: Record the outcome**

Append to `memory/1994-brose-volume-sheet-2026-09-23.md` (project-root memory, per `CLAUDE.md`):
```markdown
**Project worksheet (plan docs/superpowers/plans/2026-09-24-project-worksheet.md):**
alembic 082 (field_notes, field_note_comments) and 083 (material columns on parts);
`/api/v1/parts/{id}/field-notes/...`, `/api/v1/projects/{id}/field-notes`, `/api/v1/materials/search`,
`/api/v1/parts/{id}/material`, `/api/v1/projects/{id}/worksheet` (+ `/export`). Worksheet at
`/projects/<id>?view=worksheet`. MaterialDB link needs MATERIALDB_BASE_URL and MATERIALDB_SERVICE_TOKEN
on the PLM backend. Prod: back up, `alembic upgrade head`, then
`scripts/import_1994_worksheet_notes.py --xlsx ... --user <id>` dry run, `--apply` after review.
```
Update the spec status line to `Status: design approved in chat; implemented per plan 2026-09-24-project-worksheet.md.`

- [ ] **Step 9: Commit**

```bash
cd /home/nitrolinux/claude/plm2-integ
git add memory/1994-brose-volume-sheet-2026-09-23.md docs/superpowers/specs/2026-09-24-project-worksheet-design.md
git commit -m "docs(memory): project worksheet, field notes and linked material shipped

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Never stage `frontend/vite.integ.config.ts`.
