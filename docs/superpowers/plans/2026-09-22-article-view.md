# Article View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project page's article panel read like a PLM revision browser: revision strip with proposals, one document pane for 3D or PDF, grouped files with "Open", mirror parts shown as relations with a red warning, and an expandable structure tree on the left.

**Architecture:** Backend adds a `mirror_of` relation type with rules, an inline document route, and one project structure endpoint (revisions + related parts per article, batched queries). Frontend adds three focused components (`RevisionStrip`, `DocumentPane`, `RevisionFilesGrouped`) plus a structure hook, then wires them into `ProjectDetailPage` and `PartDetail`.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (no migration needed), React + TanStack Query v5 + Tailwind + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-22-article-view-design.md`

## Global Constraints

- Mirrors are never copied. A mirror is a `part_relations` row `relation_type="mirror_of"` from the mirror to the source. Labels: outgoing "mirror of", incoming "mirrored by". Rules: one mirror per part, no self-mirror, both parts articles of the same project; violations → 400 (self, cross-project, non-article) or 409 (second mirror).
- Red banner text on a mirror fallback: `Mirrored part. Showing {source number} ({source name}). Geometry is the mirror image, RPS and references differ.`
- Inline route: `GET /api/v1/parts/revision-files/{file_id}/inline`, `Content-Disposition: inline`, media type from `MIME_MAP` by extension; allowed extensions `.pdf .png .jpg .jpeg .gif .webp`; others → 415. Same 404 rules as download.
- Structure endpoint: `GET /api/v1/parts/project/{project_id}/structure`, at most 4 SQL queries regardless of part count.
- Revision strip: majors are revisions with `parent_revision_id == null`, ordered as `groupByMajor` from `components/parts/revisionGrouping.ts` orders them; minors nested under their major.
- File groups: **3D** = `file_type === 'cad'`; **2D** = `file_type === 'drawing'`; **Documents** = everything else. "Open" only for `mime_type` `application/pdf` or `image/*`.
- Backend tests: `cd backend && uv run pytest <file> -q`. Frontend: `cd frontend && npx vitest run <file>`; `npx tsc --noEmit`. Existing tests stay green.
- Commit after every task, no pushes. Commit messages end with a blank line then `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: `mirror_of` relation type with rules

**Files:**
- Modify: `backend/app/api/v1/items/part_relations.py` (`VALID_RELATION_TYPES` line 19, `RELATION_LABELS` lines 23-33, `create_relation` lines 57-124)
- Test: `backend/tests/test_mirror_relation.py`

**Interfaces:**
- Produces: `POST /api/v1/parts/{mirror_id}/relations {to_part_id: source_id, relation_type: "mirror_of"}` → 201 row with `label == "mirror of"`; from the source `GET /relations` shows `label == "mirrored by"`.

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_mirror_relation.py
async def _create(client, auth, seed, number, name, item_category="article", project_id=None):
    res = await client.post("/api/v1/parts", headers=auth, json={
        "project_id": project_id or seed["project_id"], "part_number": number, "name": name,
        "part_type": "internal_mfg", "data_classification": "confidential", "item_category": item_category})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _mirror(client, auth, mirror, source):
    return await client.post(f"/api/v1/parts/{mirror}/relations", headers=auth,
                             json={"to_part_id": source, "relation_type": "mirror_of"})


async def test_mirror_roundtrip_labels(client, eng_auth, seed):
    lh = await _create(client, eng_auth, seed, "20-1", "Handle LH")
    rh = await _create(client, eng_auth, seed, "20-2", "Handle RH")
    r = await _mirror(client, eng_auth, rh, lh)
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "mirror of"
    src = (await client.get(f"/api/v1/parts/{lh}/relations", headers=eng_auth)).json()
    assert [(x["label"], x["other_part_number"]) for x in src] == [("mirrored by", "20-2")]
    mir = (await client.get(f"/api/v1/parts/{rh}/relations", headers=eng_auth)).json()
    assert [(x["label"], x["other_part_number"]) for x in mir] == [("mirror of", "20-1")]


async def test_one_mirror_per_part(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "20-1", "A")
    b = await _create(client, eng_auth, seed, "20-2", "B")
    c = await _create(client, eng_auth, seed, "20-3", "C")
    assert (await _mirror(client, eng_auth, b, a)).status_code == 201
    r = await _mirror(client, eng_auth, b, c)
    assert r.status_code == 409
    assert "already a mirror" in r.json()["detail"]


async def test_mirror_must_be_articles(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "20-1", "A")
    tool = await _create(client, eng_auth, seed, "T-1", "Tool", item_category="tool")
    r = await _mirror(client, eng_auth, tool, a)
    assert r.status_code == 400
    assert "articles" in r.json()["detail"]


async def test_mirror_chain_is_refused(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "20-1", "A")
    b = await _create(client, eng_auth, seed, "20-2", "B")
    c = await _create(client, eng_auth, seed, "20-3", "C")
    assert (await _mirror(client, eng_auth, b, a)).status_code == 201
    r = await _mirror(client, eng_auth, c, b)
    assert r.status_code == 400
    assert "itself a mirror" in r.json()["detail"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_mirror_relation.py -q`
Expected: FAIL (400 Invalid relation_type).

- [ ] **Step 3: Implement**

In `part_relations.py`:

```python
VALID_RELATION_TYPES = {"produces", "checks", "assembles", "related", "serves", "feeds", "mirror_of"}
```

Add to `RELATION_LABELS`: `"mirror_of": ("mirror of", "mirrored by"),`.

In `create_relation`, after the same-project check and before the duplicate check:

```python
        if body.relation_type == "mirror_of":
            if from_part.item_category != "article" or to_part.item_category != "article":
                raise HTTPException(status_code=400, detail="Only articles can be mirrors of articles")
            already = await db.execute(select(PartRelation).where(
                PartRelation.from_part_id == part_id, PartRelation.relation_type == "mirror_of"))
            if already.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="This part is already a mirror of another part")
            source_is_mirror = await db.execute(select(PartRelation).where(
                PartRelation.from_part_id == body.to_part_id, PartRelation.relation_type == "mirror_of"))
            if source_is_mirror.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="The source part is itself a mirror; point at the part that holds the data")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_mirror_relation.py tests/test_part_relations.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/items/part_relations.py backend/tests/test_mirror_relation.py
git commit -m "feat(relations): mirror_of relation type - one mirror per article, no chains"
```

---

### Task 2: Inline document route

**Files:**
- Modify: `backend/app/api/v1/items/revision_files.py` (next to the download route, line ~374)
- Test: `backend/tests/test_revision_file_inline.py`

**Interfaces:**
- Produces: `GET /api/v1/parts/revision-files/{file_id}/inline` → `FileResponse` with `content-disposition: inline; filename=…` and the real media type; 415 for other types; 404 for unknown or soft-deleted files.

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_revision_file_inline.py
async def _upload(client, auth, part, name, payload, ctype, file_type=None):
    data = {"file_type": file_type} if file_type else {}
    r = await client.post(f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
                          files={"file": (name, payload, ctype)}, data=data, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_inline_pdf_is_served_inline(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "drawing.pdf", b"%PDF-1.4 x", "application/pdf", "drawing")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.content == b"%PDF-1.4 x"


async def test_inline_picture(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "photo.png", b"\x89PNG", "image/png")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


async def test_inline_refuses_other_types(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "model.stp", b"ISO-10303-21;", "application/step")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 415


async def test_inline_unknown_and_deleted(client, eng_auth, part):
    assert (await client.get("/api/v1/parts/revision-files/999999/inline")).status_code == 404
    fid = await _upload(client, eng_auth, part, "d.pdf", b"%PDF-1.4 y", "application/pdf", "drawing")
    assert (await client.delete(f"/api/v1/parts/revision-files/{fid}", headers=eng_auth)).status_code == 200
    assert (await client.get(f"/api/v1/parts/revision-files/{fid}/inline")).status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_revision_file_inline.py -q`
Expected: FAIL (404 on the route).

- [ ] **Step 3: Implement**

Add after the download route:

```python
INLINE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


@router.get("/revision-files/{file_id}/inline")
async def inline_revision_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve a drawing PDF or a picture for display in the app (not as a download)."""
    rev_file = await _get_file_or_404(db, file_id)
    ext = os.path.splitext(rev_file.filename)[1].lower()
    if ext not in INLINE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only PDF and pictures can be shown inline")
    if not os.path.exists(rev_file.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return FileResponse(
        path=rev_file.file_path,
        media_type=MIME_MAP.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{rev_file.filename}"'},
    )
```

Import `MIME_MAP` from `app.services.revision_file_service` (the file already imports `store_revision_file` from there; extend that import). Note: `FileResponse(filename=...)` would force `attachment`, so pass the header explicitly and omit `filename`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_revision_file_inline.py tests/test_revision_file_note.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/items/revision_files.py backend/tests/test_revision_file_inline.py
git commit -m "feat(files): inline route serves PDFs and pictures for in-app display"
```

---

### Task 3: Project structure endpoint

**Files:**
- Create: `backend/app/services/project_structure_service.py`
- Modify: `backend/app/api/v1/items/parts.py` (add route next to `GET /project/{project_id}`, line 78)
- Test: `backend/tests/test_project_structure.py`

**Interfaces:**
- Produces: `GET /api/v1/parts/project/{project_id}/structure` →
  ```json
  {"articles": [{
     "part_id": 1, "part_number": "20-1994-001-0", "customer_part_number": "206.882.251",
     "name": "...", "lifecycle_phase": "nominated", "active_revision_id": 9,
     "revisions": [{"id": 9, "revision_name": "E1", "customer_index": "003", "status": "approved",
                    "phase": "review", "parent_revision_id": null, "is_active": true}],
     "related": [{"relation_type": "produces", "direction": "incoming", "label": "produced by",
                  "part_id": 30, "part_number": "199401", "name": "...", "item_category": "tool"}],
     "mirror_of": {"part_id": 2, "part_number": "…", "customer_part_number": "…", "name": "…"} | null,
     "mirrored_by": [{"part_id": …, "part_number": …, "customer_part_number": …, "name": …}]
  }]}
  ```
  Articles ordered by `part_number`; revisions by `created_at`; related by `relation_type, part_number`. Only `item_category == "article"` parts appear as articles; `related` excludes `mirror_of` rows (they go to `mirror_of` / `mirrored_by`).

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_project_structure.py
async def _create(client, auth, seed, number, name, item_category="article"):
    res = await client.post("/api/v1/parts", headers=auth, json={
        "project_id": seed["project_id"], "part_number": number, "name": name,
        "part_type": "internal_mfg", "data_classification": "confidential", "item_category": item_category,
        "customer_part_number": f"C-{number}"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _customer_data(client, auth, pid, index):
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=auth,
                          json={"statement": "review", "received_at": "2026-05-28", "customer_index": index})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_structure_lists_articles_with_revisions_related_and_mirrors(client, eng_auth, seed):
    lh = await _create(client, eng_auth, seed, "20-1", "Handle LH")
    rh = await _create(client, eng_auth, seed, "20-2", "Handle RH")
    tool = await _create(client, eng_auth, seed, "T-1", "Tool", "tool")
    e1 = await _customer_data(client, eng_auth, lh, "003")
    r = await client.post(f"/api/v1/parts/{lh}/revisions/proposals", headers=eng_auth,
                          json={"parent_revision_id": e1, "summary": "investigation"})
    assert r.status_code in (200, 201), r.text
    for target in (lh, rh):
        assert (await client.post(f"/api/v1/parts/{tool}/relations", headers=eng_auth,
                                  json={"to_part_id": target, "relation_type": "produces"})).status_code == 201
    assert (await client.post(f"/api/v1/parts/{rh}/relations", headers=eng_auth,
                              json={"to_part_id": lh, "relation_type": "mirror_of"})).status_code == 201

    res = await client.get(f"/api/v1/parts/project/{seed['project_id']}/structure", headers=eng_auth)
    assert res.status_code == 200, res.text
    arts = {a["part_number"]: a for a in res.json()["articles"]}
    assert list(arts) == ["20-1", "20-2"]  # the tool is not an article
    a = arts["20-1"]
    assert [(x["revision_name"], x["customer_index"], x["parent_revision_id"] is None, x["is_active"]) for x in a["revisions"]] == [
        ("E1", "003", True, True), ("E1.1", None, False, False)]
    assert [(x["label"], x["part_number"], x["item_category"]) for x in a["related"]] == [("produced by", "T-1", "tool")]
    assert a["mirror_of"] is None
    assert [m["part_number"] for m in a["mirrored_by"]] == ["20-2"]
    b = arts["20-2"]
    assert b["mirror_of"]["part_number"] == "20-1"
    assert b["mirror_of"]["customer_part_number"] == "C-20-1"
    assert b["mirrored_by"] == []
    assert b["revisions"] == []


async def test_structure_unknown_project_is_empty(client, eng_auth):
    res = await client.get("/api/v1/parts/project/999999/structure", headers=eng_auth)
    assert res.status_code == 200
    assert res.json() == {"articles": []}


async def test_structure_query_count_is_bounded(client, eng_auth, seed, session_factory):
    from sqlalchemy import event
    from app.models.database import engine as app_engine  # adjust to the engine object the app uses (see conftest db_engine)
    for i in range(6):
        pid = await _create(client, eng_auth, seed, f"20-{i}", f"P{i}")
        await _customer_data(client, eng_auth, pid, "001")
    count = {"n": 0}
    def _count(*_a, **_k):
        count["n"] += 1
    sync_engine = session_factory.kw["bind"].sync_engine
    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        res = await client.get(f"/api/v1/parts/project/{seed['project_id']}/structure", headers=eng_auth)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)
    assert res.status_code == 200
    assert count["n"] <= 6, count  # auth lookup + ≤ 4 structure queries + slack
```

For the query-count test: read `backend/tests/conftest.py:20-33` to see how `session_factory` is built (`async_sessionmaker(bind=engine)`), and adapt `sync_engine = session_factory.kw["bind"].sync_engine` to the real attribute. Drop the unused `app_engine` import line. If counting proves impractical in this harness, replace the test with one that asserts the service issues exactly the four statements by mocking `session.execute` calls count — but try the event listener first.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_project_structure.py -q`
Expected: FAIL (404).

- [ ] **Step 3: Service**

```python
# backend/app/services/project_structure_service.py
"""One call for the project page's structure tree: every article with its
revisions, its related tools/gauges/equipment, and its mirror links.
Four queries regardless of project size."""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_relations import RELATION_LABELS
from app.models.part import Part, PartRelation, PartRevision


def _brief(p: Part) -> dict:
    return {"part_id": p.id, "part_number": p.part_number,
            "customer_part_number": p.customer_part_number, "name": p.name}


async def project_structure(session: AsyncSession, project_id: int) -> dict:
    parts = (await session.execute(
        select(Part).where(Part.project_id == project_id).order_by(Part.part_number))).scalars().all()
    if not parts:
        return {"articles": []}
    by_id = {p.id: p for p in parts}
    article_ids = [p.id for p in parts if p.item_category == "article"]
    revs = (await session.execute(
        select(PartRevision).where(PartRevision.part_id.in_(article_ids))
        .order_by(PartRevision.created_at))).scalars().all()
    rels = (await session.execute(
        select(PartRelation).where(
            (PartRelation.from_part_id.in_(list(by_id))) | (PartRelation.to_part_id.in_(list(by_id))))
        .order_by(PartRelation.relation_type, PartRelation.id))).scalars().all()

    revs_by_part: dict[int, list] = defaultdict(list)
    for r in revs:
        revs_by_part[r.part_id].append(r)
    related: dict[int, list] = defaultdict(list)
    mirror_of: dict[int, dict] = {}
    mirrored_by: dict[int, list] = defaultdict(list)
    for r in rels:
        src, dst = by_id.get(r.from_part_id), by_id.get(r.to_part_id)
        if src is None or dst is None:
            continue  # relation into another project's part: not part of this tree
        if r.relation_type == "mirror_of":
            mirror_of[src.id] = _brief(dst)
            mirrored_by[dst.id].append(_brief(src))
            continue
        fwd, back = RELATION_LABELS.get(r.relation_type, (r.relation_type, r.relation_type))
        related[src.id].append({"relation_type": r.relation_type, "direction": "outgoing", "label": fwd,
                                "part_id": dst.id, "part_number": dst.part_number, "name": dst.name,
                                "item_category": dst.item_category})
        related[dst.id].append({"relation_type": r.relation_type, "direction": "incoming", "label": back,
                                "part_id": src.id, "part_number": src.part_number, "name": src.name,
                                "item_category": src.item_category})

    articles = []
    for p in parts:
        if p.item_category != "article":
            continue
        articles.append({
            **_brief(p), "lifecycle_phase": p.lifecycle_phase, "active_revision_id": p.active_revision_id,
            "revisions": [{
                "id": r.id, "revision_name": r.revision_name, "customer_index": r.customer_index,
                "status": r.status.value if hasattr(r.status, "value") else r.status,
                "phase": r.phase.value if hasattr(r.phase, "value") else r.phase,
                "parent_revision_id": r.parent_revision_id, "is_active": r.id == p.active_revision_id,
            } for r in revs_by_part.get(p.id, [])],
            "related": sorted(related.get(p.id, []), key=lambda x: (x["relation_type"], x["part_number"])),
            "mirror_of": mirror_of.get(p.id),
            "mirrored_by": mirrored_by.get(p.id, []),
        })
    return {"articles": articles}
```

That is three queries; the auth dependency adds one. If importing `RELATION_LABELS` from the API module creates a circular import, move `RELATION_LABELS` and `VALID_RELATION_TYPES` into a new `backend/app/services/relation_labels.py` and import them from both places.

- [ ] **Step 4: Route**

In `backend/app/api/v1/items/parts.py`, after `get_project_parts`:

```python
@router.get("/project/{project_id}/structure", response_model=dict)
async def get_project_structure(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Articles with revisions, related tools/gauges/equipment and mirror links, in one call."""
    return await project_structure(db, project_id)
```

with `from app.services.project_structure_service import project_structure`.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_project_structure.py tests/test_part_relations.py tests/test_mirror_relation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/project_structure_service.py backend/app/api/v1/items/parts.py backend/tests/test_project_structure.py
git commit -m "feat(parts): project structure endpoint - articles with revisions, related items, mirrors"
```

---

### Task 4: `RevisionStrip` component

**Files:**
- Create: `frontend/src/components/parts/RevisionStrip.tsx`
- Test: `frontend/src/components/parts/RevisionStrip.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export interface StripRevision { id: number; revision_name: string; customer_index?: string | null; status: string; phase: 'review' | 'official'; parent_revision_id?: number | null }
  export default function RevisionStrip(props: { revisions: StripRevision[]; selectedId: number | null; activeId: number | null; onSelect(id: number): void; onNewProposal?(majorId: number): void }): JSX.Element
  ```
- Consumes: `groupByMajor` from `./revisionGrouping` (needs `Revision` shape: pass through, the extra fields `source`, `part_phase_at_receipt`, `created_at` are optional for grouping purposes; if `groupByMajor`'s type requires them, widen its parameter type to `Pick<Revision, 'id' | 'revision_name' | 'phase' | 'status' | 'parent_revision_id' | 'customer_index'>` and keep its tests green), `revisionLabel` from `./RevisionBadge`.

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/components/parts/RevisionStrip.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import RevisionStrip from './RevisionStrip'

const revs = [
  { id: 1, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review' as const, parent_revision_id: null },
  { id: 2, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review' as const, parent_revision_id: 1 },
  { id: 3, revision_name: 'E2', customer_index: '004', status: 'approved', phase: 'review' as const, parent_revision_id: null },
]

describe('RevisionStrip', () => {
  afterEach(cleanup)

  it('renders majors as tabs with minors nested and marks active and selected', () => {
    render(<RevisionStrip revisions={revs} selectedId={2} activeId={3} onSelect={() => {}} />)
    const e1 = screen.getByTestId('rev-tab-1')
    const e11 = screen.getByTestId('rev-tab-2')
    const e2 = screen.getByTestId('rev-tab-3')
    expect(e1.textContent).toContain('E1 · 003')
    expect(e11.textContent).toContain('E1.1')
    expect(e11.textContent).toContain('proposal')
    expect(e2.textContent).toContain('active')
    expect(e11.getAttribute('aria-selected')).toBe('true')
    expect(e1.getAttribute('aria-selected')).toBe('false')
    // minor sits inside its major's group
    expect(screen.getByTestId('rev-group-1').contains(e11)).toBe(true)
  })

  it('selects on click and offers a proposal on the selected major', () => {
    const onSelect = vi.fn(); const onNew = vi.fn()
    render(<RevisionStrip revisions={revs} selectedId={1} activeId={1} onSelect={onSelect} onNewProposal={onNew} />)
    fireEvent.click(screen.getByTestId('rev-tab-3'))
    expect(onSelect).toHaveBeenCalledWith(3)
    fireEvent.click(screen.getByText('+ Proposal'))
    expect(onNew).toHaveBeenCalledWith(1)
  })

  it('greys frozen and rejected revisions', () => {
    render(<RevisionStrip revisions={[{ ...revs[0], status: 'frozen' }, { ...revs[1], status: 'rejected' }]} selectedId={1} activeId={1} onSelect={() => {}} />)
    expect(screen.getByTestId('rev-tab-1').className).toContain('opacity-')
    expect(screen.getByTestId('rev-tab-2').className).toContain('line-through')
  })

  it('renders nothing for no revisions', () => {
    const { container } = render(<RevisionStrip revisions={[]} selectedId={null} activeId={null} onSelect={() => {}} />)
    expect(container.textContent).toContain('No revisions')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/parts/RevisionStrip.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/parts/RevisionStrip.tsx
/**
 * RevisionStrip - majors as tabs (E1 · 003, E2 · 004, 1), each with its
 * proposals nested under it (E1.1). Replaces the flat revision dropdown so a
 * proposal is visible as a proposal. E numbers are our filing order; the
 * customer index is shown next to them.
 */
import { groupByMajor } from './revisionGrouping';
import { revisionLabel } from './RevisionBadge';

export interface StripRevision {
  id: number;
  revision_name: string;
  customer_index?: string | null;
  status: string;
  phase: 'review' | 'official';
  parent_revision_id?: number | null;
}

interface Props {
  revisions: StripRevision[];
  selectedId: number | null;
  activeId: number | null;
  onSelect(id: number): void;
  onNewProposal?(majorId: number): void;
}

const DEAD = new Set(['rejected', 'cancelled', 'archived']);

function tabClass(rev: StripRevision, selected: boolean, minor: boolean): string {
  const base = minor ? 'px-2 py-0.5 text-xs rounded' : 'px-3 py-1 text-sm rounded-t border-b-2';
  const tone = selected
    ? 'bg-slate-700 text-white border-blue-500'
    : 'text-slate-300 hover:bg-slate-700/60 border-transparent';
  const state = DEAD.has(rev.status) ? 'line-through opacity-60' : rev.status === 'frozen' ? 'opacity-70' : '';
  return `${base} ${tone} ${state}`;
}

export default function RevisionStrip({ revisions, selectedId, activeId, onSelect, onNewProposal }: Props) {
  if (revisions.length === 0) return <p className="text-xs text-slate-500 px-2 py-1">No revisions yet</p>;
  const groups = groupByMajor(revisions as never);
  return (
    <div className="flex flex-wrap items-end gap-3 px-2 py-1" role="tablist">
      {groups.map(({ major, minors }) => {
        const majorSelected = selectedId === major.id;
        return (
          <div key={major.id} data-testid={`rev-group-${major.id}`} className="flex flex-col gap-1">
            <button role="tab" aria-selected={majorSelected} data-testid={`rev-tab-${major.id}`}
              onClick={() => onSelect(major.id)} className={tabClass(major as StripRevision, majorSelected, false)}>
              {revisionLabel(major.revision_name, major.customer_index)}
              {activeId === major.id && <span className="ml-1 text-[10px] uppercase text-green-400">active</span>}
              <span className="ml-1 text-[10px] text-slate-500">{major.status.replace(/_/g, ' ')}</span>
            </button>
            {(minors.length > 0 || (onNewProposal && majorSelected)) && (
              <div className="flex items-center gap-1 pl-2">
                {minors.map((m) => (
                  <button key={m.id} role="tab" aria-selected={selectedId === m.id} data-testid={`rev-tab-${m.id}`}
                    onClick={() => onSelect(m.id)} className={tabClass(m as StripRevision, selectedId === m.id, true)}>
                    {m.revision_name}
                    <span className="ml-1 text-[10px] text-amber-300">proposal</span>
                    <span className="ml-1 text-[10px] text-slate-500">{m.status.replace(/_/g, ' ')}</span>
                  </button>
                ))}
                {onNewProposal && majorSelected && (
                  <button onClick={() => onNewProposal(major.id)}
                    className="px-2 py-0.5 text-xs rounded border border-dashed border-slate-600 text-slate-400 hover:text-white hover:border-slate-400">
                    + Proposal
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

If `groupByMajor`'s parameter type rejects `StripRevision` even with the `as never` cast, widen it as described in Interfaces and remove the cast.

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run src/components/parts/RevisionStrip.test.tsx src/components/parts/RevisionTimeline.test.tsx && npx tsc --noEmit`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/parts/RevisionStrip.tsx frontend/src/components/parts/RevisionStrip.test.tsx frontend/src/components/parts/revisionGrouping.ts
git commit -m "feat(ui): revision strip - majors as tabs with proposals nested"
```

---

### Task 5: `DocumentPane` component

**Files:**
- Create: `frontend/src/components/parts/DocumentPane.tsx`
- Test: `frontend/src/components/parts/DocumentPane.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export interface PaneDocument { fileId: number; filename: string; kind: '3d' | 'pdf' | 'image'; revisionName: string }
  export interface MirrorNotice { sourcePartId: number; sourceNumber: string; sourceName: string }
  export default function DocumentPane(props: { document: PaneDocument | null; mirror?: MirrorNotice | null; onOpenPart?(partId: number): void; children?: React.ReactNode }): JSX.Element
  ```
  Renders: header line `{filename} · {revisionName}`; for `kind === '3d'` renders `children` (the page passes its existing `<Viewer3D …/>` so assembly mode keeps working); for `pdf` an `<iframe data-testid="doc-iframe" src="${API_BASE_URL}/v1/parts/revision-files/{fileId}/inline">`; for `image` an `<img>` on the same URL. With `mirror` set, a red banner `data-testid="mirror-banner"` with the exact constraint text and a button that calls `onOpenPart(sourcePartId)`. With `document === null`, a muted "No document to show" placeholder (still shows the mirror banner if given).

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/components/parts/DocumentPane.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import DocumentPane from './DocumentPane'

vi.mock('../../api/client', () => ({ default: {}, API_BASE_URL: '/api' }))

describe('DocumentPane', () => {
  afterEach(cleanup)

  it('shows a pdf inline with the file and revision named', () => {
    render(<DocumentPane document={{ fileId: 7, filename: 'd.pdf', kind: 'pdf', revisionName: 'E1 · 003' }} />)
    expect((screen.getByTestId('doc-iframe') as HTMLIFrameElement).src).toContain('/api/v1/parts/revision-files/7/inline')
    expect(screen.getByTestId('doc-header').textContent).toContain('d.pdf · E1 · 003')
  })

  it('renders children for 3d', () => {
    render(<DocumentPane document={{ fileId: 1, filename: 'm.stp', kind: '3d', revisionName: 'E1' }}><div>viewer-here</div></DocumentPane>)
    expect(screen.getByText('viewer-here')).toBeTruthy()
    expect(screen.queryByTestId('doc-iframe')).toBeNull()
  })

  it('shows the red mirror banner with the exact wording and opens the source', () => {
    const onOpen = vi.fn()
    render(<DocumentPane document={{ fileId: 1, filename: 'm.stp', kind: '3d', revisionName: 'E1' }}
      mirror={{ sourcePartId: 5, sourceNumber: '206.882.251', sourceName: 'Handle, height adjustment LH' }} onOpenPart={onOpen}><div /></DocumentPane>)
    const b = screen.getByTestId('mirror-banner')
    expect(b.textContent).toContain('Mirrored part. Showing 206.882.251 (Handle, height adjustment LH). Geometry is the mirror image, RPS and references differ.')
    expect(b.className).toContain('red')
    fireEvent.click(screen.getByText('Open source part'))
    expect(onOpen).toHaveBeenCalledWith(5)
  })

  it('placeholder when nothing to show', () => {
    render(<DocumentPane document={null} />)
    expect(screen.getByText(/No document to show/)).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/parts/DocumentPane.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/parts/DocumentPane.tsx
/**
 * DocumentPane - the one area on the article panel that shows what you are
 * looking at: the 3D viewer (passed in as children so assembly mode keeps
 * working), a drawing PDF, or a picture. A mirror part with no own data shows
 * the source part's document under a red warning.
 */
import type { ReactNode } from 'react';
import { API_BASE_URL } from '../../api/client';

export interface PaneDocument {
  fileId: number;
  filename: string;
  kind: '3d' | 'pdf' | 'image';
  revisionName: string;
}

export interface MirrorNotice {
  sourcePartId: number;
  sourceNumber: string;
  sourceName: string;
}

interface Props {
  document: PaneDocument | null;
  mirror?: MirrorNotice | null;
  onOpenPart?(partId: number): void;
  children?: ReactNode;
}

export default function DocumentPane({ document, mirror, onOpenPart, children }: Props) {
  const inlineUrl = document ? `${API_BASE_URL}/v1/parts/revision-files/${document.fileId}/inline` : null;
  return (
    <div className="relative border-b border-slate-700">
      {mirror && (
        <div data-testid="mirror-banner"
          className="flex items-center justify-between gap-2 px-3 py-1.5 bg-red-900/60 border-b border-red-600 text-red-100 text-xs">
          <span>
            Mirrored part. Showing {mirror.sourceNumber} ({mirror.sourceName}). Geometry is the mirror image, RPS and references differ.
          </span>
          {onOpenPart && (
            <button onClick={() => onOpenPart(mirror.sourcePartId)}
              className="px-2 py-0.5 rounded bg-red-800 hover:bg-red-700 text-white font-medium flex-shrink-0">
              Open source part
            </button>
          )}
        </div>
      )}
      {document ? (
        <>
          <div data-testid="doc-header" className="px-3 py-1 text-xs text-slate-400 bg-slate-800/60 font-mono truncate">
            {document.filename} · {document.revisionName}
          </div>
          {document.kind === '3d' && <div className="h-80 overflow-hidden relative">{children}</div>}
          {document.kind === 'pdf' && (
            <iframe data-testid="doc-iframe" title={document.filename} src={inlineUrl ?? undefined} className="w-full h-[32rem] bg-white" />
          )}
          {document.kind === 'image' && (
            <div className="h-80 flex items-center justify-center bg-slate-900">
              <img src={inlineUrl ?? undefined} alt={document.filename} className="max-h-full max-w-full object-contain" />
            </div>
          )}
        </>
      ) : (
        <div className="h-24 flex items-center justify-center text-xs text-slate-500">No document to show on this revision</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run src/components/parts/DocumentPane.test.tsx && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/parts/DocumentPane.tsx frontend/src/components/parts/DocumentPane.test.tsx
git commit -m "feat(ui): document pane - 3D, inline PDF or picture, red mirror banner"
```

---

### Task 6: Grouped file list with Open

**Files:**
- Create: `frontend/src/components/parts/RevisionFilesGrouped.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` `RevisionFileRow` (line ~925): add `onOpen?: () => void` prop and an `Open` button before `Download` when provided
- Test: `frontend/src/components/parts/RevisionFilesGrouped.test.tsx`, extend `frontend/src/pages/ProjectDetailPage.files.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export function canOpenInline(file: { mime_type: string; filename: string }): boolean  // pdf or image/*
  export default function RevisionFilesGrouped(props: { files: RevisionFileLike[]; locked: boolean; viewingFileId: number | null; onView(file): void; onOpen(file): void; revisionName: string }): JSX.Element
  ```
  where `RevisionFileLike` is the page's `RevisionFile` shape (export that interface from `ProjectDetailPage.tsx` as `export interface RevisionFile`). Groups in order 3D / 2D / Documents with headers `3D (n)`, `2D (n)`, `Documents (n)`; empty groups are omitted; an empty list renders `No files on {revisionName} yet`. Rows are `RevisionFileRow` (import from the page) with `onView` for `has_viewer`, `onOpen` for `canOpenInline`.

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/components/parts/RevisionFilesGrouped.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RevisionFilesGrouped, { canOpenInline } from './RevisionFilesGrouped'

vi.mock('../../api/client', () => ({ default: { delete: vi.fn() }, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const f = (id: number, filename: string, file_type: string, mime_type: string, has_viewer = false, kind: string | null = null) => ({
  id, revision_id: 9, filename, file_type, mime_type, file_size: 1000, cad_format: null, has_viewer, uploaded_at: '2026-05-28', kind, note: null,
})
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('RevisionFilesGrouped', () => {
  afterEach(cleanup)

  it('groups into 3D, 2D and Documents with counts and omits empty groups', () => {
    wrap(<RevisionFilesGrouped revisionName="E1" locked={false} viewingFileId={null} onView={() => {}} onOpen={() => {}}
      files={[f(1, 'a.CATPart', 'cad', 'application/octet-stream', false, 'PCA'), f(2, 'a.stp', 'cad', 'application/step', true), f(3, 'd.pdf', 'drawing', 'application/pdf')]} />)
    expect(screen.getByText('3D (2)')).toBeTruthy()
    expect(screen.getByText('2D (1)')).toBeTruthy()
    expect(screen.queryByText(/Documents/)).toBeNull()
    expect(screen.getByText('PCA')).toBeTruthy()
  })

  it('offers Open for pdf and pictures, View 3D for viewable cad', () => {
    const onOpen = vi.fn(); const onView = vi.fn()
    wrap(<RevisionFilesGrouped revisionName="E1" locked={false} viewingFileId={null} onView={onView} onOpen={onOpen}
      files={[f(2, 'a.stp', 'cad', 'application/step', true), f(3, 'd.pdf', 'drawing', 'application/pdf'), f(4, 'p.png', 'picture', 'image/png'), f(5, 'x.xlsx', 'document', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')]} />)
    expect(screen.getAllByText('Open')).toHaveLength(2)
    fireEvent.click(screen.getAllByText('Open')[0])
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
    fireEvent.click(screen.getByText('View 3D'))
    expect(onView).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
  })

  it('empty state', () => {
    wrap(<RevisionFilesGrouped revisionName="E1" locked={false} viewingFileId={null} onView={() => {}} onOpen={() => {}} files={[]} />)
    expect(screen.getByText('No files on E1 yet')).toBeTruthy()
  })

  it('canOpenInline', () => {
    expect(canOpenInline({ mime_type: 'application/pdf', filename: 'a.pdf' })).toBe(true)
    expect(canOpenInline({ mime_type: 'image/png', filename: 'a.png' })).toBe(true)
    expect(canOpenInline({ mime_type: 'application/octet-stream', filename: 'a.pdf' })).toBe(true)
    expect(canOpenInline({ mime_type: 'application/octet-stream', filename: 'a.CATPart' })).toBe(false)
  })
})
```

Add to `ProjectDetailPage.files.test.tsx`, inside the `RevisionFileRow provenance` describe:

```tsx
  it('shows Open when an onOpen handler is given', () => {
    const onOpen = vi.fn()
    wrap(<RevisionFileRow file={file({ file_type: 'drawing', mime_type: 'application/pdf', filename: 'd.pdf' })} isViewing={false} locked={false} onOpen={onOpen} />)
    fireEvent.click(screen.getByText('Open'))
    expect(onOpen).toHaveBeenCalled()
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/parts/RevisionFilesGrouped.test.tsx src/pages/ProjectDetailPage.files.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `ProjectDetailPage.tsx`: change `interface RevisionFile` to `export interface RevisionFile`; in `RevisionFileRow` add `onOpen?: () => void` to the props type and, before the Download link:

```tsx
        {onOpen && (
          <button onClick={onOpen}
            className="px-2 py-0.5 rounded bg-slate-600 hover:bg-slate-500 text-white font-medium text-xs">
            Open
          </button>
        )}
```

New component:

```tsx
// frontend/src/components/parts/RevisionFilesGrouped.tsx
/** File list of a revision grouped the way engineers look for things:
 *  3D (PCA, DMU, STEP), 2D (drawings), Documents (the rest). */
import { RevisionFileRow, type RevisionFile } from '../../pages/ProjectDetailPage';

export function canOpenInline(file: { mime_type: string; filename: string }): boolean {
  if (file.mime_type === 'application/pdf' || file.mime_type.startsWith('image/')) return true;
  const lower = file.filename.toLowerCase();
  return /\.(pdf|png|jpe?g|gif|webp)$/.test(lower);
}

const GROUPS: { key: string; label: string; match(f: RevisionFile): boolean }[] = [
  { key: '3d', label: '3D', match: (f) => f.file_type === 'cad' },
  { key: '2d', label: '2D', match: (f) => f.file_type === 'drawing' },
  { key: 'docs', label: 'Documents', match: (f) => f.file_type !== 'cad' && f.file_type !== 'drawing' },
];

interface Props {
  files: RevisionFile[];
  locked: boolean;
  viewingFileId: number | null;
  revisionName: string;
  onView(file: RevisionFile): void;
  onOpen(file: RevisionFile): void;
}

export default function RevisionFilesGrouped({ files, locked, viewingFileId, revisionName, onView, onOpen }: Props) {
  if (files.length === 0) return <p className="text-slate-500 text-xs px-1 py-2">No files on {revisionName} yet</p>;
  return (
    <div className="space-y-2">
      {GROUPS.map((g) => {
        const rows = files.filter(g.match);
        if (rows.length === 0) return null;
        return (
          <div key={g.key}>
            <p className="text-[10px] uppercase tracking-wide text-slate-500 px-1 mb-1">{g.label} ({rows.length})</p>
            <div className="space-y-1">
              {rows.map((file) => (
                <RevisionFileRow key={file.id} file={file} locked={locked} isViewing={viewingFileId === file.id}
                  onView={file.has_viewer ? () => onView(file) : undefined}
                  onOpen={canOpenInline(file) ? () => onOpen(file) : undefined} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

Importing a component from a page module is unusual but avoids moving `RevisionFileRow` (with its delete mutation and tests) in this task. If it creates an import cycle that breaks tests (page imports the grouped list, grouped list imports the page), move `RevisionFileRow`, `fileTypeColor`, `UploadedBy` usage and the `RevisionFile` interface into `frontend/src/components/parts/RevisionFileRow.tsx`, re-export them from the page (`export { RevisionFileRow } from '../components/parts/RevisionFileRow'; export type { RevisionFile } …`) so existing test imports keep working, and import from the new file here.

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run src/components/parts/RevisionFilesGrouped.test.tsx src/pages/ && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/parts/RevisionFilesGrouped.tsx frontend/src/components/parts/RevisionFilesGrouped.test.tsx frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.files.test.tsx
git commit -m "feat(ui): revision files grouped into 3D / 2D / documents with Open for drawings"
```

(Add `frontend/src/components/parts/RevisionFileRow.tsx` to the add list if the fallback move was needed.)

---

### Task 7: Wire the article panel: strip, pane, grouped files, mirror fallback, relation chips

**Files:**
- Create: `frontend/src/hooks/useProjectStructure.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (header lines ~1385-1410, viewer ~1450-1471, files ~1472-1502, state ~1014-1030 and ~1127-1130)
- Test: `frontend/src/pages/ProjectDetailPage.article.test.tsx`

**Interfaces:**
- Consumes: Tasks 4-6 components; Task 3 endpoint.
- Produces: `useProjectStructure(projectId)` → `useQuery` on `['project-structure', projectId]` → `GET /v1/parts/project/{id}/structure`, typed as
  ```ts
  export interface StructureRevision { id: number; revision_name: string; customer_index: string | null; status: string; phase: 'review' | 'official'; parent_revision_id: number | null; is_active: boolean }
  export interface StructureRelated { relation_type: string; direction: 'outgoing' | 'incoming'; label: string; part_id: number; part_number: string; name: string; item_category: string }
  export interface StructureBrief { part_id: number; part_number: string; customer_part_number: string | null; name: string }
  export interface StructureArticle extends StructureBrief { lifecycle_phase: string; active_revision_id: number | null; revisions: StructureRevision[]; related: StructureRelated[]; mirror_of: StructureBrief | null; mirrored_by: StructureBrief[] }
  export function useProjectStructure(projectId: number): UseQueryResult<{ articles: StructureArticle[] }>
  export function articleOf(structure, partId): StructureArticle | undefined
  ```

Behaviour to implement on the page, for a selected article:

1. **Header**: after the part name in the panel header (the `Files & 3D Model` header at ~1385 becomes the article header), when `article.mirror_of` show `<span data-testid="mirror-chip" class="… border-red-500 text-red-300">⇄ Mirror of {number} · data on that part</span>` as a button that selects the source part; when `mirrored_by.length` show `⇄ mirrored by {numbers}`.
2. **Strip**: replace the `<select>` with `<RevisionStrip revisions={partRevisions} selectedId={selectedRevisionId} activeId={selectedPart.active_revision_id} onSelect={(id) => { setSelectedRevisionId(id); setViewingFileId(null); setOpenDocId(null); }} onNewProposal={(majorId) => proposalMutation.mutate(majorId)} />`. Add `proposalMutation` (`POST /v1/parts/{selectedPartId}/revisions/proposals {parent_revision_id}`, on success toast `Created {revision_name}`, invalidate `['part-revisions', selectedPartId]` and `['project-structure', id]`, select the new revision).
3. **Pane**: new state `openDocId: number | null` (a PDF/picture chosen with Open). Document selection order: if `openDocId` names a file of the current revision → pdf/image doc; else if a viewable 3D file (existing `viewingFile`) → 3d doc with the existing `<Viewer3D …/>` as children (keep the assembly banner/button logic inside the children); else if the article is a mirror → **fallback**: fetch the source part's active revision files (`useRevisionFiles(article.mirror_of.part_id → its active revision)`; get the source's active revision id from `articleOf(structure, sourceId)?.active_revision_id`), take its first viewable 3D (or, when `openDocId` was set from a drawing intent, its first pdf), render with `mirror={{ sourcePartId, sourceNumber: customer_part_number ?? part_number, sourceName }}`; else `document={null}`. Pass `onOpenPart={setSelectedPartId}`.
4. **Files**: replace the `revisionFiles.map(...)` block with `<RevisionFilesGrouped files={revisionFiles ?? []} locked={revisionLocked} viewingFileId={viewingFile?.id ?? null} revisionName={revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index)} onView={(f) => { setViewingFileId(f.id); setOpenDocId(null); }} onOpen={(f) => setOpenDocId(f.id)} />`. Keep the drop zone and upload dialog exactly as they are.
5. **Relation chips** under the files: `article.related` as small chips `{label} {part_number} {name}` (category icon from `CATEGORY_META`), each a button selecting that part; plus the mirror chip if any. Existing `PartRelationsSection` stays where it is.
6. **Structure invalidation**: everywhere the page invalidates `['part-revisions', …]` (upload dialog `onDone`/`onClose`, customer data, package), also invalidate `['project-structure', id]`.

- [ ] **Step 1: Failing tests**

```tsx
// frontend/src/pages/ProjectDetailPage.article.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/workflows/RevisionWorkflowSection', () => stub('workflow'))
vi.mock('../components/PartBOMSection', () => stub('bom-section'))
vi.mock('../components/PartRelationsSection', () => stub('relations'))
vi.mock('../components/ProcessFlowSection', () => stub('process-flow'))
vi.mock('../components/PPAPSection', () => stub('ppap'))
vi.mock('../components/MilestoneStrip', () => stub('milestones'))
vi.mock('../components/ProjectLessonsSection', () => stub('lessons'))
vi.mock('../components/ProjectSepSection', () => stub('sep'))
vi.mock('../components/ProjectChangesSection', () => stub('changes'))
vi.mock('../components/parts/AssemblyTreeList', () => stub('assemblies'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

const LH = { id: 5, part_number: '20-1994-001-0', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null }
const structure = { articles: [
  { part_id: 5, part_number: LH.part_number, customer_part_number: '206.882.251', name: LH.name, lifecycle_phase: 'nominated', active_revision_id: 9,
    revisions: [{ id: 9, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true },
                { id: 10, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review', parent_revision_id: 9, is_active: false }],
    related: [{ relation_type: 'produces', direction: 'incoming', label: 'produced by', part_id: 30, part_number: '199401', name: 'TOOL Handle', item_category: 'tool' }],
    mirror_of: null, mirrored_by: [{ part_id: 6, part_number: RH.part_number, customer_part_number: '206.882.252', name: RH.name }] },
  { part_id: 6, part_number: RH.part_number, customer_part_number: '206.882.252', name: RH.name, lifecycle_phase: 'nominated', active_revision_id: 19,
    revisions: [{ id: 19, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true }],
    related: [], mirror_of: { part_id: 5, part_number: LH.part_number, customer_part_number: '206.882.251', name: LH.name }, mirrored_by: [] },
] }
const files9 = [
  { id: 101, revision_id: 9, filename: 'lh.CATPart', file_type: 'cad', mime_type: 'application/octet-stream', file_size: 1, cad_format: 'catia', has_viewer: false, uploaded_at: '2026-05-28', kind: 'PCA', note: 'PCA engineering master' },
  { id: 102, revision_id: 9, filename: 'lh.stp', file_type: 'cad', mime_type: 'application/step', file_size: 1, cad_format: 'step', has_viewer: true, uploaded_at: '2026-05-28' },
  { id: 103, revision_id: 9, filename: 'lh.pdf', file_type: 'drawing', mime_type: 'application/pdf', file_size: 1, cad_format: null, has_viewer: false, uploaded_at: '2026-05-28' },
]

function mount() {
  clientMocks.get.mockImplementation((url: string) => {
    if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active' }] })
    if (url === '/v1/parts/project/2') return Promise.resolve({ data: [LH, RH] })
    if (url === '/v1/parts/project/2/structure') return Promise.resolve({ data: structure })
    if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
    if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: structure.articles[1].revisions.map((r) => ({ ...r, part_id: 6, created_at: '2026-05-28' })) })
    if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: files9 })
    if (url === '/v1/parts/revisions/10/files') return Promise.resolve({ data: [] })
    if (url === '/v1/parts/revisions/19/files') return Promise.resolve({ data: [] })
    if (url.includes('/bom-tree')) return Promise.resolve({ data: { part_id: 5, part_number: LH.part_number, name: LH.name, revision_name: 'E1', customer_index: '003', lines: [] } })
    return Promise.resolve({ data: [] })
  })
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/projects/2']}><Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes></MemoryRouter>
    </QueryClientProvider>)
}

describe('ProjectDetailPage article panel', () => {
  beforeEach(() => { clientMocks.get.mockReset(); clientMocks.post.mockReset() })
  afterEach(cleanup)

  it('shows the revision strip with the proposal nested, grouped files and relation chips', async () => {
    mount()
    fireEvent.click(await screen.findByText(/Handle LH/))
    expect(await screen.findByTestId('rev-tab-10')).toBeTruthy()
    expect(screen.getByTestId('rev-tab-10').textContent).toContain('proposal')
    expect(await screen.findByText('3D (2)')).toBeTruthy()
    expect(screen.getByText('2D (1)')).toBeTruthy()
    expect(screen.getByTestId('relation-chip-30').textContent).toContain('199401')
    expect(screen.getByText(/mirrored by 20-1994-002-0/)).toBeTruthy()
  })

  it('Open on the drawing switches the pane to the inline pdf, selecting a revision switches back', async () => {
    mount()
    fireEvent.click(await screen.findByText(/Handle LH/))
    await screen.findByText('3D (2)')
    fireEvent.click(screen.getByText('Open'))
    expect((await screen.findByTestId('doc-iframe') as HTMLIFrameElement).src).toContain('/v1/parts/revision-files/103/inline')
    fireEvent.click(screen.getByTestId('rev-tab-10'))
    await waitFor(() => expect(screen.queryByTestId('doc-iframe')).toBeNull())
  })

  it('a mirror with no own 3D shows the source viewer under the red banner and the mirror chip', async () => {
    mount()
    fireEvent.click(await screen.findByText(/Handle RH/))
    const banner = await screen.findByTestId('mirror-banner')
    expect(banner.textContent).toContain('Mirrored part. Showing 206.882.251')
    expect(screen.getByText('viewer')).toBeTruthy()
    expect(screen.getByTestId('mirror-chip').textContent).toContain('Mirror of 206.882.251')
    fireEvent.click(within(banner).getByText('Open source part'))
    expect(await screen.findByText('3D (2)')).toBeTruthy()
  })

  it('+ Proposal on the selected major posts a proposal', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 11, revision_name: 'E1.2' } })
    mount()
    fireEvent.click(await screen.findByText(/Handle LH/))
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByText('+ Proposal'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/5/revisions/proposals', { parent_revision_id: 9 }))
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.article.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Hook**

```ts
// frontend/src/hooks/useProjectStructure.ts
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';

export interface StructureRevision { id: number; revision_name: string; customer_index: string | null; status: string; phase: 'review' | 'official'; parent_revision_id: number | null; is_active: boolean }
export interface StructureRelated { relation_type: string; direction: 'outgoing' | 'incoming'; label: string; part_id: number; part_number: string; name: string; item_category: string }
export interface StructureBrief { part_id: number; part_number: string; customer_part_number: string | null; name: string }
export interface StructureArticle extends StructureBrief {
  lifecycle_phase: string; active_revision_id: number | null;
  revisions: StructureRevision[]; related: StructureRelated[];
  mirror_of: StructureBrief | null; mirrored_by: StructureBrief[];
}
export interface ProjectStructure { articles: StructureArticle[] }

export function useProjectStructure(projectId: number) {
  return useQuery<ProjectStructure>({
    queryKey: ['project-structure', projectId],
    queryFn: async () => (await client.get(`/v1/parts/project/${projectId}/structure`)).data,
    enabled: !!projectId,
  });
}

export function articleOf(structure: ProjectStructure | undefined, partId: number | null): StructureArticle | undefined {
  if (!structure || partId === null) return undefined;
  return structure.articles.find((a) => a.part_id === partId);
}
```

Check whether `frontend/src/hooks/` exists; if the project keeps hooks elsewhere (grep `useQuery` outside pages), follow that convention and adjust the import paths in the page and the tests.

- [ ] **Step 4: Page wiring**

Implement points 1-6 above in `ProjectDetailPage.tsx`. Concretely:

- Imports: `RevisionStrip`, `DocumentPane`, `RevisionFilesGrouped`, `useProjectStructure, articleOf`.
- In the page component: `const { data: structure } = useProjectStructure(id); const article = articleOf(structure, selectedPartId);`
- Mirror fallback data: `const mirrorSource = article?.mirror_of ? articleOf(structure, article.mirror_of.part_id) : undefined; const mirrorFiles = useRevisionFiles(mirrorSource?.active_revision_id ?? 0);` (`useRevisionFiles` is already `enabled: !!revisionId`).
- `const [openDocId, setOpenDocId] = useState<number | null>(null);` reset it in the same places `setViewingFileId(null)` is called on part/revision change.
- Document derivation (after `viewingFile`/`viewerUrl`):

```tsx
  const openDoc = revisionFiles?.find((f) => f.id === openDocId) ?? null;
  const docKind = (f: RevisionFile): 'pdf' | 'image' => (f.mime_type === 'application/pdf' || /\.pdf$/i.test(f.filename) ? 'pdf' : 'image');
  const revName = selectedRevision ? revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index) : '';
  let paneDoc: PaneDocument | null = null;
  let paneMirror: MirrorNotice | null = null;
  if (openDoc) paneDoc = { fileId: openDoc.id, filename: openDoc.filename, kind: docKind(openDoc), revisionName: revName };
  else if (viewingFile || assemblyActive) paneDoc = { fileId: viewingFile?.id ?? 0, filename: assemblyActive ? 'Assembly' : viewingFile!.filename, kind: '3d', revisionName: revName };
  else if (article?.mirror_of && mirrorSource) {
    const src = mirrorFiles.data ?? [];
    const pick = src.find((f) => f.has_viewer) ?? src.find((f) => f.file_type === 'drawing') ?? null;
    if (pick) {
      paneDoc = { fileId: pick.id, filename: pick.filename, kind: pick.has_viewer ? '3d' : docKind(pick), revisionName: `${mirrorSource.part_number} · active` };
      paneMirror = { sourcePartId: mirrorSource.part_id, sourceNumber: mirrorSource.customer_part_number ?? mirrorSource.part_number, sourceName: mirrorSource.name };
    }
  }
  const paneViewerUrl = paneMirror && paneDoc?.kind === '3d' ? `${API_BASE_URL}/v1/parts/revision-files/${paneDoc.fileId}/viewer` : viewerUrl;
```

- Replace the viewer block with:

```tsx
  <DocumentPane document={paneDoc} mirror={paneMirror} onOpenPart={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }}>
    <Viewer3D fileId={assemblyActive ? null : paneDoc?.fileId ?? null} viewerUrl={assemblyActive ? null : paneViewerUrl} models={assemblyActive ? assemblyModels : undefined} />
    {/* keep the existing assembly banner and "← Assembly view" button here unchanged */}
  </DocumentPane>
```

- Header: replace the `<h3>Files & 3D Model</h3>` with the article number + name + phase chip + mirror chips; replace the `<select>` with `<RevisionStrip …/>` on its own row under the header (full width); keep the lock indicator and "+ Customer package".
- Files: replace the `revisionFiles.map` block with `RevisionFilesGrouped`; keep the drop zone.
- Relation chips: after the files block:

```tsx
  {article && (article.related.length > 0 || article.mirror_of || article.mirrored_by.length > 0) && (
    <div className="flex flex-wrap gap-1 px-2 py-1 border-t border-slate-700">
      {article.related.map((r) => (
        <button key={`${r.relation_type}-${r.part_id}`} data-testid={`relation-chip-${r.part_id}`} onClick={() => setSelectedPartId(r.part_id)}
          className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-xs text-slate-200">
          <span className="text-slate-400">{r.label}</span> {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, projectCode)}
        </button>
      ))}
      {article.mirrored_by.map((m) => (
        <button key={m.part_id} onClick={() => setSelectedPartId(m.part_id)} className="px-2 py-0.5 rounded border border-red-700 text-xs text-red-300">⇄ mirrored by {m.part_number}</button>
      ))}
    </div>
  )}
```

- Mirror chip in the header: `{article?.mirror_of && <button data-testid="mirror-chip" onClick={() => setSelectedPartId(article.mirror_of!.part_id)} className="px-2 py-0.5 rounded border border-red-500 text-red-300 text-xs">⇄ Mirror of {article.mirror_of.customer_part_number ?? article.mirror_of.part_number} · data on that part</button>}`.
- Proposal mutation as in point 2. Invalidate `['project-structure', id]` wherever `['part-revisions', …]` is invalidated (grep the file).

- [ ] **Step 5: Run tests and type check**

Run: `cd frontend && npx vitest run src/pages/ && npx tsc --noEmit`
Expected: the new test file and all existing page tests PASS (the upload and files tests must keep passing: they mock `/v1/parts/project/2/structure` through the `return Promise.resolve({ data: [] })` fallback, which yields `articles` undefined; make `articleOf` tolerate a missing `articles` array).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useProjectStructure.ts frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.article.test.tsx
git commit -m "feat(ui): article panel - revision strip, document pane with mirror fallback, grouped files, relation chips"
```

---

### Task 8: Structure children in the left tree

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (`TreeNodeComponent`, function at ~445, JSX ~482-560)
- Test: extend `frontend/src/pages/ProjectDetailPage.article.test.tsx`

**Interfaces:**
- Consumes: Task 7's `structure` (pass `articleOf(structure, node.part.id)` into `TreeNodeComponent` as `article?: StructureArticle`, and `onSelectRevision(partId, revisionId)`).

Behaviour: an article row gets the expand chevron even without BOM children when it has an `article` entry with revisions or related items. Expanded, it renders under the row (indented one level, not draggable, not selectable as parts):

```
Revisions   [E1 · 003 ● active]  [E1.1 proposal]
Tools       199401 TOOL Handle
```

Each revision chip is a button → `onSelectRevision(part.id, rev.id)`; each related chip → `onSelect(otherPartId)`. Mirror rows show `⇄ mirror of {number}` (or `⇄ mirrored by …`) inline after the name, red text, `data-testid="tree-mirror-{partId}"`.

- [ ] **Step 1: Failing tests** (append to `ProjectDetailPage.article.test.tsx`)

```tsx
  it('tree rows expand to revisions and tools, and mark mirrors', async () => {
    mount()
    const row = await screen.findByText(/Handle LH/)
    expect(screen.getByTestId('tree-mirror-6').textContent).toContain('mirror of 20-1994-001-0')
    const chevron = within(row.closest('button')!.parentElement!).getByLabelText('Expand')
    fireEvent.click(chevron)
    expect(await screen.findByTestId('tree-rev-10')).toBeTruthy()
    expect(screen.getByTestId('tree-rev-10').textContent).toContain('E1.1')
    expect(screen.getByTestId('tree-rel-30').textContent).toContain('199401')
    fireEvent.click(screen.getByTestId('tree-rev-10'))
    expect((await screen.findByTestId('rev-tab-10')).getAttribute('aria-selected')).toBe('true')
  })
```

If the chevron's accessible name differs after implementation, use `aria-label="Expand"` / `"Collapse"` on the chevron button (add it; the existing chevron has none).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.article.test.tsx -t "tree rows"`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `TreeNodeComponent` props add `article?: StructureArticle; onSelectRevision?(partId: number, revisionId: number): void`. Compute `const hasStructure = !!article && (article.revisions.length > 0 || article.related.length > 0); const expandable = hasChildren || hasStructure;` and use `expandable` where `hasChildren` gates the chevron (`aria-label={expanded ? 'Collapse' : 'Expand'}`). After the name span:

```tsx
  {article?.mirror_of && <span data-testid={`tree-mirror-${node.part.id}`} className="ml-2 text-[10px] text-red-300">⇄ mirror of {article.mirror_of.part_number}</span>}
  {article && article.mirrored_by.length > 0 && <span data-testid={`tree-mirror-${node.part.id}`} className="ml-2 text-[10px] text-red-300">⇄ mirrored by {article.mirrored_by.map((m) => m.part_number).join(', ')}</span>}
```

Under the row, when `expanded && hasStructure`:

```tsx
  <div className="ml-6 my-1 space-y-1 text-xs" style={{ marginLeft: `${depth * 20 + 24}px` }}>
    {article!.revisions.length > 0 && (
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-slate-500 w-16">Revisions</span>
        {article!.revisions.map((r) => (
          <button key={r.id} data-testid={`tree-rev-${r.id}`} onClick={(e) => { e.stopPropagation(); onSelectRevision?.(node.part.id, r.id); }}
            className={`px-1.5 py-0.5 rounded ${r.parent_revision_id ? 'bg-amber-900/40 text-amber-200' : 'bg-slate-700 text-slate-200'} ${r.is_active ? 'font-semibold' : ''}`}>
            {revisionLabel(r.revision_name, r.customer_index)}{r.parent_revision_id ? ' proposal' : ''}{r.is_active ? ' ●' : ''}
          </button>
        ))}
      </div>
    )}
    {article!.related.length > 0 && (
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-slate-500 w-16">Linked</span>
        {article!.related.map((r) => (
          <button key={`${r.relation_type}-${r.part_id}`} data-testid={`tree-rel-${r.part_id}`} onClick={(e) => { e.stopPropagation(); onSelect(r.part_id); }}
            className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
            {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, projectCode)}
          </button>
        ))}
      </div>
    )}
  </div>
```

Thread `article={articleOf(structure, node.part.id)}` and `onSelectRevision={(pid, rid) => { setSelectedPartId(pid); setSelectedRevisionId(rid); setViewingFileId(null); setOpenDocId(null); }}` from the page into every `TreeNodeComponent` render (there is a recursive render for children: pass `structure` down or pass `articleOf` results per child).

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run src/pages/ && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.article.test.tsx
git commit -m "feat(ui): project tree expands articles to revisions and linked items, marks mirrors"
```

---

### Task 9: Relations UI offers mirror; part page gets the document pane and grouped files

**Files:**
- Modify: `frontend/src/components/PartRelationsSection.tsx` (`<select>` lines ~148-157)
- Modify: `frontend/src/pages/PartDetail.tsx` (add a "Files" card between BOM and Revisions)
- Test: `frontend/src/components/PartRelationsSection.test.tsx` (extend or create), `frontend/src/pages/PartDetail.files.test.tsx`

- [ ] **Step 1: Failing tests**

For `PartRelationsSection`: find its existing test file (`ls frontend/src/components/PartRelationsSection*.test.tsx`); add a test that, for `itemCategory="article"`, the type select contains an option with value `mirror_of` and label `mirror of`, and that for `itemCategory="tool"` it does not.

```tsx
// frontend/src/pages/PartDetail.files.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PartDetail from './PartDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../components/Viewer3D', () => ({ default: () => <div>viewer</div> }))
vi.mock('../components/parts/PartPaintCard', () => ({ default: () => <div>paint</div> }))

describe('PartDetail files card', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: { id: 5, project_id: 2, part_number: '20-1', name: 'Cover', part_type: 'internal_mfg', item_category: 'article', active_revision_id: 9, lifecycle_phase: 'rfq',
        revisions: [{ id: 9, revision_name: 'E1', phase: 'review', status: 'approved', parent_revision_id: null, source: 'customer', customer_index: '003', part_phase_at_receipt: 'rfq', created_at: '2026-05-28' }] } })
      if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: [
        { id: 103, revision_id: 9, filename: 'd.pdf', file_type: 'drawing', mime_type: 'application/pdf', file_size: 1, cad_format: null, has_viewer: false, uploaded_at: '2026-05-28' }] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists the active revision files grouped and opens a drawing inline', async () => {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/parts/5']}><Routes><Route path="/parts/:partId" element={<PartDetail />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('2D (1)')).toBeTruthy()
    fireEvent.click(screen.getByText('Open'))
    expect((await screen.findByTestId('doc-iframe') as HTMLIFrameElement).src).toContain('/v1/parts/revision-files/103/inline')
  })
})
```

Check the real route path and param name of the part page in `frontend/src/App.tsx` (`/parts/:partId` vs `:id`) and the exact `GET /v1/parts/{id}` shape `PartDetail` expects (read `PartDetail.tsx:77-100`); adjust the mock accordingly.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/PartDetail.files.test.tsx src/components/PartRelationsSection.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`PartRelationsSection.tsx`: in the `<select>`, add `{itemCategory === 'article' && <option value="mirror_of">mirror of</option>}` after `related to`. Also map a backend 409 or 400 detail into the existing error toast (it already uses `errMsg`-style handling; verify).

`PartDetail.tsx`: add between the BOM card and the Revisions card:

```tsx
<div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
  <h2 className="text-lg font-semibold text-slate-100 mb-3">Files · {activeRevision ? revisionLabel(activeRevision.revision_name, activeRevision.customer_index) : 'no active revision'}</h2>
  <DocumentPane document={paneDoc}>
    {paneDoc?.kind === '3d' && <Viewer3D fileId={paneDoc.fileId} viewerUrl={`${API_BASE_URL}/v1/parts/revision-files/${paneDoc.fileId}/viewer`} />}
  </DocumentPane>
  <div className="mt-3">
    <RevisionFilesGrouped files={files ?? []} locked={true} viewingFileId={viewingId} revisionName={activeRevision?.revision_name ?? ''}
      onView={(f) => { setViewingId(f.id); setOpenId(null); }} onOpen={(f) => setOpenId(f.id)} />
  </div>
</div>
```

with `const activeRevision = part.revisions.find((r) => r.id === part.active_revision_id)`, a `useQuery` on `['revision-files', activeRevision?.id]` → `GET /v1/parts/revisions/{id}/files` (enabled when defined), local `viewingId`/`openId` state, and the same `paneDoc` derivation as Task 7 (no mirror fallback here). `locked={true}` on the part page: deleting stays on the project page. Imports: `DocumentPane`, `RevisionFilesGrouped`, `Viewer3D`, `API_BASE_URL`, `revisionLabel`.

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PartRelationsSection.tsx frontend/src/pages/PartDetail.tsx frontend/src/pages/PartDetail.files.test.tsx frontend/src/components/PartRelationsSection.test.tsx
git commit -m "feat(ui): mirror relation in the relations form; part page shows files and documents"
```

---

### Task 10: Docs and full verification

**Files:**
- Modify: `docs/CUSTOMER_DATA_INDEX.md` (new section "Article view" after "Uploading files (project page)")

- [ ] **Step 1: Docs**

Add:

```markdown
### Article view (project page)

Select an article: the header shows number, name, phase and, for a mirrored
part, a red `⇄ Mirror of …` chip. Below it the **revision strip**: majors
as tabs (`E1 · 003`, `E2 · 004`, `1`), proposals nested under their major
(`E1.1 proposal`), the active one marked. **+ Proposal** on the selected
major opens the next `E1.n`.

The **document pane** shows one thing at a time: the 3D viewer, a drawing
(**Open** on a PDF), or a picture. A mirror part with no data of its own
shows the source part's model or drawing under a red banner; the source
holds the files, the mirror only points at it (`mirror_of` relation).

Files are grouped **3D** (PCA, DMU, STEP), **2D** (drawings), **Documents**.
Linked tools, gauges and equipment appear as chips under the files; the
left tree expands an article to the same revisions and links.
```

- [ ] **Step 2: Full suites**

Run: `cd backend && uv run pytest -q` and `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all green (the known flake `test_implementation_tracking::test_a_resolution_clears_the_open_risk` passes alone if it trips).

- [ ] **Step 3: Manual check on local**

Local backend needs the new code: `docker cp backend/app claude-plm2-backend-1:/app/ && docker restart claude-plm2-backend-1`. Open project 1994 locally (local data has the 12 articles, mirrors and E1.1 after today's reset), select 206.882.252: red banner with the LH model; select 206.886.197: `E1.1 proposal` tab in the strip; Open on a drawing shows the PDF.

- [ ] **Step 4: Commit**

```bash
git add docs/CUSTOMER_DATA_INDEX.md
git commit -m "docs: article view - revision strip, document pane, mirrors"
```
