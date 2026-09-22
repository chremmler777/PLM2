# Guided Upload with Customer File Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare drop zone on the project page with an upload dialog that reads the customer index and data kind from filenames per customer convention, lets the user choose attach / next customer major / next proposal, and shows kind and note per file.

**Architecture:** A pure parser registry in the backend (`customer_naming.py`) serves a parse endpoint and the package preview. Projects carry a default convention, the upload endpoint stores `kind` and `note`. The frontend dialog is one component with a pure helper (`uploadLevel.ts`) for the default-level decision, wired into `ProjectDetailPage` where `CADUploader` sits today.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend, tests via `uv run pytest` in `backend/`), React + TanStack Query + Tailwind + Vitest/Testing Library (frontend, tests via `npx vitest run` in `frontend/`).

**Spec:** `docs/superpowers/specs/2026-09-22-guided-upload-customer-naming-design.md`

## Global Constraints

- Migration id `075`, revises `074`. Idempotent like `074` (check table/column existence before adding).
- Convention values: `"vw"`, `"scout"`, `null`. Labels: "None", "VW group", "Scout".
- Customer index is optional and informational everywhere. Detection prefills, never decides.
- Kind labels (single source, backend `KIND_LABELS`, mirrored in frontend from the parse response, never retyped):
  - `PCA` → "PCA engineering master: full construction model with RPS, reference points/lines, annotations. Open this one in CATIA."
  - `DMU` → "DMU lightweight solid for packaging and quick viewing, no RPS or references. Archive copy."
  - `DRW` → "DRW customer part drawing."
  - `G\d\d` → "Assembly position {kind}."
- Backend tests: `cd backend && uv run pytest <file> -q`. Frontend tests: `cd frontend && npx vitest run <file>`. Type check: `cd frontend && npx tsc --noEmit`.
- Commit after every task. No pushes.
- Existing `CADUploader`, `CustomerDataDialog`, `CustomerPackageDialog` keep working; tests for them stay green.

---

### Task 1: Project `customer_naming` column, response field, PATCH endpoint

**Files:**
- Create: `backend/alembic/versions/075_customer_naming_and_file_note.py`
- Modify: `backend/app/models/entities.py:103-118` (Project)
- Modify: `backend/app/models/part.py:224-260` (RevisionFile, add `kind` and `note`)
- Modify: `backend/app/api/v1/plants.py:48-70` (list), `:107-140` (create), add PATCH
- Test: `backend/tests/test_project_customer_naming.py`

**Interfaces:**
- Produces: `Project.customer_naming: str | None`; `RevisionFile.note: str | None`; `RevisionFile.kind: str | None`; `PATCH /api/v1/plants/projects/{project_id}` body `{customer_naming?: "vw"|"scout"|null, name?, description?, status?}` → project dict incl. `customer_naming`; `GET /api/v1/plants/projects` rows include `customer_naming`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_project_customer_naming.py
async def test_projects_list_carries_customer_naming(client, eng_auth, seed):
    rows = (await client.get("/api/v1/plants/projects", headers=eng_auth)).json()
    me = next(r for r in rows if r["id"] == seed["project_id"])
    assert me["customer_naming"] is None


async def test_patch_project_sets_customer_naming(client, eng_auth, seed):
    pid = seed["project_id"]
    r = await client.patch(f"/api/v1/plants/projects/{pid}", json={"customer_naming": "vw"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["customer_naming"] == "vw"
    rows = (await client.get("/api/v1/plants/projects", headers=eng_auth)).json()
    assert next(x for x in rows if x["id"] == pid)["customer_naming"] == "vw"


async def test_patch_project_rejects_unknown_convention(client, eng_auth, seed):
    r = await client.patch(f"/api/v1/plants/projects/{seed['project_id']}",
                           json={"customer_naming": "bmw"}, headers=eng_auth)
    assert r.status_code == 422


async def test_patch_project_clears_customer_naming(client, eng_auth, seed):
    pid = seed["project_id"]
    await client.patch(f"/api/v1/plants/projects/{pid}", json={"customer_naming": "vw"}, headers=eng_auth)
    r = await client.patch(f"/api/v1/plants/projects/{pid}", json={"customer_naming": None}, headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["customer_naming"] is None


async def test_patch_unknown_project_is_404(client, eng_auth):
    r = await client.patch("/api/v1/plants/projects/999999", json={"customer_naming": "vw"}, headers=eng_auth)
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_project_customer_naming.py -q`
Expected: FAIL (KeyError `customer_naming`, 404/405 on PATCH).

- [ ] **Step 3: Model columns**

In `backend/app/models/entities.py`, inside `class Project`, after `status`:

```python
    # Filename convention of the customer delivering data to this project:
    # "vw" (VW group / Brose / Audi), "scout", or NULL = none. Used to read the
    # customer index and data kind from uploaded filenames.
    customer_naming: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

In `backend/app/models/part.py`, inside `class RevisionFile`, after `cad_data`:

```python
    # Data kind read from the customer filename (PCA, DMU, DRW, G02 ...) and a
    # free note shown under the filename (what a PCA vs a DMU file is for).
    kind: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 4: Migration**

```python
# backend/alembic/versions/075_customer_naming_and_file_note.py
"""075: project customer file naming + note on revision files.

projects.customer_naming: "vw" | "scout" | NULL, the filename convention used
to read the customer index and data kind on upload.
revision_files.kind: data kind from the filename (PCA, DMU, DRW, G02 ...).
revision_files.note: free text shown under the filename.

Revision ID: 075
Revises: 074
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "customer_naming" not in _cols(insp, "projects"):
        op.add_column("projects", sa.Column("customer_naming", sa.String(20), nullable=True))
    if "kind" not in _cols(insp, "revision_files"):
        op.add_column("revision_files", sa.Column("kind", sa.String(10), nullable=True))
    if "note" not in _cols(insp, "revision_files"):
        op.add_column("revision_files", sa.Column("note", sa.String(500), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    for col in ("note", "kind"):
        if col in _cols(insp, "revision_files"):
            op.drop_column("revision_files", col)
    if "customer_naming" in _cols(insp, "projects"):
        op.drop_column("projects", "customer_naming")
```

- [ ] **Step 5: Endpoint and list field**

In `backend/app/api/v1/plants.py`:

Add to imports: `from typing import List, Literal, Optional`.

Add after `class ProjectCreate`:

```python
class ProjectPatch(BaseModel):
    """Partial update of a project header. Every field optional; a field
    that is present with null clears it (customer_naming only)."""
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    customer_naming: Optional[Literal["vw", "scout"]] = None


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "code": p.code,
        "description": p.description,
        "status": p.status,
        "plant_id": p.plant_id,
        "customer_naming": p.customer_naming,
    }
```

Replace the dict literal in `get_all_projects` with `[_project_dict(p) for p in projects]`. Do the same for the `return {...}` at the end of `create_project` (`return _project_dict(project)`), and in `get_plant_projects` if it builds the same dict (read `:72-100` first; if its dict has extra keys, add `customer_naming` to it instead).

Add after `create_project`:

```python
@router.patch("/projects/{project_id}", response_model=dict)
async def patch_project(
    project_id: int,
    body: ProjectPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the project header. `customer_naming` may be set to null to clear it."""
    result = await db.execute(
        select(Project).join(Plant).where(
            (Project.id == project_id) & (Plant.organization_id == current_user.organization_id)
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    fields = body.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return _project_dict(project)
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/test_project_customer_naming.py tests/test_customer_package_api.py -q`
Expected: all PASS.

- [ ] **Step 7: Apply migration locally and commit**

Run: `docker exec claude-plm2-backend-1 alembic upgrade head` (the local backend container mounts the repo; if it does not pick up the new file, `docker cp backend/alembic/versions/075_customer_naming_and_file_note.py claude-plm2-backend-1:/app/alembic/versions/` first).

```bash
git add backend/alembic/versions/075_customer_naming_and_file_note.py backend/app/models/entities.py backend/app/models/part.py backend/app/api/v1/plants.py backend/tests/test_project_customer_naming.py
git commit -m "feat(projects): customer file naming convention on the project, PATCH endpoint, kind and note columns on revision files"
```

---

### Task 2: Filename parser registry

**Files:**
- Create: `backend/app/services/customer_naming.py`
- Test: `backend/tests/test_customer_naming.py`

**Interfaces:**
- Produces:
  ```python
  CONVENTIONS: dict[str, str]  # {"vw": "VW group", "scout": "Scout"}
  KIND_LABELS: dict[str, str]
  @dataclass class ParsedName: filename, customer_part_number, variant, kind, kind_label, model_type, customer_index, release, dated  (all Optional[str] except dated: Optional[date], filename: str)
  def parse_filename(filename: str, convention: str | None, customer_part_number: str | None = None) -> ParsedName
  def kind_label(kind: str | None) -> str | None
  ```
- Consumes: `index_from_filename` from `app.services.customer_package` (fallback when convention is None).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_customer_naming.py
from datetime import date

from app.services.customer_naming import CONVENTIONS, KIND_LABELS, kind_label, parse_filename


def test_vw_pca_part_model():
    p = parse_filename("206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.CATPart", "vw")
    assert p.customer_part_number == "206.881.479"
    assert p.variant is None
    assert p.kind == "PCA"
    assert p.kind_label.startswith("PCA engineering master")
    assert p.model_type == "TM"
    assert p.customer_index == "003"
    assert p.release == "B-RELEASE"
    assert p.dated == date(2026, 5, 28)


def test_vw_dmu_and_drawing():
    d = parse_filename("206_885_967____DMU_TM__004_____LATCH_COVER_40_____B-RELEASE_2026-05-28.CATPart", "vw")
    assert (d.kind, d.customer_index, d.dated) == ("DMU", "004", date(2026, 5, 28))
    z = parse_filename("206_887_233____DRW_TZ__001_____ISOFIX_COVER_______B-RELEASE___20260528.pdf", "vw")
    assert (z.kind, z.model_type, z.customer_index) == ("DRW", "TZ", "001")
    assert z.kind_label == KIND_LABELS["DRW"]


def test_vw_variant_letter_and_assembly_position():
    v = parse_filename("206_881_971_B__PCA_TM__001_____SEAT_BACK_PANEL____B-RELEASE___20260528.stp", "vw")
    assert v.customer_part_number == "206.881.971.B"
    assert v.variant == "B"
    g = parse_filename("206_881_971____G02_TM__004_003_MAP_POCKET_________B-RELEASE___20260528.stp", "vw")
    assert g.kind == "G02"
    assert g.kind_label == "Assembly position G02."
    assert g.customer_index == "004"


def test_vw_release_stage_variants():
    c = parse_filename("206_881_971____PCA_TM__003_____SEAT_BACK_PANEL____CP3_________20260220.stp", "vw")
    assert (c.release, c.dated) == ("CP3", date(2026, 2, 20))
    u = parse_filename("206_886_197____PCA_TM__003_000_CTR_BEARING_COVER__B_RELEASE___20260528.stp", "vw")
    assert (u.release, u.customer_index) == ("B_RELEASE", "003")


def test_vw_non_matching_name_is_empty_but_keeps_filename():
    p = parse_filename("readme.txt", "vw")
    assert p.filename == "readme.txt"
    assert p.customer_part_number is None and p.customer_index is None and p.kind is None


def test_none_convention_falls_back_to_letter_index():
    p = parse_filename("3CR807425B_Unterfahrschutz.stp", None, customer_part_number="3CR.807.425")
    assert p.customer_index == "B"
    assert p.kind is None
    q = parse_filename("3CR807425_Unterfahrschutz.stp", None, customer_part_number="3CR.807.425")
    assert q.customer_index is None


def test_scout_parses_like_vw_for_now():
    p = parse_filename("206_881_479____PCA_TM__003_____X___B-RELEASE___20260528.CATPart", "scout")
    assert p.customer_index == "003"


def test_unknown_convention_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_filename("x.stp", "bmw")


def test_registry_and_labels():
    assert CONVENTIONS == {"vw": "VW group", "scout": "Scout"}
    assert kind_label("PCA") == KIND_LABELS["PCA"]
    assert kind_label("G07") == "Assembly position G07."
    assert kind_label("XYZ") is None
    assert kind_label(None) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_customer_naming.py -q`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/services/customer_naming.py
"""Customer filename conventions: read the customer index and the data kind
from a delivered filename. Detection only prefills the upload dialog; the
user always chooses. See docs/CUSTOMER_DATA_INDEX.md, "Customer file names".
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services.customer_package import index_from_filename

CONVENTIONS: dict[str, str] = {"vw": "VW group", "scout": "Scout"}

KIND_LABELS: dict[str, str] = {
    "PCA": "PCA engineering master: full construction model with RPS, reference points/lines, "
           "annotations. Open this one in CATIA.",
    "DMU": "DMU lightweight solid for packaging and quick viewing, no RPS or references. Archive copy.",
    "DRW": "DRW customer part drawing.",
}

# 206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528
# 206_881_971_B__PCA_TM__001_____...          variant letter
# 206_881_971____G02_TM__004_003_MAP_POCKET   assembly position + two indexes
_VW_HEAD = re.compile(
    r"^(?P<a>\d{3})_(?P<b>\d{3})_(?P<c>\d{3})(?:_(?P<variant>[A-Z]))?_+"
    r"(?P<kind>[A-Z]\d{2}|[A-Z]{3})_(?P<model>[A-Z]{2})__(?P<index>\d{3})",
    re.I,
)
_VW_RELEASE = re.compile(r"(B[-_]RELEASE|CP\d|ADS)", re.I)
_VW_DATE = re.compile(r"(?<!\d)(\d{4})-?(\d{2})-?(\d{2})(?!\d)")
_G_POS = re.compile(r"^G\d{2}$")


@dataclass
class ParsedName:
    filename: str
    customer_part_number: Optional[str] = None
    variant: Optional[str] = None
    kind: Optional[str] = None
    kind_label: Optional[str] = None
    model_type: Optional[str] = None
    customer_index: Optional[str] = None
    release: Optional[str] = None
    dated: Optional[date] = None


def kind_label(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return None
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    if _G_POS.match(kind):
        return f"Assembly position {kind}."
    return None


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _parse_vw(filename: str) -> ParsedName:
    stem = _stem(filename)
    out = ParsedName(filename=filename)
    m = _VW_HEAD.match(stem)
    if not m:
        return out
    number = f"{m['a']}.{m['b']}.{m['c']}"
    variant = m["variant"].upper() if m["variant"] else None
    out.customer_part_number = f"{number}.{variant}" if variant else number
    out.variant = variant
    out.kind = m["kind"].upper()
    out.kind_label = kind_label(out.kind)
    out.model_type = m["model"].upper()
    out.customer_index = m["index"]
    tail = stem[m.end():]
    rel = _VW_RELEASE.search(tail)
    if rel:
        out.release = rel.group(1).upper()
    for dm in _VW_DATE.finditer(tail):
        try:
            out.dated = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            continue
    return out


def parse_filename(filename: str, convention: Optional[str],
                   customer_part_number: Optional[str] = None) -> ParsedName:
    """Parse one filename under a convention. None = the letter-index rule
    that the package flow has always used (needs the part's customer number)."""
    if convention is None:
        return ParsedName(filename=filename,
                          customer_index=index_from_filename(filename, customer_part_number))
    if convention not in CONVENTIONS:
        raise ValueError(f"Unknown customer naming convention '{convention}'")
    # Scout has not shown a distinct grammar yet; it parses like VW group.
    return _parse_vw(filename)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_customer_naming.py -q`
Expected: 9 passed. If `test_vw_release_stage_variants` fails on `CP3`, check the date regex picks `20260220` (it must, the `(?<!\d)` guard only blocks digits before).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/customer_naming.py backend/tests/test_customer_naming.py
git commit -m "feat(naming): customer filename convention registry with VW group parser"
```

---

### Task 3: Parse endpoint and package preview using the project convention

**Files:**
- Modify: `backend/app/api/v1/items/revision_files.py` (add GET parse route near `list_revision_files`, `:278`)
- Modify: `backend/app/services/customer_package_service.py:92-110` (preview)
- Test: `backend/tests/test_customer_naming_api.py`

**Interfaces:**
- Produces: `GET /api/v1/parts/{part_id}/files/parse?filenames=<n>&filenames=<n>[&convention=vw|scout|none]` → `{"convention": str|null, "conventions": {"vw": "VW group", "scout": "Scout"}, "rows": [ParsedName as dict, dated as ISO string]}`. `convention` omitted → the part's project setting. `convention=none` → letter rule.
- Consumes: Task 1 `Project.customer_naming`, Task 2 `parse_filename`, `CONVENTIONS`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_customer_naming_api.py
async def _mk_part(client, auth, seed, number, customer_number):
    r = await client.post("/api/v1/parts", headers=auth, json={
        "project_id": seed["project_id"], "part_number": number, "name": number,
        "part_type": "internal_mfg", "data_classification": "confidential",
        "customer_part_number": customer_number})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_parse_uses_project_convention_by_default(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "20-1", "206.881.479")
    await client.patch(f"/api/v1/plants/projects/{seed['project_id']}", json={"customer_naming": "vw"}, headers=eng_auth)
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth, params={
        "filenames": ["206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.CATPart",
                      "readme.txt"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["convention"] == "vw"
    assert body["conventions"] == {"vw": "VW group", "scout": "Scout"}
    assert body["rows"][0]["customer_index"] == "003"
    assert body["rows"][0]["kind"] == "PCA"
    assert body["rows"][0]["dated"] == "2026-05-28"
    assert body["rows"][1]["customer_index"] is None


async def test_parse_override_and_none(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "20-2", "3CR.807.425")
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth, params={
        "filenames": ["3CR807425B_x.stp"], "convention": "none"})
    assert r.json()["convention"] is None
    assert r.json()["rows"][0]["customer_index"] == "B"
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth, params={
        "filenames": ["206_881_479____DMU_TM__003_____X___B-RELEASE___20260528.CATPart"], "convention": "vw"})
    assert r.json()["rows"][0]["customer_index"] == "003"


async def test_parse_rejects_unknown_convention(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "20-3", None)
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth,
                         params={"filenames": ["a.stp"], "convention": "bmw"})
    assert r.status_code == 422


async def test_package_preview_reads_vw_index_when_project_set(client, eng_auth, seed):
    top = await _mk_part(client, eng_auth, seed, "20-10", "206.881.971")
    child = await _mk_part(client, eng_auth, seed, "20-11", "206.881.479")
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-05-01"})
    top_rev = r.json()["id"]
    await client.post(f"/api/v1/parts/{top}/revisions/{top_rev}/bom", headers=eng_auth,
                      json={"child_part_id": child, "quantity": 1})
    await client.patch(f"/api/v1/plants/projects/{seed['project_id']}", json={"customer_naming": "vw"}, headers=eng_auth)
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package/preview", headers=eng_auth, json={
        "statement": "review", "received_at": "2026-05-28", "package_index": None,
        "filenames": ["206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.stp"]})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0] if isinstance(r.json(), dict) else r.json()[0]
    assert row["part_id"] == child
    assert row["customer_index"] == "003"
```

Before running, open `backend/tests/test_customer_package_api.py:25-50` and copy the exact request shapes used there for the BOM line and preview (field names may differ from the sketch above: fix the test to match the real API, not the other way round).

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_customer_naming_api.py -q`
Expected: FAIL with 404 on the parse route and `customer_index` None in the preview.

- [ ] **Step 3: Parse endpoint**

In `backend/app/api/v1/items/revision_files.py` add imports:

```python
from dataclasses import asdict
from fastapi import Query
from app.models.entities import Project
from app.services.customer_naming import CONVENTIONS, parse_filename
```

Add before `list_revision_files`:

```python
@router.get("/{part_id}/files/parse", response_model=dict)
async def parse_upload_filenames(
    part_id: int,
    filenames: List[str] = Query(..., min_length=1, max_length=200),
    convention: Optional[str] = Query(None, description="vw | scout | none; omitted = project default"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read customer index and data kind from filenames before uploading.
    Detection only prefills the dialog; nothing is stored here."""
    part = await PartService.get_part(db, part_id)
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    if convention is None:
        project = await db.get(Project, part.project_id)
        effective = project.customer_naming if project else None
    elif convention == "none":
        effective = None
    elif convention in CONVENTIONS:
        effective = convention
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Unknown convention '{convention}'")
    rows = []
    for name in filenames:
        parsed = asdict(parse_filename(name, effective, part.customer_part_number))
        parsed["dated"] = parsed["dated"].isoformat() if parsed["dated"] else None
        rows.append(parsed)
    return {"convention": effective, "conventions": CONVENTIONS, "rows": rows}
```

Route ordering: FastAPI matches `/{part_id}/files/parse` before `/{part_id}/revisions/...` only if no other route swallows it; there is a `/{part_id}/files` POST for legacy uploads in `items/parts.py`, which is a different method and path, so no conflict. Run the tests to confirm.

- [ ] **Step 4: Package preview**

In `backend/app/services/customer_package_service.py`, `preview(...)`: load the project convention once and prefer it.

```python
        cands = await CustomerPackageService.candidates(session, assembly_id)
        assembly = await session.get(Part, assembly_id)
        project = await session.get(Project, assembly.project_id) if assembly else None
        convention = project.customer_naming if project else None
        rows: list[PackageRow] = []
        for name in filenames:
            row = PackageRow(filename=name)
            c = match_file(name, cands)
            if c is None:
                rows.append(row)
                continue
            row.part_id = c.part_id
            detected = None
            if convention:
                detected = parse_filename(name, convention, c.customer_part_number).customer_index
            row.customer_index = (detected
                                  or index_from_filename(name, c.customer_part_number)
                                  or (package_index or None))
```

Add the imports `from app.models.entities import Project` and `from app.services.customer_naming import parse_filename` at the top (check `Part` is already imported there; it is used on line 63).

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_customer_naming_api.py tests/test_customer_package_api.py tests/test_customer_package_service.py tests/test_customer_package_rules.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/items/revision_files.py backend/app/services/customer_package_service.py backend/tests/test_customer_naming_api.py
git commit -m "feat(naming): parse endpoint for upload filenames; package preview reads the project convention"
```

---

### Task 4: Upload endpoint stores `kind` and `note`, file list exposes them

**Files:**
- Modify: `backend/app/services/revision_file_service.py:96-150` (`store_revision_file`)
- Modify: `backend/app/api/v1/items/revision_files.py:51-65` (`_file_response_dict`), `:99-140` (upload)
- Test: `backend/tests/test_revision_file_note.py`

**Interfaces:**
- Produces: `POST /api/v1/parts/{part_id}/revisions/{revision_id}/files` form fields `file`, `file_type?`, `kind?` (≤10 chars), `note?` (≤500 chars). Response and `GET /api/v1/parts/revisions/{revision_id}/files` rows carry `"kind": str|null`, `"note": str|null`.
- `store_revision_file(session, revision, filename, contents, uploaded_by, content_type=None, file_type=None, kind=None, note=None)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_revision_file_note.py
async def test_upload_stores_kind_and_note(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("206_881_479____PCA_TM__003_____X.CATPart", b"catia-bytes", "application/octet-stream")},
        data={"kind": "PCA", "note": "PCA engineering master."}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] == "PCA"
    assert up.json()["note"] == "PCA engineering master."
    rows = (await client.get(f"/api/v1/parts/revisions/{part['revision_id']}/files", headers=eng_auth)).json()
    assert rows[0]["kind"] == "PCA"
    assert rows[0]["note"] == "PCA engineering master."


async def test_upload_without_kind_and_note_is_unchanged(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("drawing.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"file_type": "drawing"}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] is None and up.json()["note"] is None
    assert up.json()["file_type"] == "drawing"


async def test_note_on_a_drawing_is_kept_without_cad_data(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("d.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"file_type": "drawing", "kind": "DRW", "note": "DRW customer part drawing."}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] == "DRW"
    assert up.json()["note"] == "DRW customer part drawing."


async def test_note_too_long_is_rejected(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("d.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"note": "x" * 501}, headers=eng_auth)
    assert up.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_revision_file_note.py -q`
Expected: FAIL (KeyError `kind`).

- [ ] **Step 3: Service**

In `store_revision_file` change the signature to

```python
async def store_revision_file(session: AsyncSession, revision: PartRevision, filename: str, contents: bytes,
                              uploaded_by: int, content_type: str | None = None,
                              file_type: str | None = None, kind: str | None = None,
                              note: str | None = None) -> RevisionFile:
```

and when building `RevisionFile(...)` add the two columns from Task 1:

```python
        rev_file = RevisionFile(
            revision_id=revision.id, filename=filename, file_type=resolved_type,
            mime_type=content_type or MIME_MAP.get(ext, "application/octet-stream"),
            file_size=len(contents), file_path=file_path, cad_format=cad_format,
            kind=(kind or "").strip().upper() or None, note=(note or "").strip() or None,
            file_hash=hashlib.sha256(contents).hexdigest(),
            viewer_file_path=viewer_file_path, has_viewer=viewer_file_path is not None,
            uploaded_by=uploaded_by,
        )
```

`kind` is stored for every file type (a `DRW` on a drawing PDF as much as a `PCA` on CAD), so it lives in its own column, not in `cad_data`.

- [ ] **Step 4: Endpoint and response**

In `upload_revision_file` add form params after `file_type`:

```python
    kind: Optional[str] = Form(None, max_length=10),
    note: Optional[str] = Form(None, max_length=500),
```

and pass them: `store_revision_file(db, revision, file.filename or "", contents, current_user.id, content_type=file.content_type, file_type=file_type, kind=kind, note=note)`.

In `_file_response_dict` add `"kind": f.kind, "note": f.note,`.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_revision_file_note.py tests/test_file_provenance.py tests/test_project_customer_naming.py -q`
Expected: all PASS. (`test_note_too_long_is_rejected` relies on FastAPI's `Form(max_length=500)` returning 422; if it returns 400 through the endpoint's own handling, assert `in (400, 422)`.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/revision_file_service.py backend/app/api/v1/items/revision_files.py backend/tests/test_revision_file_note.py
git commit -m "feat(files): upload takes kind and note per revision file, listed back with the file"
```

---

### Task 5: Project header select for the naming convention

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx:35-40` (Project interface), `:1151` area (header)
- Test: `frontend/src/pages/ProjectDetailPage.naming.test.tsx`

**Interfaces:**
- Consumes: `GET /v1/plants/projects` rows with `customer_naming`; `PATCH /v1/plants/projects/{id}`.
- Produces: `CustomerNamingSelect` (exported from `ProjectDetailPage.tsx` for the test) with props `{ projectId: number; value: 'vw' | 'scout' | null }`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/ProjectDetailPage.naming.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerNamingSelect } from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('CustomerNamingSelect', () => {
  beforeEach(() => { clientMocks.patch.mockReset() })
  afterEach(cleanup)

  it('shows the current convention and saves a change', async () => {
    clientMocks.patch.mockResolvedValue({ data: { id: 2, customer_naming: 'vw' } })
    wrap(<CustomerNamingSelect projectId={2} value={null} />)
    const sel = screen.getByLabelText('Customer file naming') as HTMLSelectElement
    expect(sel.value).toBe('')
    fireEvent.change(sel, { target: { value: 'vw' } })
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/plants/projects/2', { customer_naming: 'vw' }))
  })

  it('clears with null', async () => {
    clientMocks.patch.mockResolvedValue({ data: { id: 2, customer_naming: null } })
    wrap(<CustomerNamingSelect projectId={2} value="scout" />)
    const sel = screen.getByLabelText('Customer file naming') as HTMLSelectElement
    expect(sel.value).toBe('scout')
    fireEvent.change(sel, { target: { value: '' } })
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/plants/projects/2', { customer_naming: null }))
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.naming.test.tsx`
Expected: FAIL, `CustomerNamingSelect` not exported.

- [ ] **Step 3: Implement**

In `ProjectDetailPage.tsx`:

Interface:

```ts
export type CustomerNaming = 'vw' | 'scout' | null;
export const CUSTOMER_NAMING_LABELS: Record<Exclude<CustomerNaming, null>, string> = { vw: 'VW group', scout: 'Scout' };

interface Project {
  id: number;
  name: string;
  code: string;
  status: string;
  customer_naming?: CustomerNaming;
}
```

Component, placed next to `RevisionFileRow` (module level, exported):

```tsx
export function CustomerNamingSelect({ projectId, value }: { projectId: number; value: CustomerNaming }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async (next: CustomerNaming) => {
      const res = await client.patch(`/v1/plants/projects/${projectId}`, { customer_naming: next });
      return res.data;
    },
    onSuccess: () => {
      toast.success('Customer file naming saved');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to save');
    },
  });
  return (
    <label className="flex items-center gap-2 text-xs text-slate-400">
      Customer file naming
      <select
        aria-label="Customer file naming"
        value={value ?? ''}
        disabled={save.isPending}
        onChange={(e) => save.mutate((e.target.value || null) as CustomerNaming)}
        className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-100 text-xs"
      >
        <option value="">None</option>
        {(Object.keys(CUSTOMER_NAMING_LABELS) as Array<'vw' | 'scout'>).map((k) => (
          <option key={k} value={k}>{CUSTOMER_NAMING_LABELS[k]}</option>
        ))}
      </select>
    </label>
  );
}
```

Header: at `:1151`, after the `<h1>` line that renders `{project.name} (…code)`, add on the same header row (read the surrounding JSX first; put it in the flex container that holds the title, right-aligned if there is one):

```tsx
<CustomerNamingSelect projectId={project.id} value={project.customer_naming ?? null} />
```

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.naming.test.tsx src/pages/ProjectDetailPage.files.test.tsx && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.naming.test.tsx
git commit -m "feat(ui): customer file naming select in the project header"
```

---

### Task 6: Default-level helper

**Files:**
- Create: `frontend/src/lib/uploadLevel.ts`
- Test: `frontend/src/lib/uploadLevel.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type UploadLevel = 'attach' | 'major' | 'proposal';
  export interface ParsedRow { filename: string; customer_part_number: string | null; variant: string | null; kind: string | null; kind_label: string | null; model_type: string | null; customer_index: string | null; release: string | null; dated: string | null }
  export function detectedIndex(rows: ParsedRow[]): { index: string | null; mixed: boolean }
  export function defaultLevel(detected: string | null, current: string | null | undefined): UploadLevel
  export function inferFileType(filename: string): 'cad' | 'drawing' | 'picture' | 'document'
  export function nextMajorName(revisionNames: string[], statement: 'review' | 'official'): string
  export function nextProposalName(revisionNames: string[], parent: string): string
  ```

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/uploadLevel.test.ts
import { describe, it, expect } from 'vitest'
import { detectedIndex, defaultLevel, inferFileType, nextMajorName, nextProposalName, type ParsedRow } from './uploadLevel'

const row = (o: Partial<ParsedRow>): ParsedRow => ({
  filename: 'f', customer_part_number: null, variant: null, kind: null, kind_label: null,
  model_type: null, customer_index: null, release: null, dated: null, ...o,
})

describe('detectedIndex', () => {
  it('returns the single index across files', () => {
    expect(detectedIndex([row({ customer_index: '003' }), row({ customer_index: '003' }), row({})]))
      .toEqual({ index: '003', mixed: false })
  })
  it('flags mixed indexes and returns none', () => {
    expect(detectedIndex([row({ customer_index: '003' }), row({ customer_index: '004' })]))
      .toEqual({ index: null, mixed: true })
  })
  it('handles nothing detected', () => {
    expect(detectedIndex([row({}), row({})])).toEqual({ index: null, mixed: false })
  })
})

describe('defaultLevel', () => {
  it('attaches when nothing detected', () => expect(defaultLevel(null, '003')).toBe('attach'))
  it('attaches when detected equals current', () => expect(defaultLevel('003', '003')).toBe('attach'))
  it('offers a new major when detected differs', () => expect(defaultLevel('004', '003')).toBe('major'))
  it('offers a new major when current has no index but a file carries one', () => expect(defaultLevel('003', null)).toBe('major'))
})

describe('inferFileType', () => {
  it('maps extensions', () => {
    expect(inferFileType('a.CATPart')).toBe('cad')
    expect(inferFileType('a.stp')).toBe('cad')
    expect(inferFileType('a.pdf')).toBe('drawing')
    expect(inferFileType('a.dxf')).toBe('drawing')
    expect(inferFileType('a.png')).toBe('picture')
    expect(inferFileType('a.xlsx')).toBe('document')
  })
})

describe('next names', () => {
  it('next review and official majors', () => {
    expect(nextMajorName(['E1', 'E1.1', 'E2'], 'review')).toBe('E3')
    expect(nextMajorName(['E1', 'E2'], 'official')).toBe('1')
    expect(nextMajorName(['E1', '1', '1.1', '2'], 'official')).toBe('3')
    expect(nextMajorName([], 'review')).toBe('E1')
  })
  it('next proposal under a parent', () => {
    expect(nextProposalName(['E1', 'E1.1', 'E1.2'], 'E1')).toBe('E1.3')
    expect(nextProposalName(['E1'], 'E1')).toBe('E1.1')
    expect(nextProposalName(['1', '1.1'], '1')).toBe('1.2')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/uploadLevel.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

```ts
// frontend/src/lib/uploadLevel.ts
/** Pure helpers for the upload dialog: which level to preselect and what
 *  the next revision would be called. Detection prefills, the user decides. */
export type UploadLevel = 'attach' | 'major' | 'proposal';

export interface ParsedRow {
  filename: string;
  customer_part_number: string | null;
  variant: string | null;
  kind: string | null;
  kind_label: string | null;
  model_type: string | null;
  customer_index: string | null;
  release: string | null;
  dated: string | null;
}

export function detectedIndex(rows: ParsedRow[]): { index: string | null; mixed: boolean } {
  const found = Array.from(new Set(rows.map((r) => r.customer_index).filter((x): x is string => !!x)));
  if (found.length === 0) return { index: null, mixed: false };
  if (found.length > 1) return { index: null, mixed: true };
  return { index: found[0], mixed: false };
}

export function defaultLevel(detected: string | null, current: string | null | undefined): UploadLevel {
  if (!detected) return 'attach';
  if ((current ?? '').trim().toLowerCase() === detected.trim().toLowerCase()) return 'attach';
  return 'major';
}

const CAD = ['.step', '.stp', '.iges', '.igs', '.stl', '.jt', '.catpart', '.catproduct'];
const DRAWING = ['.pdf', '.dxf', '.dwg'];
const PICTURE = ['.png', '.jpg', '.jpeg', '.gif', '.webp'];

export function inferFileType(filename: string): 'cad' | 'drawing' | 'picture' | 'document' {
  const lower = filename.toLowerCase();
  const ext = lower.includes('.') ? lower.slice(lower.lastIndexOf('.')) : '';
  if (CAD.includes(ext)) return 'cad';
  if (DRAWING.includes(ext)) return 'drawing';
  if (PICTURE.includes(ext)) return 'picture';
  return 'document';
}

const majors = (names: string[]) => names.filter((n) => !n.includes('.'));

export function nextMajorName(revisionNames: string[], statement: 'review' | 'official'): string {
  const ms = majors(revisionNames);
  if (statement === 'review') {
    const n = Math.max(0, ...ms.filter((m) => m.startsWith('E')).map((m) => parseInt(m.slice(1), 10) || 0));
    return `E${n + 1}`;
  }
  const n = Math.max(0, ...ms.filter((m) => !m.startsWith('E')).map((m) => parseInt(m, 10) || 0));
  return String(n + 1);
}

export function nextProposalName(revisionNames: string[], parent: string): string {
  const minors = revisionNames
    .filter((n) => n.startsWith(`${parent}.`))
    .map((n) => parseInt(n.slice(parent.length + 1), 10) || 0);
  return `${parent}.${Math.max(0, ...minors) + 1}`;
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/lib/uploadLevel.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/uploadLevel.ts frontend/src/lib/uploadLevel.test.ts
git commit -m "feat(ui): upload level helpers (detected index, default level, next names)"
```

---

### Task 7: UploadDialog component

**Files:**
- Create: `frontend/src/components/parts/UploadDialog.tsx`
- Test: `frontend/src/components/parts/UploadDialog.test.tsx`

**Interfaces:**
- Consumes: Task 6 helpers; `GET /v1/parts/{partId}/files/parse` (Task 3); `POST /v1/parts/{partId}/revisions/customer-data` body `{statement, received_at, customer_index?, summary?}`; `POST /v1/parts/{partId}/revisions/proposals` body `{parent_revision_id, summary?}`; `POST /v1/parts/{partId}/revisions/{revId}/files` multipart `file, file_type, kind?, note?` (Task 4).
- Produces:
  ```ts
  export interface UploadDialogProps {
    open: boolean;
    partId: number;
    currentRevision: { id: number; revision_name: string; customer_index?: string | null; phase: 'review' | 'official' };
    revisionNames: string[];        // every revision of the part, for next names
    officialOnly: boolean;          // part already has official data
    projectNaming: 'vw' | 'scout' | null;
    initialFiles: File[];
    onClose(): void;
    onDone(targetRevisionId: number): void;
  }
  export default function UploadDialog(props: UploadDialogProps): JSX.Element | null
  ```

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/parts/UploadDialog.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UploadDialog from './UploadDialog'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const parsed = (filename: string, over: Record<string, unknown> = {}) => ({
  filename, customer_part_number: '206.881.479', variant: null, kind: 'PCA',
  kind_label: 'PCA engineering master: full construction model.', model_type: 'TM',
  customer_index: '003', release: 'B-RELEASE', dated: '2026-05-28', ...over,
})
const f = (name: string) => new File(['x'], name, { type: 'application/octet-stream' })
const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const baseProps = {
  open: true, partId: 7,
  currentRevision: { id: 9, revision_name: 'E1', customer_index: '003', phase: 'review' as const },
  revisionNames: ['E1'], officialOnly: false, projectNaming: 'vw' as const,
  onClose: vi.fn(), onDone: vi.fn(),
}

describe('UploadDialog', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((_url: string, cfg?: { params?: { filenames: string[]; convention?: string } }) => {
      const names: string[] = cfg?.params?.filenames ?? []
      const conv = cfg?.params?.convention ?? 'vw'
      return Promise.resolve({ data: {
        convention: conv === 'none' ? null : conv, conventions: { vw: 'VW group', scout: 'Scout' },
        rows: names.map((n) => conv === 'none'
          ? parsed(n, { kind: null, kind_label: null, customer_index: null })
          : parsed(n, { customer_index: n.includes('__004__') ? '004' : '003', kind: n.includes('DMU') ? 'DMU' : 'PCA' })),
      } })
    })
    clientMocks.post.mockResolvedValue({ data: { id: 42, revision_name: 'E2' } })
  })
  afterEach(cleanup)

  it('lists files with detected kind and index, and defaults to attach when the index matches', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__003_____X.CATPart'), f('206_881_479____DMU_TM__003_____X.CATPart')]} />)
    await screen.findByText('PCA')
    expect(screen.getByText('DMU')).toBeTruthy()
    expect(screen.getAllByText('003').length).toBeGreaterThan(0)
    expect((screen.getByLabelText(/Attach to E1/) as HTMLInputElement).checked).toBe(true)
  })

  it('defaults to next customer data when the detected index differs and prefills it', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__004_____X.CATPart')]} />)
    await screen.findByText('PCA')
    expect((screen.getByLabelText(/Next customer data/) as HTMLInputElement).checked).toBe(true)
    const idx = screen.getByLabelText('Customer index') as HTMLInputElement
    expect(idx.value).toBe('004')
    expect(screen.getByText(/current 003/)).toBeTruthy()
    expect(screen.getByText(/detected 004/)).toBeTruthy()
    expect((screen.getByLabelText('Received on') as HTMLInputElement).value).toBe('2026-05-28')
  })

  it('warns on mixed indexes and leaves the index empty', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('a____PCA_TM__003__.CATPart'), f('b____PCA_TM__004__.CATPart')]} />)
    await screen.findByText(/different customer indexes/i)
    fireEvent.click(screen.getByLabelText(/Next customer data/))
    expect((screen.getByLabelText('Customer index') as HTMLInputElement).value).toBe('')
  })

  it('re-parses when the convention changes', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__003_____X.CATPart')]} />)
    await screen.findByText('PCA')
    fireEvent.change(screen.getByLabelText('Naming convention'), { target: { value: 'none' } })
    await waitFor(() => expect(clientMocks.get).toHaveBeenLastCalledWith('/v1/parts/7/files/parse',
      expect.objectContaining({ params: expect.objectContaining({ convention: 'none' }) })))
  })

  it('proposal level hides the customer index', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('x.pdf')]} />)
    await screen.findByLabelText(/Attach to E1/)
    fireEvent.click(screen.getByLabelText(/Next proposal/))
    expect(screen.queryByLabelText('Customer index')).toBeNull()
    expect(screen.getByText(/E1\.1/)).toBeTruthy()
  })

  it('creates the major with the overridden index, then uploads every file with kind and note', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__004_____X.CATPart'), f('206_881_479____DMU_TM__004_____X.CATPart')]} />)
    await screen.findByText('PCA')
    fireEvent.change(screen.getByLabelText('Customer index'), { target: { value: '004a' } })
    fireEvent.click(screen.getByText('Upload'))
    await waitFor(() => expect(baseProps.onDone).toHaveBeenCalledWith(42))
    expect(clientMocks.post.mock.calls[0][0]).toBe('/v1/parts/7/revisions/customer-data')
    expect(clientMocks.post.mock.calls[0][1]).toEqual(expect.objectContaining({ statement: 'review', received_at: '2026-05-28', customer_index: '004a' }))
    const uploads = clientMocks.post.mock.calls.slice(1)
    expect(uploads).toHaveLength(2)
    expect(uploads[0][0]).toBe('/v1/parts/7/revisions/42/files')
    const fd = uploads[0][1] as FormData
    expect(fd.get('file_type')).toBe('cad')
    expect(fd.get('kind')).toBe('PCA')
    expect(String(fd.get('note'))).toContain('engineering master')
  })

  it('attach level uploads to the current revision without creating anything', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__003_____X.CATPart')]} />)
    await screen.findByText('PCA')
    fireEvent.click(screen.getByText('Upload'))
    await waitFor(() => expect(baseProps.onDone).toHaveBeenCalledWith(9))
    expect(clientMocks.post.mock.calls.every((c) => c[0] === '/v1/parts/7/revisions/9/files')).toBe(true)
  })

  it('stops on the first failed upload and reports which landed', async () => {
    clientMocks.post
      .mockResolvedValueOnce({ data: { id: 1 } })
      .mockRejectedValueOnce({ response: { data: { detail: 'Unsupported file extension' } } })
    wrap(<UploadDialog {...baseProps} initialFiles={[f('a____PCA_TM__003__.CATPart'), f('b____DMU_TM__003__.CATPart'), f('c____DRW_TZ__001__.pdf')]} />)
    await screen.findByText('PCA')
    fireEvent.click(screen.getByText('Upload'))
    await screen.findByText(/1 of 3 uploaded/)
    expect(screen.getByText(/Unsupported file extension/)).toBeTruthy()
    expect(baseProps.onDone).not.toHaveBeenCalled()
  })

  it('lets the user change a file type and remove a file', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('scan.pdf'), f('x____PCA_TM__003__.CATPart')]} />)
    await screen.findByText('PCA')
    const types = screen.getAllByLabelText('File type') as HTMLSelectElement[]
    expect(types[0].value).toBe('drawing')
    fireEvent.change(types[0], { target: { value: 'document' } })
    expect(types[0].value).toBe('document')
    fireEvent.click(screen.getAllByLabelText('Remove file')[1])
    expect(screen.queryByText('PCA')).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/parts/UploadDialog.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/parts/UploadDialog.tsx
/**
 * UploadDialog - put customer files on a part. Reads the customer index and
 * data kind from the filenames (per naming convention) to prefill; the user
 * picks the level: attach to the current revision, next customer major, or
 * next proposal. E-numbers are our filing order, the customer index is
 * informational and optional.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import {
  defaultLevel, detectedIndex, inferFileType, nextMajorName, nextProposalName,
  type ParsedRow, type UploadLevel,
} from '../../lib/uploadLevel';

export interface UploadDialogProps {
  open: boolean;
  partId: number;
  currentRevision: { id: number; revision_name: string; customer_index?: string | null; phase: 'review' | 'official' };
  revisionNames: string[];
  officialOnly: boolean;
  projectNaming: 'vw' | 'scout' | null;
  initialFiles: File[];
  onClose(): void;
  onDone(targetRevisionId: number): void;
}

type FileType = 'cad' | 'drawing' | 'picture' | 'document';
interface Row { file: File; fileType: FileType }

const TYPE_OPTIONS: FileType[] = ['cad', 'drawing', 'picture', 'document'];
const ACCEPT = '.step,.stp,.iges,.igs,.stl,.jt,.catpart,.catproduct,.pdf,.dxf,.dwg,.png,.jpg,.jpeg,.gif,.webp,.docx,.xlsx,.pptx,.txt,.md,.csv';
const MAX_BYTES = 100 * 1024 * 1024;

const inputCls = 'mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100 text-sm';

export default function UploadDialog(props: UploadDialogProps) {
  const { open, partId, currentRevision, revisionNames, officialOnly, projectNaming, initialFiles, onClose, onDone } = props;
  const [rows, setRows] = useState<Row[]>(() => initialFiles.map((file) => ({ file, fileType: inferFileType(file.name) })));
  const [convention, setConvention] = useState<'vw' | 'scout' | 'none'>(projectNaming ?? 'none');
  const [level, setLevel] = useState<UploadLevel | null>(null); // null until the first parse decides the default
  const [statement, setStatement] = useState<'review' | 'official'>(officialOnly ? 'official' : 'review');
  const [receivedAt, setReceivedAt] = useState('');
  const [index, setIndex] = useState('');
  const [summary, setSummary] = useState('');
  const [progress, setProgress] = useState<{ done: number; total: number; error?: string } | null>(null);

  const names = rows.map((r) => r.file.name);
  const parse = useQuery({
    queryKey: ['parse-filenames', partId, convention, names],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/files/parse`, { params: { filenames: names, convention } });
      return res.data as { convention: string | null; conventions: Record<string, string>; rows: ParsedRow[] };
    },
    enabled: open && names.length > 0,
  });
  const parsedByName = useMemo(() => {
    const m = new Map<string, ParsedRow>();
    parse.data?.rows.forEach((r) => m.set(r.filename, r));
    return m;
  }, [parse.data]);
  const detected = useMemo(() => detectedIndex(parse.data?.rows ?? []), [parse.data]);
  const firstDate = parse.data?.rows.find((r) => r.dated)?.dated ?? null;

  // Prefill once per parse result: level, index, received date. The user's
  // later edits are not overwritten (level only set while null).
  useEffect(() => {
    if (!parse.data) return;
    setLevel((prev) => prev ?? defaultLevel(detected.index, currentRevision.customer_index));
    setIndex(detected.index ?? '');
    setReceivedAt(firstDate ?? new Date().toISOString().slice(0, 10));
  }, [parse.data, detected.index, firstDate, currentRevision.customer_index]);

  if (!open) return null;

  const effectiveStatement = officialOnly ? 'official' : statement;
  const majorName = nextMajorName(revisionNames, effectiveStatement);
  const proposalName = nextProposalName(revisionNames, currentRevision.revision_name);
  const currentLabel = currentRevision.customer_index
    ? `${currentRevision.revision_name} · ${currentRevision.customer_index}` : currentRevision.revision_name;

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const next: Row[] = [];
    Array.from(list).forEach((file) => {
      if (file.size > MAX_BYTES) { toast.error(`${file.name}: over 100MB`); return; }
      if (rows.some((r) => r.file.name === file.name)) return;
      next.push({ file, fileType: inferFileType(file.name) });
    });
    if (next.length) { setRows((r) => [...r, ...next]); setLevel(null); }
  };

  const submit = async () => {
    if (rows.length === 0 || !level) return;
    setProgress({ done: 0, total: rows.length });
    let targetId = currentRevision.id;
    try {
      if (level === 'major') {
        const res = await client.post(`/v1/parts/${partId}/revisions/customer-data`, {
          statement: effectiveStatement, received_at: receivedAt,
          customer_index: index.trim() || undefined, summary: summary.trim() || undefined,
        });
        targetId = res.data.id;
      } else if (level === 'proposal') {
        const res = await client.post(`/v1/parts/${partId}/revisions/proposals`, {
          parent_revision_id: currentRevision.id, summary: summary.trim() || undefined,
        });
        targetId = res.data.id;
      }
    } catch (error: unknown) {
      const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not create the revision';
      setProgress({ done: 0, total: rows.length, error: msg });
      return;
    }
    let done = 0;
    for (const row of rows) {
      const parsed = parsedByName.get(row.file.name);
      const fd = new FormData();
      fd.append('file', row.file);
      fd.append('file_type', row.fileType);
      if (parsed?.kind) fd.append('kind', parsed.kind);
      if (parsed?.kind_label) fd.append('note', parsed.kind_label);
      try {
        await client.post(`/v1/parts/${partId}/revisions/${targetId}/files`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
        done += 1;
        setProgress({ done, total: rows.length });
      } catch (error: unknown) {
        const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || `Upload of ${row.file.name} failed`;
        setProgress({ done, total: rows.length, error: `${row.file.name}: ${msg}` });
        return;
      }
    }
    toast.success(`${done} file${done === 1 ? '' : 's'} uploaded`);
    onDone(targetId);
  };

  const busy = progress !== null && !progress.error;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-2xl w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-bold text-slate-100">Upload files to {currentLabel}</h3>

        {/* Files */}
        <div className="space-y-1">
          {rows.map((row) => {
            const p = parsedByName.get(row.file.name);
            return (
              <div key={row.file.name} className="flex items-center gap-2 p-2 rounded bg-slate-900 border border-slate-700 text-xs">
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-slate-100 truncate">{row.file.name}</p>
                  <div className="flex items-center gap-2 mt-1 text-slate-400">
                    <span>{(row.file.size / 1024 / 1024).toFixed(2)} MB</span>
                    {p?.kind && <span title={p.kind_label ?? undefined} className="px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300">{p.kind}</span>}
                    {p?.customer_index && <span className="px-1.5 py-0.5 rounded bg-slate-700 text-slate-200">{p.customer_index}</span>}
                  </div>
                  {p?.kind_label && <p className="text-slate-500 mt-1 truncate">{p.kind_label}</p>}
                </div>
                <select aria-label="File type" value={row.fileType} disabled={busy}
                  onChange={(e) => setRows((rs) => rs.map((r) => r === row ? { ...r, fileType: e.target.value as FileType } : r))}
                  className="px-2 py-1 rounded bg-slate-800 border border-slate-600 text-slate-100">
                  {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <button aria-label="Remove file" disabled={busy} onClick={() => { setRows((rs) => rs.filter((r) => r !== row)); setLevel(null); }}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-red-700 text-slate-200">×</button>
              </div>
            );
          })}
          <label className="block text-xs text-slate-400 border border-dashed border-slate-600 rounded p-2 text-center cursor-pointer hover:border-slate-500">
            + Add more files
            <input type="file" multiple accept={ACCEPT} className="hidden" disabled={busy} onChange={(e) => addFiles(e.target.files)} />
          </label>
          {parse.isError && <p className="text-xs text-red-400">Could not read the filenames, you can still upload.</p>}
        </div>

        {/* Convention */}
        <label className="block text-sm text-slate-400">Naming convention
          <select aria-label="Naming convention" value={convention} disabled={busy}
            onChange={(e) => { setConvention(e.target.value as 'vw' | 'scout' | 'none'); setLevel(null); }} className={inputCls}>
            <option value="none">None</option>
            {Object.entries(parse.data?.conventions ?? { vw: 'VW group', scout: 'Scout' }).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
          <span className="text-xs text-slate-500">Used to read the customer index and data kind from the filenames.</span>
        </label>
        {detected.mixed && (
          <p className="text-xs text-amber-300">The files carry different customer indexes. Check them, or split the upload.</p>
        )}

        {/* Level */}
        <fieldset className="space-y-2">
          <legend className="text-sm text-slate-400">Where do these files go?</legend>
          <label className="flex items-center gap-2 text-slate-100 text-sm">
            <input type="radio" name="level" checked={level === 'attach'} disabled={busy} onChange={() => setLevel('attach')} />
            Attach to {currentLabel}
          </label>
          <label className="flex items-center gap-2 text-slate-100 text-sm">
            <input type="radio" name="level" checked={level === 'major'} disabled={busy} onChange={() => setLevel('major')} />
            Next customer data → {majorName}
            <span className="text-xs text-slate-400">customer sent a new data state</span>
          </label>
          {level === 'major' && (
            <div className="ml-6 space-y-2">
              <div className="flex gap-4 text-sm text-slate-100">
                {(['review', 'official'] as const).map((s) => (
                  <label key={s} className={`flex items-center gap-1 ${officialOnly && s === 'review' ? 'opacity-40' : ''}`}>
                    <input type="radio" name="statement" checked={effectiveStatement === s} disabled={busy || (officialOnly && s === 'review')} onChange={() => setStatement(s)} />
                    <span className="capitalize">{s}</span>
                  </label>
                ))}
              </div>
              <label className="block text-sm text-slate-400">Received on
                <input aria-label="Received on" type="date" value={receivedAt} disabled={busy} onChange={(e) => setReceivedAt(e.target.value)} className={inputCls} />
              </label>
              <label className="block text-sm text-slate-400">Customer index
                <input aria-label="Customer index" value={index} disabled={busy} onChange={(e) => setIndex(e.target.value)} placeholder="optional" className={inputCls} />
                <span className="text-xs text-slate-500">
                  current {currentRevision.customer_index || 'none'} · detected {detected.index || (detected.mixed ? 'mixed' : 'none')}
                </span>
              </label>
              <label className="block text-sm text-slate-400">Summary (optional)
                <textarea value={summary} rows={2} disabled={busy} onChange={(e) => setSummary(e.target.value)} className={inputCls} />
              </label>
            </div>
          )}
          <label className="flex items-center gap-2 text-slate-100 text-sm">
            <input type="radio" name="level" checked={level === 'proposal'} disabled={busy} onChange={() => setLevel('proposal')} />
            Next proposal → {proposalName}
            <span className="text-xs text-slate-400">our own iteration, feasibility</span>
          </label>
          {level === 'proposal' && (
            <label className="ml-6 block text-sm text-slate-400">Summary (optional)
              <textarea value={summary} rows={2} disabled={busy} onChange={(e) => setSummary(e.target.value)} className={inputCls} />
            </label>
          )}
        </fieldset>

        {progress && (
          <p className={`text-sm ${progress.error ? 'text-red-400' : 'text-slate-300'}`}>
            {progress.done} of {progress.total} uploaded{progress.error ? ` · ${progress.error}` : ''}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="px-4 py-2 rounded bg-slate-700 text-slate-100 hover:bg-slate-600">
            {progress?.error ? 'Close' : 'Cancel'}
          </button>
          <button onClick={submit} disabled={busy || rows.length === 0 || !level || (level === 'major' && !receivedAt)}
            className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:bg-slate-600">
            {busy ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

Notes for the implementer:
- The test "defaults to attach when nothing detected" is covered by the `x.pdf` proposal test (`Attach to E1` is found checked before clicking proposal). Keep it.
- `useQuery` key includes `names`, so adding or removing a file re-parses. `setLevel(null)` on those changes lets the default recompute.
- Axios FormData: the test inspects `FormData.get(...)`; jsdom supports it.

- [ ] **Step 4: Run tests and type check**

Run: `cd frontend && npx vitest run src/components/parts/UploadDialog.test.tsx && npx tsc --noEmit`
Expected: 9 passed, no type errors. If the "re-parses" assertion fails on call shape, log `clientMocks.get.mock.calls` and align the `params` object (it must be `{ filenames: string[], convention: string }`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/parts/UploadDialog.tsx frontend/src/components/parts/UploadDialog.test.tsx
git commit -m "feat(ui): upload dialog with detected kind and customer index, level choice (attach / next major / proposal)"
```

---

### Task 8: Wire the dialog into the project page, show kind and note on file rows

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx:122-134` (RevisionFile interface), `:895-960` (RevisionFileRow), `:1431-1450` (files list + uploader)
- Test: `frontend/src/pages/ProjectDetailPage.files.test.tsx` (extend), `frontend/src/pages/ProjectDetailPage.upload.test.tsx` (new)

**Interfaces:**
- Consumes: Task 7 `UploadDialog`, Task 4 `kind`/`note` on file rows, Task 5 `project.customer_naming`.

- [ ] **Step 1: Write the failing tests**

Add to `ProjectDetailPage.files.test.tsx` inside `describe('RevisionFileRow provenance')`:

```tsx
  it('shows the data kind chip and the note', () => {
    wrap(<RevisionFileRow file={file({ kind: 'PCA', note: 'PCA engineering master: open this one in CATIA.' })}
      isViewing={false} locked={false} />)
    expect(screen.getByText('PCA')).toBeTruthy()
    expect(screen.getByText(/open this one in CATIA/)).toBeTruthy()
  })

  it('renders nothing extra for a file without kind or note', () => {
    wrap(<RevisionFileRow file={file()} isViewing={false} locked={false} />)
    expect(screen.queryByTestId('file-kind')).toBeNull()
    expect(screen.queryByTestId('file-note')).toBeNull()
  })
```

New `ProjectDetailPage.upload.test.tsx` (copy the mock block and `vi.mock` stubs from `ProjectDetailPage.files.test.tsx:1-25`, but do **not** stub `CADUploader`; stub `../components/parts/UploadDialog` with a spy that records its props):

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
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
const dialogProps = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }))
vi.mock('../components/parts/UploadDialog', () => ({
  default: (props: Record<string, unknown>) => { dialogProps.last = props; return <div>upload-dialog</div> },
}))

describe('ProjectDetailPage upload entry point', () => {
  beforeEach(() => {
    dialogProps.last = null
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects')
        return Promise.resolve({ data: [{ id: 2, name: 'Atlas', code: 'ATL', status: 'active', customer_naming: 'vw' }] })
      if (url === '/v1/parts/project/2')
        return Promise.resolve({ data: [{ id: 5, part_number: '20-1', name: 'Cover', part_type: 'internal_mfg',
          active_revision_id: 9, item_category: 'article', parent_part_id: null }] })
      if (url === '/v1/parts/5/revisions')
        return Promise.resolve({ data: [{ id: 9, part_id: 5, revision_name: 'E1', phase: 'review', status: 'approved',
          created_at: '2026-05-28', customer_index: '003' }] })
      if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('opens the upload dialog with the project convention and the selected revision when files are dropped', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/projects/2']}>
          <Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>)
    fireEvent.click(await screen.findByText('Cover'))
    const zone = await screen.findByTestId('upload-dropzone')
    const f = new File(['x'], '206_881_479____PCA_TM__003_____X.CATPart')
    fireEvent.drop(zone, { dataTransfer: { files: [f] } })
    await waitFor(() => expect(screen.getByText('upload-dialog')).toBeTruthy())
    expect(dialogProps.last).toEqual(expect.objectContaining({
      partId: 5, projectNaming: 'vw', officialOnly: false, revisionNames: ['E1'],
    }))
    expect((dialogProps.last as { currentRevision: { id: number } }).currentRevision.id).toBe(9)
    expect((dialogProps.last as { initialFiles: File[] }).initialFiles[0].name).toBe(f.name)
  })
})
```

If the part list click needs a different selector (the tree renders the name inside a row), open `ProjectDetailPage.files.test.tsx:60-90` and copy how it selects the part there.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.files.test.tsx src/pages/ProjectDetailPage.upload.test.tsx`
Expected: the two new file-row tests and the upload test FAIL.

- [ ] **Step 3: File row**

In the `RevisionFile` interface add `kind?: string | null; note?: string | null;`.

In `RevisionFileRow`, inside the `<div className="flex items-center gap-2">` after the filename `<p>`:

```tsx
          {file.kind && (
            <span data-testid="file-kind" title={file.note ?? undefined}
              className="px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 bg-blue-900/50 text-blue-300">{file.kind}</span>
          )}
```

and after the size/no-preview line:

```tsx
        {file.note && <p data-testid="file-note" className="text-slate-500 text-xs truncate">{file.note}</p>}
```

- [ ] **Step 4: Replace the uploader with a drop zone that opens the dialog**

Import: `import UploadDialog from '../components/parts/UploadDialog';` and remove the `CADUploader` import if nothing else on the page uses it (grep first; if the legacy part-level path uses it elsewhere on this page, keep the import).

State next to `showCustomerData`:

```tsx
  const [uploadFiles, setUploadFiles] = useState<File[] | null>(null);
  const [uploadDrag, setUploadDrag] = useState(false);
```

Replace `<CADUploader partId={selectedPart.id} revisionId={selectedRevisionId} compact />` with:

```tsx
                        <div
                          data-testid="upload-dropzone"
                          className={`border-2 border-dashed rounded-lg p-2 text-center text-xs cursor-pointer transition-colors ${uploadDrag ? 'border-blue-500 bg-blue-50/10' : 'border-slate-600 hover:border-slate-500 bg-slate-800/50'}`}
                          onDragEnter={(e) => { e.preventDefault(); setUploadDrag(true); }}
                          onDragOver={(e) => { e.preventDefault(); setUploadDrag(true); }}
                          onDragLeave={(e) => { e.preventDefault(); setUploadDrag(false); }}
                          onDrop={(e) => { e.preventDefault(); setUploadDrag(false); setUploadFiles(Array.from(e.dataTransfer.files)); }}
                          onClick={() => document.getElementById('upload-dropzone-input')?.click()}
                        >
                          <input id="upload-dropzone-input" type="file" multiple className="hidden"
                            onChange={(e) => { if (e.target.files?.length) setUploadFiles(Array.from(e.target.files)); e.target.value = ''; }} />
                          <p className="text-slate-400">+ Drop files here or click to upload (CAD, drawing, picture, document)</p>
                        </div>
```

After the files list block (still inside the `selectedRevisionId` guard, same JSX level as the dialog for customer data), render the dialog:

```tsx
                      {uploadFiles && selectedRevision && (
                        <UploadDialog
                          open
                          partId={selectedPart.id}
                          currentRevision={{ id: selectedRevision.id, revision_name: selectedRevision.revision_name,
                            customer_index: selectedRevision.customer_index, phase: selectedRevision.phase }}
                          revisionNames={(partRevisions ?? []).map((r) => r.revision_name)}
                          officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
                          projectNaming={project?.customer_naming ?? null}
                          initialFiles={uploadFiles}
                          onClose={() => setUploadFiles(null)}
                          onDone={(targetRevisionId) => {
                            setUploadFiles(null);
                            queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                            queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
                            queryClient.invalidateQueries({ queryKey: ['parts', id] });
                            setSelectedRevisionId(targetRevisionId);
                          }}
                        />
                      )}
```

`project` here is the result of `useProject(...)` already in scope on the page (check its variable name near `:1150`; it is used as `project.name`).

- [ ] **Step 5: Run tests and type check**

Run: `cd frontend && npx vitest run src/pages/ && npx tsc --noEmit`
Expected: all page tests PASS (the old `files.test.tsx` still stubs `CADUploader`, harmless), no type errors.

- [ ] **Step 6: Full suites**

Run: `cd frontend && npx vitest run` and `cd backend && uv run pytest -q`
Expected: all green. Fix anything the change broke before committing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.files.test.tsx frontend/src/pages/ProjectDetailPage.upload.test.tsx
git commit -m "feat(ui): project page uploads go through the guided dialog; file rows show kind and note"
```

---

### Task 9: Docs and manual check

**Files:**
- Modify: `docs/CUSTOMER_DATA_INDEX.md` ("Recording customer data" section and "Customer file names")

- [ ] **Step 1: Document the flow**

Under "Recording customer data", replace the numbered list's step 4 ("Save. … Upload the files to it as usual.") with a short paragraph and add a new subsection:

```markdown
### Uploading files (project page)

Drop files on the part's file list. The dialog reads each filename under the
project's **customer file naming** convention (set in the project header,
overridable in the dialog) and shows the data kind (PCA, DMU, DRW) and the
customer index it found. Then choose where the files go:

- **Attach to the current revision** (`E1 · 003`).
- **Next customer data → E2** (or `2` once official): statement, received date
  and customer index are prefilled from the filenames, all editable, the index
  optional.
- **Next proposal → E1.1**: our own iteration, no customer index.

The E number is always our filing order; the customer index is informational
and shown next to it. Detection only prefills, you decide.
```

- [ ] **Step 2: Manual check on the local app**

Run the local stack (`docker compose` at `/home/nitrolinux/claude/docker-compose.yml` is already up for plm2). Open project 1994, set "Customer file naming" to VW group, select an article, drop one PCA CATPart from `/mnt/c/Users/christoph.demmler/OneDrive - KTX America Corporation/Desktop/1994E1/3D Nom Verified/3D Nom Verified/<any>/`, confirm: kind chip PCA, index 003, default "Attach to E1 · 003", upload lands with the note under the filename.

- [ ] **Step 3: Commit**

```bash
git add docs/CUSTOMER_DATA_INDEX.md
git commit -m "docs: guided upload flow and customer file naming"
```
