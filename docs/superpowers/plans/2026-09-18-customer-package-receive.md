# Customer Package Receive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receive a customer delivery (assembly file plus one file per part) in one step, creating a new major only for parts whose customer index changed, let the user choose the major number, and show the customer index next to every revision name.

**Architecture:** Pure matching/decision functions live in a new `customer_package.py` module and are unit-tested without a database. A `CustomerPackageService` composes them with the existing `RevisionService.receive_customer_data` and a new shared `store_revision_file` helper extracted from the upload endpoint. Two multipart endpoints (preview, confirm) sit next to the existing customer-data endpoint. The frontend gets one `RevisionBadge` component reused everywhere and one `CustomerPackageDialog` with a review table.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest-asyncio (backend, run from `backend/` with `uv run pytest`), React + TypeScript + vitest + testing-library (frontend, run from `frontend/` with `npx vitest run`).

**Spec:** `docs/superpowers/specs/2026-09-18-customer-package-receive-design.md`

## Global Constraints

- Revision names stay `E<n>[.<m>]` / `<n>[.<m>]`; counters never reset; review after official is refused (`RevisionRuleViolation` → HTTP 409).
- Sameness of a delivered file is decided by customer index equality only, never by hash.
- No change process is added for customer data.
- File storage keeps the existing layout `uploads/revisions/<revision_id>/<uuid><ext>` and the existing SHA-256 + glTF conversion.
- Commit after every task with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` as the last line of the message.
- Backend tests: `cd backend && uv run pytest tests/<file> -q`. Frontend tests: `cd frontend && npx vitest run src/<path>`.

---

### Task 1: Chosen major number (naming rule + service + API)

**Files:**
- Modify: `backend/app/services/revision_naming.py:56-66` (`next_major_name`)
- Modify: `backend/app/services/part_service.py:197-247` (`receive_customer_data`)
- Modify: `backend/app/services/part_service.py:283-300` (`promote_revision`)
- Modify: `backend/app/schemas/part.py:181-200` (`CustomerDataReceivedRequest`, `PromoteRevisionRequest`)
- Modify: `backend/app/api/v1/items/parts.py:167-230` (pass `major`)
- Test: `backend/tests/test_revision_naming.py`, `backend/tests/test_customer_data_service.py`, `backend/tests/test_customer_data_index.py`

**Interfaces:**
- Produces: `next_major_name(existing_major_names: list[str], statement: str, requested: int | None = None) -> str`
- Produces: `RevisionService.receive_customer_data(..., major: int | None = None)` and `promote_revision(..., major: int | None = None)`
- Produces: request field `major: Optional[int]` (>= 1) on both request schemas.

- [ ] **Step 1: Write the failing naming tests**

Append to `backend/tests/test_revision_naming.py`:

```python
def test_requested_major_above_existing_is_taken():
    assert next_major_name(["E1"], "review", requested=3) == "E3"
    assert next_major_name([], "review", requested=2) == "E2"
    assert next_major_name(["E1", "E2", "1"], "official", requested=4) == "4"


@pytest.mark.parametrize("existing,statement,requested", [
    (["E2"], "review", 2), (["E2"], "review", 1), (["1"], "official", 1), ([], "review", 0),
])
def test_requested_major_not_above_existing_is_a_rule_violation(existing, statement, requested):
    with pytest.raises(RevisionRuleViolation):
        next_major_name(existing, statement, requested=requested)
```

Check the imports at the top of the file already include `pytest`, `next_major_name` and `RevisionRuleViolation`; add any that are missing.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_revision_naming.py -q`
Expected: FAIL with `TypeError: next_major_name() got an unexpected keyword argument 'requested'`

- [ ] **Step 3: Implement the rule**

Replace `next_major_name` in `backend/app/services/revision_naming.py`:

```python
def next_major_name(existing_major_names: list[str], statement: str, requested: int | None = None) -> str:
    """Next major of the given kind. ``requested`` lets the user pick the
    number (the customer's numbering may be ahead of ours); it must be above
    every existing major of that kind. Gaps are fine."""
    if statement not in STATEMENTS:
        raise ValueError(f"statement must be one of {STATEMENTS}, got {statement!r}")
    want_official = statement == STATEMENT_OFFICIAL
    majors = _majors(existing_major_names)
    if not want_official and any(is_official for is_official, _ in majors):
        raise RevisionRuleViolation(
            "This part already has official customer data; the customer cannot "
            "un-release it, so new data must be official too.")
    highest = max((n for is_off, n in majors if is_off == want_official), default=0)
    if requested is None:
        return format_name(want_official, highest + 1)
    if requested < 1 or requested <= highest:
        raise RevisionRuleViolation(
            f"Revision number must be above {format_name(want_official, highest)}"
            if highest else "Revision number must be 1 or higher")
    return format_name(want_official, requested)
```

- [ ] **Step 4: Run naming tests**

Run: `cd backend && uv run pytest tests/test_revision_naming.py -q`
Expected: all PASS

- [ ] **Step 5: Write the failing service and API tests**

Append to `backend/tests/test_customer_data_service.py`:

```python
async def test_receive_with_chosen_major_number(session_factory, seed):
    pid = await _part(session_factory, seed, number="P-MAJ")
    async with session_factory() as s:
        e2 = await RevisionService.receive_customer_data(
            s, pid, "review", date(2026, 9, 1), major=2, created_by=seed["admin_id"])
        assert e2.revision_name == "E2"
        e3 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        assert e3.revision_name == "E3"
        with pytest.raises(RevisionRuleViolation):
            await RevisionService.receive_customer_data(
                s, pid, "review", date(2026, 9, 3), major=3, created_by=seed["admin_id"])
        await s.commit()
```

Append to `backend/tests/test_customer_data_index.py`:

```python
async def test_customer_data_with_chosen_major(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, number="P-CD-MAJ")
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-01", "major": 2})
    assert r.status_code == 201 and r.json()["revision_name"] == "E2"
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-02", "major": 2})
    assert r.status_code == 409
    assert "above E2" in r.json()["detail"]
```

- [ ] **Step 6: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_customer_data_service.py tests/test_customer_data_index.py -q`
Expected: FAIL (`unexpected keyword argument 'major'`; API test gets 201 with `E1`)

- [ ] **Step 7: Thread `major` through service, schema and endpoint**

In `backend/app/services/part_service.py`, `receive_customer_data`: add parameter `major: Optional[int] = None` after `copy_bom_from`, and change the name line to
`name = next_major_name([m.revision_name for m in majors], statement, requested=major)`.

In `promote_revision`: add `major: Optional[int] = None` after `customer_index`, and pass `major=major` into the `receive_customer_data` call.

In `backend/app/schemas/part.py`, add to both `CustomerDataReceivedRequest` and `PromoteRevisionRequest`:

```python
    major: Optional[int] = Field(None, ge=1, description="Chosen major number; must be above every existing major of this kind")
```

In `backend/app/api/v1/items/parts.py`, pass `major=body.major` in the `receive_customer_data` call of the `receive_customer_data` endpoint and in the `promote_revision` call of the `promote_revision` endpoint.

- [ ] **Step 8: Run the backend tests**

Run: `cd backend && uv run pytest tests/test_revision_naming.py tests/test_customer_data_service.py tests/test_customer_data_index.py tests/test_bom_tree.py -q`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/revision_naming.py backend/app/services/part_service.py backend/app/schemas/part.py backend/app/api/v1/items/parts.py backend/tests/test_revision_naming.py backend/tests/test_customer_data_service.py backend/tests/test_customer_data_index.py
git commit -m "feat(revisions): choose the major number when recording customer data

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Revision number field in the customer data dialog

**Files:**
- Modify: `frontend/src/components/parts/CustomerDataDialog.tsx`
- Create: `frontend/src/components/parts/CustomerDataDialog.test.tsx`

**Interfaces:**
- Produces: `CustomerDataInput.major?: number`; new prop `nextMajor?: { review: number; official: number }` used as the placeholder.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/parts/CustomerDataDialog.test.tsx`:

```tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import CustomerDataDialog from './CustomerDataDialog'

describe('CustomerDataDialog', () => {
  afterEach(cleanup)

  it('submits the chosen major number and omits it when blank', () => {
    const onSubmit = vi.fn()
    render(<CustomerDataDialog open title="t" onClose={() => {}} onSubmit={onSubmit} nextMajor={{ review: 1, official: 1 }} />)
    const major = screen.getByTestId('major-input') as HTMLInputElement
    expect(major.placeholder).toBe('1')
    fireEvent.click(screen.getByText('Save'))
    expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ statement: 'review' }))
    expect(onSubmit.mock.calls[0][0].major).toBeUndefined()

    fireEvent.change(major, { target: { value: '3' } })
    fireEvent.click(screen.getByText('Save'))
    expect(onSubmit.mock.calls[1][0].major).toBe(3)
  })

  it('placeholder follows the statement', () => {
    render(<CustomerDataDialog open title="t" onClose={() => {}} onSubmit={() => {}} nextMajor={{ review: 3, official: 1 }} />)
    expect((screen.getByTestId('major-input') as HTMLInputElement).placeholder).toBe('3')
    fireEvent.click(screen.getByLabelText(/official/i))
    expect((screen.getByTestId('major-input') as HTMLInputElement).placeholder).toBe('1')
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/parts/CustomerDataDialog.test.tsx`
Expected: FAIL, `Unable to find an element by: [data-testid="major-input"]`

- [ ] **Step 3: Add the field**

In `CustomerDataDialog.tsx`:

- extend the interface: `major?: number;` on `CustomerDataInput`; add prop `nextMajor?: { review: number; official: number };`
- add state `const [major, setMajor] = useState('');`
- add after the "Received on" label:

```tsx
        <label className="block text-sm text-slate-400">Revision number (optional)
          <input data-testid="major-input" type="number" min={1} value={major} onChange={(e) => setMajor(e.target.value)}
            placeholder={nextMajor ? String(nextMajor[effective]) : ''}
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
          <span className="text-xs text-slate-500">Leave empty for the next free number. Must be above every existing {effective === 'review' ? 'E' : 'official'} revision.</span>
        </label>
```

- in `onSubmit`, add `major: major.trim() ? parseInt(major, 10) : undefined`.
- the `official` radio label must be selectable with `getByLabelText(/official/i)`: give the `<label>` an `htmlFor` or keep the input inside the label (it already is; testing-library resolves nested inputs).

- [ ] **Step 4: Run the test**

Run: `cd frontend && npx vitest run src/components/parts/CustomerDataDialog.test.tsx`
Expected: PASS

- [ ] **Step 5: Pass `nextMajor` from both callers**

In `frontend/src/pages/PartDetail.tsx` and `frontend/src/pages/ProjectDetailPage.tsx`, where `CustomerDataDialog` is rendered, compute from the part's revisions (`revisions` on PartDetail, `partRevisions` on ProjectDetailPage):

```ts
const majorsOf = (revs: { revision_name: string }[]) => revs.filter((r) => !r.revision_name.includes('.'));
const nextMajor = {
  review: Math.max(0, ...majorsOf(revs).filter((r) => r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name.slice(1), 10))) + 1,
  official: Math.max(0, ...majorsOf(revs).filter((r) => !r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name, 10))) + 1,
};
```

and pass `nextMajor={nextMajor}` to every `CustomerDataDialog` on both pages. On PartDetail the promote dialog also sends `major`: extend its `client.post` body with `major: v.major`.

- [ ] **Step 6: Type-check and run the page tests**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json && npx vitest run src/components/parts src/pages/PartDetail`
Expected: no type errors, tests PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/parts/CustomerDataDialog.tsx frontend/src/components/parts/CustomerDataDialog.test.tsx frontend/src/pages/PartDetail.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(ui): revision number field on the customer data dialog

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Extract `store_revision_file` into a service

**Files:**
- Create: `backend/app/services/revision_file_service.py`
- Modify: `backend/app/api/v1/items/revision_files.py:30-90,156-248`
- Test: `backend/tests/test_revision_file_service.py` (new), `backend/tests/test_file_provenance.py` (existing, must keep passing)

**Interfaces:**
- Produces:

```python
EXTENSION_MAP, VALID_FILE_TYPES, MIME_MAP, MAX_FILE_SIZE, uploads_dir(revision_id) -> str
class UnsupportedFile(ValueError): ...
async def store_revision_file(session, revision: PartRevision, filename: str, contents: bytes,
                              uploaded_by: int, content_type: str | None = None,
                              file_type: str | None = None) -> RevisionFile
```
  It validates extension/type/size, writes the file, hashes it, converts STEP to glTF, adds the `RevisionFile`, flushes, and logs the changelog line. It does not commit and does not check the revision's locked status (the caller does).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_revision_file_service.py`:

```python
"""store_revision_file: one code path for every file that lands on a revision."""
import hashlib
import os
from datetime import date

import pytest

from app.models.part import RevisionFile
from app.services.part_service import PartService, RevisionService
from app.services.revision_file_service import UnsupportedFile, store_revision_file


async def _rev(session_factory, seed):
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number="P-RF",
                                          name="F", part_type="internal_mfg", created_by=seed["admin_id"])
        r = await RevisionService.receive_customer_data(s, p.id, "review", date(2026, 9, 1), created_by=seed["admin_id"])
        await s.commit()
        return r.id


async def test_store_writes_hashes_and_logs(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rid = await _rev(session_factory, seed)
    async with session_factory() as s:
        from app.models.part import PartRevision
        rev = await s.get(PartRevision, rid)
        f = await store_revision_file(s, rev, "3CR807425B.pdf", b"%PDF-1.4 hello", seed["admin_id"], file_type="drawing")
        await s.commit()
        assert f.file_type == "drawing" and f.mime_type == "application/pdf"
        assert f.file_hash == hashlib.sha256(b"%PDF-1.4 hello").hexdigest()
        assert os.path.isfile(f.file_path) and str(rid) in f.file_path
        assert (await s.get(RevisionFile, f.id)) is not None


async def test_store_rejects_unknown_extension(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rid = await _rev(session_factory, seed)
    async with session_factory() as s:
        from app.models.part import PartRevision
        rev = await s.get(PartRevision, rid)
        with pytest.raises(UnsupportedFile):
            await store_revision_file(s, rev, "x.exe", b"MZ", seed["admin_id"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_revision_file_service.py -q`
Expected: FAIL with `ModuleNotFoundError: app.services.revision_file_service`

- [ ] **Step 3: Create the service**

Create `backend/app/services/revision_file_service.py`. Move `MAX_FILE_SIZE`, `EXTENSION_MAP`, `VALID_FILE_TYPES`, `MIME_MAP` verbatim from `revision_files.py` into it, then add:

```python
"""One code path for a file landing on a revision: validate, write, hash,
convert STEP to glTF, record, log. Used by the single-file upload endpoint
and by the customer package receive."""
from __future__ import annotations

import hashlib
import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import PartRevision, RevisionFile
from app.services.part_service import ChangelogService
from app.utils.cad_converter import convert_step_to_gltf

logger = logging.getLogger(__name__)

# ... MAX_FILE_SIZE, EXTENSION_MAP, VALID_FILE_TYPES, MIME_MAP moved here ...


class UnsupportedFile(ValueError):
    """Extension, file type or size not accepted."""


def uploads_dir(revision_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "revisions", str(revision_id))


def classify(filename: str, file_type: str | None = None) -> tuple[str, str, str | None]:
    """(ext, resolved file_type, cad_format) or raise UnsupportedFile."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in EXTENSION_MAP:
        raise UnsupportedFile(f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(EXTENSION_MAP))}")
    inferred_type, cad_format = EXTENSION_MAP[ext]
    resolved = file_type or inferred_type
    if resolved not in VALID_FILE_TYPES:
        raise UnsupportedFile(f"Invalid file_type '{resolved}'. Valid: {', '.join(sorted(VALID_FILE_TYPES))}")
    return ext, resolved, cad_format


async def store_revision_file(session: AsyncSession, revision: PartRevision, filename: str, contents: bytes,
                              uploaded_by: int, content_type: str | None = None,
                              file_type: str | None = None) -> RevisionFile:
    ext, resolved_type, cad_format = classify(filename, file_type)
    if len(contents) > MAX_FILE_SIZE:
        raise UnsupportedFile("File size must be under 100MB")
    target_dir = uploads_dir(revision.id)
    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, f"{uuid.uuid4().hex}{ext}")
    with open(file_path, "wb") as fh:
        fh.write(contents)
    viewer_file_path = None
    if cad_format == "step":
        gltf_path = os.path.join(target_dir, f"{uuid.uuid4().hex}.glb")
        try:
            if await convert_step_to_gltf(file_path, gltf_path):
                viewer_file_path = gltf_path
            else:
                logger.warning(f"glTF conversion failed for {filename}")
        except Exception as e:  # conversion is best effort
            logger.error(f"glTF conversion error for {filename}: {e}", exc_info=True)
    rev_file = RevisionFile(
        revision_id=revision.id, filename=filename, file_type=resolved_type,
        mime_type=content_type or MIME_MAP.get(ext, "application/octet-stream"),
        file_size=len(contents), file_path=file_path, cad_format=cad_format,
        file_hash=hashlib.sha256(contents).hexdigest(),
        viewer_file_path=viewer_file_path, has_viewer=viewer_file_path is not None,
        uploaded_by=uploaded_by,
    )
    session.add(rev_file)
    await session.flush()
    await ChangelogService.log_action(
        session, part_id=revision.part_id, revision_id=revision.id, action="file_uploaded",
        action_description=f"Uploaded {resolved_type} file '{filename}' to {revision.revision_name}",
        performed_by=uploaded_by, file_id=rev_file.id)
    return rev_file
```

- [ ] **Step 4: Make the endpoint use it**

In `backend/app/api/v1/items/revision_files.py`:
- delete the moved constants and `_uploads_dir`; add `from app.services.revision_file_service import EXTENSION_MAP, VALID_FILE_TYPES, MIME_MAP, MAX_FILE_SIZE, UnsupportedFile, store_revision_file, uploads_dir as _uploads_dir` (other functions in the file still reference these names; keep the aliases so nothing else changes).
- in `upload_revision_file`, replace everything from `ext = os.path.splitext(...)` through `await db.flush()` and the changelog call with:

```python
        part = await PartService.get_part(db, part_id)
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
        revision = await _load_revision(db, part_id, revision_id, mismatch_status=status.HTTP_400_BAD_REQUEST)
        if _status_value(revision.status) in LOCKED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Revision {revision.revision_name} is {_status_value(revision.status)} and cannot accept new files",
            )
        contents = await file.read()
        try:
            rev_file = await store_revision_file(db, revision, file.filename or "", contents, current_user.id,
                                                 content_type=file.content_type, file_type=file_type)
        except UnsupportedFile as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        await db.commit()
```

Keep the `logger.info` and the `return {"status": "success", **_file_response_dict(rev_file)}`.

- [ ] **Step 5: Run the file tests**

Run: `cd backend && uv run pytest tests/test_revision_file_service.py tests/test_file_provenance.py -q && uv run pytest -q -x`
Expected: all PASS (the full run guards the moved constants)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/revision_file_service.py backend/app/api/v1/items/revision_files.py backend/tests/test_revision_file_service.py
git commit -m "refactor(files): store_revision_file service shared by upload paths

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Pure package matching and decision functions

**Files:**
- Create: `backend/app/services/customer_package.py`
- Test: `backend/tests/test_customer_package_rules.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Candidate:  # a part that a file may belong to
    part_id: int; part_number: str; customer_part_number: str | None; in_tree: bool

def squash(s: str | None) -> str            # lowercase, drop . space - _
def match_file(filename: str, candidates: list[Candidate]) -> Candidate | None
def index_from_filename(filename: str, customer_part_number: str | None) -> str | None
def decide_action(row_index: str | None, current_index: str | None) -> str   # "new_major" | "unchanged"
```

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_customer_package_rules.py`:

```python
"""Pure rules of the customer package receive: match a file to a part, read
the index from the filename, decide whether the part changed."""
import pytest

from app.services.customer_package import Candidate, decide_action, index_from_filename, match_file, squash

TREE = [
    Candidate(1, "1994-100", "3CR.807.425", True),
    Candidate(2, "1994-110", "3CR.807.531.A", True),
    Candidate(3, "1994-900", None, False),
]


def test_squash_drops_separators_and_case():
    assert squash("3CR.807.425.B") == "3cr807425b"
    assert squash(None) == ""


@pytest.mark.parametrize("filename,expected", [
    ("3CR807425B_Unterfahrschutz.stp", 1),
    ("3cr-807-425.pdf", 1),
    ("3CR.807.531.A.step", 2),
    ("1994-900 clamp.stp", 3),
    ("1994_900.pdf", 3),
    ("unrelated.stp", None),
])
def test_match_by_customer_number_then_our_number(filename, expected):
    m = match_file(filename, TREE)
    assert (m.part_id if m else None) == expected


def test_tree_candidates_win_over_project_candidates():
    cands = [Candidate(9, "X", "3CR.807.425", False), Candidate(1, "Y", "3CR.807.425", True)]
    assert match_file("3CR807425.stp", cands).part_id == 1


def test_longest_customer_number_wins():
    # 3CR.807.531 vs 3CR.807.531.A: the file names the longer one
    cands = [Candidate(1, "A", "3CR.807.531", True), Candidate(2, "B", "3CR.807.531.A", True)]
    assert match_file("3CR807531A.stp", cands).part_id == 2
    assert match_file("3CR807531.stp", cands).part_id == 1


@pytest.mark.parametrize("filename,number,expected", [
    ("3CR807425B_Unterfahrschutz.stp", "3CR.807.425", "B"),
    ("3CR.807.425.B.stp", "3CR.807.425", "B"),
    ("3CR-807-425-C.pdf", "3CR.807.425", "C"),
    ("3CR807425.stp", "3CR.807.425", None),
    ("3CR807425_Unterfahrschutz.stp", "3CR.807.425", None),
    ("3CR807425AB.stp", "3CR.807.425", None),
    ("anything.stp", None, None),
])
def test_index_from_filename(filename, number, expected):
    assert index_from_filename(filename, number) == expected


@pytest.mark.parametrize("row,current,expected", [
    ("B", "B", "unchanged"), ("b ", "B", "unchanged"),
    ("C", "B", "new_major"), ("B", None, "new_major"), (None, "B", "new_major"), (None, None, "new_major"),
])
def test_decide_action(row, current, expected):
    assert decide_action(row, current) == expected
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_customer_package_rules.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `backend/app/services/customer_package.py`:

```python
"""Rules of the customer package receive (pure, no database).

A delivery is the assembly file plus one file per part. A file belongs to
the part whose customer part number (or, failing that, our part number) is
in the filename. If the customer index of the file equals the index already
on the part's active revision, the data did not change and the E does not
change either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ACTION_NEW = "new_major"
ACTION_UNCHANGED = "unchanged"
ACTION_UNMATCHED = "unmatched"
ACTION_ERROR = "error"

_SEP = re.compile(r"[.\s_-]")


@dataclass(frozen=True)
class Candidate:
    part_id: int
    part_number: str
    customer_part_number: str | None
    in_tree: bool  # the assembly itself or a part on its BOM tree


def squash(s: str | None) -> str:
    return _SEP.sub("", (s or "").lower())


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def match_file(filename: str, candidates: list[Candidate]) -> Candidate | None:
    """Tree candidates before project candidates; customer number before our
    number; the longest matching number wins so 3CR.807.531.A beats 3CR.807.531."""
    hay = squash(_stem(filename))
    for in_tree in (True, False):
        for attr in ("customer_part_number", "part_number"):
            best: Candidate | None = None
            best_len = 0
            for c in candidates:
                if c.in_tree != in_tree:
                    continue
                needle = squash(getattr(c, attr))
                if needle and needle in hay and len(needle) > best_len:
                    best, best_len = c, len(needle)
            if best is not None:
                return best
    return None


def index_from_filename(filename: str, customer_part_number: str | None) -> str | None:
    """The single index token right after the customer part number in the
    filename: '3CR807425B_x' -> 'B', '3CR.807.425.B' -> 'B'. Two letters or
    nothing after the number means no index in the name."""
    needle = squash(customer_part_number)
    if not needle:
        return None
    stem = _stem(filename)
    # walk the stem keeping a map from squashed position to original char
    squashed_chars = [(i, ch.lower()) for i, ch in enumerate(stem) if not _SEP.match(ch)]
    squashed = "".join(ch for _, ch in squashed_chars)
    pos = squashed.find(needle)
    if pos < 0:
        return None
    after = squashed[pos + len(needle):]
    m = re.match(r"^([a-z])(?![a-z0-9])", after)
    if not m:
        return None
    return m.group(1).upper()


def decide_action(row_index: str | None, current_index: str | None) -> str:
    a = (row_index or "").strip().lower()
    b = (current_index or "").strip().lower()
    return ACTION_UNCHANGED if a and b and a == b else ACTION_NEW
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_customer_package_rules.py -q`
Expected: all PASS. If `3CR807425_Unterfahrschutz.stp` yields `U`, the lookahead is wrong: the token must be a single letter followed by end-of-string or a digit; separators are already stripped, so `_Unterfahrschutz` becomes `unterfahrschutz` and `u` is followed by `n`, a letter, which the `(?![a-z0-9])` rejects. Keep that behaviour.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/customer_package.py backend/tests/test_customer_package_rules.py
git commit -m "feat(package): pure matching and change-decision rules for customer packages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `CustomerPackageService.preview` and `.confirm`

**Files:**
- Create: `backend/app/services/customer_package_service.py`
- Test: `backend/tests/test_customer_package_service.py`

**Interfaces:**
- Consumes: `Candidate`, `match_file`, `index_from_filename`, `decide_action` (Task 4); `store_revision_file` (Task 3); `RevisionService.receive_customer_data(..., major=)` (Task 1); `BomTreeService.tree`.
- Produces:

```python
@dataclass
class PackageRow:
    filename: str
    part_id: int | None
    part_number: str | None
    customer_part_number: str | None
    customer_index: str | None
    current_revision: str | None
    current_index: str | None
    action: str            # new_major | unchanged | unmatched | error
    suggested_name: str | None
    major: int | None      # confirm only, user's chosen number
    error: str | None

class CustomerPackageService:
    @staticmethod
    async def candidates(session, assembly_id) -> list[Candidate]
    @staticmethod
    async def preview(session, assembly_id, statement, received_at, package_index, filenames) -> list[PackageRow]
    @staticmethod
    async def confirm(session, assembly_id, statement, received_at, rows: list[PackageRow],
                      files: dict[str, tuple[bytes, str | None]], created_by) -> dict
        # returns {"created": [{"part_id","part_number","revision_name","file_id"}], "kept": [...], "skipped": [filename,...]}
        # raises PackageError(rows_with_errors) before touching anything
```

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_customer_package_service.py`:

```python
"""Package receive: only changed parts get a new major, files land on it,
the assembly BOM is copied forward, nothing is stored on error."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.part import Part, PartRevision, RevisionFile
from app.services.bom_tree_service import BomTreeService
from app.services.customer_package_service import CustomerPackageService, PackageError, PackageRow
from app.services.part_service import PartService, RevisionService


async def _setup(session_factory, seed):
    """Assembly TOP (3CR.807.425, E1 index A) with children SUB (3CR.807.531, E1 index A)
    and CLAMP (no customer number, E1 index A). Returns ids."""
    async with session_factory() as s:
        admin = seed["admin_id"]
        top = await PartService.create_part(s, project_id=seed["project_id"], part_number="1994-100", name="Top",
                                            part_type="internal_mfg", created_by=admin, customer_part_number="3CR.807.425")
        sub = await PartService.create_part(s, project_id=seed["project_id"], part_number="1994-110", name="Sub",
                                            part_type="internal_mfg", created_by=admin, customer_part_number="3CR.807.531")
        clamp = await PartService.create_part(s, project_id=seed["project_id"], part_number="1994-120", name="Clamp",
                                              part_type="purchased", created_by=admin)
        ids = {}
        for p in (top, sub, clamp):
            r = await RevisionService.receive_customer_data(s, p.id, "review", date(2026, 9, 1), customer_index="A", created_by=admin)
            ids[p.part_number] = (p.id, r.id)
        from app.models.part import PartBOMItem
        s.add(PartBOMItem(revision_id=ids["1994-100"][1], child_part_id=sub.id, item_number="10", name="Sub", quantity=1, unit="pcs", position=1, created_by=admin))
        s.add(PartBOMItem(revision_id=ids["1994-100"][1], child_part_id=clamp.id, item_number="20", name="Clamp", quantity=4, unit="pcs", position=2, created_by=admin))
        await s.commit()
        return ids


async def test_preview_matches_and_decides(session_factory, seed):
    ids = await _setup(session_factory, seed)
    async with session_factory() as s:
        rows = await CustomerPackageService.preview(
            s, ids["1994-100"][0], "review", date(2026, 9, 10), "B",
            ["3CR807425B_top.stp", "3CR807531A_sub.stp", "1994-120 clamp.stp", "stranger.stp"])
    by = {r.filename: r for r in rows}
    assert by["3CR807425B_top.stp"].action == "new_major" and by["3CR807425B_top.stp"].customer_index == "B"
    assert by["3CR807425B_top.stp"].suggested_name == "E2" and by["3CR807425B_top.stp"].current_revision == "E1"
    assert by["3CR807531A_sub.stp"].action == "unchanged" and by["3CR807531A_sub.stp"].customer_index == "A"
    # no index in the clamp filename -> package index B -> differs from A -> new major
    assert by["1994-120 clamp.stp"].action == "new_major" and by["1994-120 clamp.stp"].customer_index == "B"
    assert by["stranger.stp"].action == "unmatched" and by["stranger.stp"].part_id is None


async def test_confirm_creates_only_changed_majors_and_copies_bom(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = await _setup(session_factory, seed)
    top_id, sub_id, clamp_id = ids["1994-100"][0], ids["1994-110"][0], ids["1994-120"][0]
    rows = [
        PackageRow(filename="top.stp", part_id=top_id, customer_index="B", action="new_major", major=None),
        PackageRow(filename="sub.stp", part_id=sub_id, customer_index="A", action="unchanged"),
        PackageRow(filename="clamp.stp", part_id=clamp_id, customer_index="A", action="unchanged"),
        PackageRow(filename="stranger.stp", part_id=None, action="unmatched"),
    ]
    files = {n: (b"ISO-10303-21;" + n.encode(), "model/step") for n in ("top.stp", "sub.stp", "clamp.stp", "stranger.stp")}
    async with session_factory() as s:
        out = await CustomerPackageService.confirm(s, top_id, "review", date(2026, 9, 10), rows, files, seed["admin_id"])
        await s.commit()
    assert [c["revision_name"] for c in out["created"]] == ["E2"]
    assert {k["part_id"] for k in out["kept"]} == {sub_id, clamp_id}
    assert out["skipped"] == ["stranger.stp"]
    async with session_factory() as s:
        top = await s.get(Part, top_id)
        e2 = await s.get(PartRevision, top.active_revision_id)
        assert e2.revision_name == "E2" and e2.customer_index == "B"
        files_on_e2 = (await s.execute(select(RevisionFile).where(RevisionFile.revision_id == e2.id))).scalars().all()
        assert [f.filename for f in files_on_e2] == ["top.stp"]
        sub = await s.get(Part, sub_id)
        assert sub.active_revision_id == ids["1994-110"][1]  # untouched
        tree = await BomTreeService.tree(s, top_id)
        assert tree["revision_name"] == "E2" and len(tree["lines"]) == 2
        assert (await s.execute(select(RevisionFile).where(RevisionFile.filename == "sub.stp"))).scalar_one_or_none() is None


async def test_confirm_with_chosen_major_and_error_row(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = await _setup(session_factory, seed)
    top_id = ids["1994-100"][0]
    async with session_factory() as s:
        out = await CustomerPackageService.confirm(
            s, top_id, "review", date(2026, 9, 10),
            [PackageRow(filename="top.stp", part_id=top_id, customer_index="C", action="new_major", major=4)],
            {"top.stp": (b"x", None)}, seed["admin_id"])
        await s.commit()
    assert out["created"][0]["revision_name"] == "E4"
    async with session_factory() as s:
        with pytest.raises(PackageError) as ei:
            await CustomerPackageService.confirm(
                s, top_id, "review", date(2026, 9, 11),
                [PackageRow(filename="top.stp", part_id=top_id, customer_index="D", action="new_major", major=3),
                 PackageRow(filename="bad.exe", part_id=top_id, customer_index="D", action="new_major")],
                {"top.stp": (b"x", None), "bad.exe": (b"MZ", None)}, seed["admin_id"])
        errors = {r.filename: r.error for r in ei.value.rows if r.action == "error"}
        assert "above E4" in errors["top.stp"] and "Unsupported" in errors["bad.exe"]
        await s.rollback()
    async with session_factory() as s:
        names = (await s.execute(select(PartRevision.revision_name).where(PartRevision.part_id == top_id))).scalars().all()
        assert sorted(names) == ["E1", "E4"]
```

Check `PartService.create_part` accepts `customer_part_number`; if it does not, set it on the returned part (`top.customer_part_number = "3CR.807.425"`) before the commit.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_customer_package_service.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/customer_package_service.py`:

```python
"""Receive a customer delivery for an assembly in one step. See
docs/superpowers/specs/2026-09-18-customer-package-receive-design.md."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part, PartRevision
from app.services.bom_tree_service import BomTreeService
from app.services.customer_package import (
    ACTION_ERROR, ACTION_NEW, ACTION_UNCHANGED, ACTION_UNMATCHED,
    Candidate, decide_action, index_from_filename, match_file)
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import UnsupportedFile, classify, store_revision_file
from app.services.revision_naming import RevisionRuleViolation, next_major_name


@dataclass
class PackageRow:
    filename: str
    part_id: Optional[int] = None
    part_number: Optional[str] = None
    customer_part_number: Optional[str] = None
    customer_index: Optional[str] = None
    current_revision: Optional[str] = None
    current_index: Optional[str] = None
    action: str = ACTION_UNMATCHED
    suggested_name: Optional[str] = None
    major: Optional[int] = None
    error: Optional[str] = None


class PackageError(ValueError):
    """At least one row is in error; nothing was stored."""

    def __init__(self, rows: list[PackageRow]):
        super().__init__("Package has rows in error")
        self.rows = rows


def _tree_part_ids(node: dict, acc: set[int]) -> set[int]:
    acc.add(node["part_id"])
    for line in node.get("lines", []):
        if line.get("child"):
            _tree_part_ids(line["child"], acc)
    return acc


class CustomerPackageService:

    @staticmethod
    async def candidates(session: AsyncSession, assembly_id: int) -> list[Candidate]:
        assembly = await session.get(Part, assembly_id)
        if assembly is None:
            raise ValueError("Assembly not found")
        tree_ids = _tree_part_ids(await BomTreeService.tree(session, assembly_id), set())
        parts = (await session.execute(
            select(Part).where(Part.project_id == assembly.project_id).order_by(Part.part_number))).scalars().all()
        return [Candidate(p.id, p.part_number, p.customer_part_number, p.id in tree_ids) for p in parts]

    @staticmethod
    async def _current(session: AsyncSession, part_id: int) -> Optional[PartRevision]:
        part = await session.get(Part, part_id)
        return await BomTreeService._display_revision(session, part) if part else None

    @staticmethod
    async def _fill_row(session: AsyncSession, row: PackageRow, statement: str) -> PackageRow:
        """Current revision, suggested name and rule errors for a row with a part."""
        part = await session.get(Part, row.part_id)
        if part is None:
            row.action, row.error = ACTION_ERROR, "Part not found"
            return row
        row.part_number, row.customer_part_number = part.part_number, part.customer_part_number
        current = await CustomerPackageService._current(session, row.part_id)
        row.current_revision = current.revision_name if current else None
        row.current_index = current.customer_index if current else None
        try:
            classify(row.filename)
            majors = await RevisionService._majors(session, row.part_id)
            row.suggested_name = next_major_name([m.revision_name for m in majors], statement, requested=row.major)
        except (UnsupportedFile, RevisionRuleViolation) as e:
            row.action, row.error = ACTION_ERROR, str(e)
        return row

    @staticmethod
    async def preview(session: AsyncSession, assembly_id: int, statement: str, received_at: date,
                      package_index: Optional[str], filenames: list[str]) -> list[PackageRow]:
        cands = await CustomerPackageService.candidates(session, assembly_id)
        rows: list[PackageRow] = []
        for name in filenames:
            row = PackageRow(filename=name)
            c = match_file(name, cands)
            if c is None:
                try:
                    classify(name)
                except UnsupportedFile as e:
                    row.action, row.error = ACTION_ERROR, str(e)
                rows.append(row)
                continue
            row.part_id = c.part_id
            row.customer_index = index_from_filename(name, c.customer_part_number) or (package_index or None)
            await CustomerPackageService._fill_row(session, row, statement)
            if row.action != ACTION_ERROR:
                row.action = decide_action(row.customer_index, row.current_index)
            rows.append(row)
        return rows

    @staticmethod
    async def confirm(session: AsyncSession, assembly_id: int, statement: str, received_at: date,
                      rows: list[PackageRow], files: dict[str, tuple[bytes, Optional[str]]],
                      created_by: int) -> dict:
        assembly = await session.get(Part, assembly_id)
        if assembly is None:
            raise ValueError("Assembly not found")
        # validate every row first; nothing is written while any row errs
        for row in rows:
            if row.action == ACTION_NEW:
                if row.part_id is None:
                    row.action, row.error = ACTION_ERROR, "No part chosen"
                elif row.filename not in files:
                    row.action, row.error = ACTION_ERROR, "File missing from upload"
                else:
                    await CustomerPackageService._fill_row(session, row, statement)
        if any(r.action == ACTION_ERROR for r in rows):
            raise PackageError(rows)

        created, kept, skipped = [], [], []
        written: list[str] = []
        try:
            # children first, the assembly last, so its new BOM copy sees the children active
            ordered = sorted((r for r in rows if r.action == ACTION_NEW), key=lambda r: r.part_id == assembly_id)
            for row in ordered:
                rev = await RevisionService.receive_customer_data(
                    session, row.part_id, statement, received_at, customer_index=row.customer_index,
                    summary=f"Customer package {received_at.isoformat()}", created_by=created_by, major=row.major)
                contents, ctype = files[row.filename]
                f = await store_revision_file(session, rev, row.filename, contents, created_by, content_type=ctype)
                written.append(f.file_path)
                if f.viewer_file_path:
                    written.append(f.viewer_file_path)
                created.append({"part_id": row.part_id, "part_number": row.part_number,
                                "revision_name": rev.revision_name, "file_id": f.id, "filename": row.filename})
            for row in rows:
                if row.action == ACTION_UNCHANGED and row.part_id is not None:
                    current = await CustomerPackageService._current(session, row.part_id)
                    part = await session.get(Part, row.part_id)
                    await ChangelogService.log_action(
                        session, part_id=row.part_id, revision_id=current.id if current else None,
                        action="package_unchanged",
                        action_description=(f"Customer package {received_at.isoformat()}: {row.filename} unchanged, "
                                            f"kept {current.revision_name if current else 'no revision'}"),
                        performed_by=created_by)
                    kept.append({"part_id": row.part_id, "part_number": part.part_number if part else None,
                                 "revision_name": current.revision_name if current else None, "filename": row.filename})
                elif row.action == ACTION_UNMATCHED:
                    skipped.append(row.filename)
        except Exception:
            for path in written:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        return {"created": created, "kept": kept, "skipped": skipped}
```

`ChangelogService.log_action` must accept `revision_id=None`; check its signature in `part_service.py` and, if `revision_id` is required, pass the part's display revision id or skip the log line when there is none.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_customer_package_service.py tests/test_customer_package_rules.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/customer_package_service.py backend/tests/test_customer_package_service.py
git commit -m "feat(package): preview and confirm a customer package on an assembly

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Package endpoints

**Files:**
- Create: `backend/app/api/v1/items/customer_package.py`
- Modify: the router registration file that includes `revision_files.router` (find with `grep -rn "revision_files" backend/app/api/v1/`), add the new router the same way
- Modify: `backend/app/schemas/part.py` (append response schemas)
- Test: `backend/tests/test_customer_package_api.py`

**Interfaces:**
- Produces:
  - `POST /api/v1/parts/{assembly_id}/revisions/customer-package/preview` multipart: `statement`, `received_at` (ISO date), `package_index` (optional), `files[]`. Returns `{"rows": [PackageRowOut]}`.
  - `POST /api/v1/parts/{assembly_id}/revisions/customer-package` multipart: `statement`, `received_at`, `rows` (JSON string, list of `{filename, part_id, customer_index, action, major}`), `files[]`. Returns `{"created": [...], "kept": [...], "skipped": [...]}`; `409` with `{"detail": "...", "rows": [...]}` when any row errs.

- [ ] **Step 1: Write the failing API test**

Create `backend/tests/test_customer_package_api.py`:

```python
"""HTTP flow of the customer package receive."""
import json


async def _mk_part(client, auth, seed, number, customer_number=None, part_type="internal_mfg"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": part_type, "data_classification": "confidential"}
    if customer_number:
        body["customer_part_number"] = customer_number
    res = await client.post("/api/v1/parts", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=auth,
                          json={"statement": "review", "received_at": "2026-09-01", "customer_index": "A"})
    assert r.status_code == 201, r.text
    return pid, r.json()["id"]


async def test_preview_then_confirm(client, eng_auth, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    top, top_rev = await _mk_part(client, eng_auth, seed, "1994-100", "3CR.807.425")
    sub, _ = await _mk_part(client, eng_auth, seed, "1994-110", "3CR.807.531")
    r = await client.post(f"/api/v1/parts/{top}/revisions/{top_rev}/bom-items", headers=eng_auth,
                          json={"child_part_id": sub, "quantity": 1, "unit": "pcs"})
    assert r.status_code in (200, 201), r.text

    files = [("files", ("3CR807425B_top.stp", b"ISO-10303-21;", "model/step")),
             ("files", ("3CR807531A_sub.stp", b"ISO-10303-21;", "model/step"))]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package/preview", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-09-10", "package_index": "B"}, files=files)
    assert r.status_code == 200, r.text
    rows = {x["filename"]: x for x in r.json()["rows"]}
    assert rows["3CR807425B_top.stp"]["action"] == "new_major" and rows["3CR807425B_top.stp"]["suggested_name"] == "E2"
    assert rows["3CR807531A_sub.stp"]["action"] == "unchanged"

    confirm_rows = [{"filename": "3CR807425B_top.stp", "part_id": top, "customer_index": "B", "action": "new_major", "major": None},
                    {"filename": "3CR807531A_sub.stp", "part_id": sub, "customer_index": "A", "action": "unchanged", "major": None}]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-09-10", "rows": json.dumps(confirm_rows)}, files=files)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [c["revision_name"] for c in out["created"]] == ["E2"] and len(out["kept"]) == 1

    part = (await client.get(f"/api/v1/parts/{top}", headers=eng_auth)).json()
    assert [x["revision_name"] for x in part["revisions"]] == ["E1", "E2"]


async def test_confirm_reports_row_errors(client, eng_auth, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    top, _ = await _mk_part(client, eng_auth, seed, "1994-200", "3CR.807.999")
    rows = [{"filename": "top.stp", "part_id": top, "customer_index": "B", "action": "new_major", "major": 1}]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-09-10", "rows": json.dumps(rows)},
                          files=[("files", ("top.stp", b"x", "model/step"))])
    assert r.status_code == 409, r.text
    assert r.json()["rows"][0]["action"] == "error" and "above E1" in r.json()["rows"][0]["error"]
```

Check the BOM line endpoint path used in the first test with `grep -n "bom-items\|bom_items" backend/app/api/v1/items/*.py` and adjust the URL and body to the real one.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_customer_package_api.py -q`
Expected: FAIL with 404 on the preview URL

- [ ] **Step 3: Add response schemas**

Append to `backend/app/schemas/part.py`:

```python
class PackageRowOut(BaseModel):
    filename: str
    part_id: Optional[int] = None
    part_number: Optional[str] = None
    customer_part_number: Optional[str] = None
    customer_index: Optional[str] = None
    current_revision: Optional[str] = None
    current_index: Optional[str] = None
    action: Literal["new_major", "unchanged", "unmatched", "error"]
    suggested_name: Optional[str] = None
    major: Optional[int] = None
    error: Optional[str] = None


class PackageRowIn(BaseModel):
    filename: str
    part_id: Optional[int] = None
    customer_index: Optional[str] = Field(None, max_length=20)
    action: Literal["new_major", "unchanged", "unmatched"]
    major: Optional[int] = Field(None, ge=1)


class PackagePreviewResponse(BaseModel):
    rows: List[PackageRowOut]
```

- [ ] **Step 4: Write the endpoints**

Create `backend/app/api/v1/items/customer_package.py`:

```python
"""Customer package receive: the assembly file plus one file per part, in
one step. Preview matches and decides; confirm stores."""
import json
import logging
from dataclasses import asdict
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.schemas.part import PackagePreviewResponse, PackageRowIn, PackageRowOut
from app.services.customer_package_service import CustomerPackageService, PackageError, PackageRow
from app.services.revision_naming import STATEMENTS, RevisionRuleViolation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/parts", tags=["customer-package"])


def _statement(value: str) -> str:
    if value not in STATEMENTS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"statement must be one of {STATEMENTS}")
    return value


@router.post("/{assembly_id}/revisions/customer-package/preview", response_model=PackagePreviewResponse)
async def preview_customer_package(
    assembly_id: int,
    statement: str = Form(...),
    received_at: date = Form(...),
    package_index: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await CustomerPackageService.preview(
            db, assembly_id, _statement(statement), received_at, (package_index or "").strip() or None,
            [f.filename or "" for f in files])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"rows": [PackageRowOut(**asdict(r)) for r in rows]}


@router.post("/{assembly_id}/revisions/customer-package", status_code=status.HTTP_201_CREATED)
async def confirm_customer_package(
    assembly_id: int,
    statement: str = Form(...),
    received_at: date = Form(...),
    rows: str = Form(...),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        parsed = TypeAdapter(List[PackageRowIn]).validate_python(json.loads(rows))
    except (ValueError, ValidationError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"rows: {e}")
    blobs = {}
    for f in files:
        blobs[f.filename or ""] = (await f.read(), f.content_type)
    package_rows = [PackageRow(filename=r.filename, part_id=r.part_id, customer_index=r.customer_index,
                               action=r.action, major=r.major) for r in parsed]
    try:
        out = await CustomerPackageService.confirm(
            db, assembly_id, _statement(statement), received_at, package_rows, blobs, current_user.id)
        await db.commit()
        return out
    except PackageError as e:
        await db.rollback()
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={
            "detail": "Some rows cannot be stored", "rows": [asdict(r) for r in e.rows]})
    except RevisionRuleViolation as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
```

Register the router where `revision_files.router` is registered, with the same prefix and dependencies. `asdict` on `PackageRow` yields plain values; `date` fields are not present, so `JSONResponse` serialises without a custom encoder.

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/test_customer_package_api.py tests/test_customer_package_service.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/items/customer_package.py backend/app/schemas/part.py backend/tests/test_customer_package_api.py
git add -u backend/app/api/v1/
git commit -m "feat(api): customer package preview and confirm endpoints

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Customer index in BOM tree, assemblies and where-used responses

**Files:**
- Modify: `backend/app/services/bom_tree_service.py:70-80,120-130,155-165`
- Test: `backend/tests/test_bom_tree.py`

**Interfaces:**
- Produces: every node/entry dict that has `revision_name` also has `customer_index: str | None`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_bom_tree.py`:

```python
async def test_tree_assemblies_and_where_used_carry_customer_index(client, eng_auth, seed):
    top, top_rev = await _mk_part(client, eng_auth, seed, "IDX-TOP", with_e1=False)
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-01", "customer_index": "B"})
    top_rev = r.json()["id"]
    sub, _ = await _mk_part(client, eng_auth, seed, "IDX-SUB")
    await _add(client, eng_auth, top, top_rev, child_id=sub)
    tree = (await client.get(f"/api/v1/parts/{top}/bom-tree", headers=eng_auth)).json()
    assert tree["customer_index"] == "B"
    assert tree["lines"][0]["child"]["customer_index"] is None
    roots = {a["part_number"]: a for a in (await client.get(f"/api/v1/parts/project/{seed['project_id']}/assemblies", headers=eng_auth)).json()}
    assert roots["IDX-TOP"]["customer_index"] == "B"
    used = (await client.get(f"/api/v1/parts/{sub}/where-used", headers=eng_auth)).json()
    assert used[0]["customer_index"] == "B"
```

Adjust `_add`'s signature to what the file already defines (it takes `client, auth, pid, rid, child_id=...`).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_bom_tree.py -q -k customer_index`
Expected: FAIL with `KeyError: 'customer_index'`

- [ ] **Step 3: Add the field in the three dicts**

In `bom_tree_service.py`:
- `_node`: after `"revision_phase": rev.phase if rev else None,` add `"customer_index": rev.customer_index if rev else None,`
- `_parents`: after `"revision_name": rev.revision_name,` add `"customer_index": rev.customer_index,`
- `project_assemblies`: after `"revision_phase": rev.phase if rev else None,` add `"customer_index": rev.customer_index if rev else None,`

If the endpoints use pydantic response models for these (check `grep -n "response_model" backend/app/api/v1/items/parts.py` around `bom-tree`, `where-used`, `assemblies`), add `customer_index: Optional[str] = None` to those models.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_bom_tree.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/bom_tree_service.py backend/tests/test_bom_tree.py
git add -u backend/app/schemas backend/app/api
git commit -m "feat(bom): customer index on tree, assemblies and where-used

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `RevisionBadge` component used everywhere

**Files:**
- Create: `frontend/src/components/parts/RevisionBadge.tsx`, `frontend/src/components/parts/RevisionBadge.test.tsx`
- Modify: `frontend/src/components/parts/BomTree.tsx:7-20,55-64`, `frontend/src/components/parts/AssemblyTreeList.tsx:11-35`, `frontend/src/components/parts/RevisionTimeline.tsx:43-48,69`, `frontend/src/pages/PartDetail.tsx:151,204,212`, `frontend/src/pages/ProjectDetailPage.tsx:272,1301,1448`
- Test: `frontend/src/components/parts/BomTree.test.tsx`, `AssemblyTreeList.test.tsx`, `RevisionTimeline.test.tsx`

**Interfaces:**
- Produces:

```tsx
export function revisionLabel(name: string | null | undefined, index?: string | null): string  // "E2 · B" | "E2" | ""
export default function RevisionBadge({ name, index, phase, testId }: {
  name: string | null | undefined; index?: string | null; phase?: 'review' | 'official' | null; testId?: string })
```

- [ ] **Step 1: Write the failing badge test**

Create `frontend/src/components/parts/RevisionBadge.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import RevisionBadge, { revisionLabel } from './RevisionBadge'

describe('revisionLabel', () => {
  it('joins name and index with a middle dot', () => {
    expect(revisionLabel('E2', 'B')).toBe('E2 · B')
    expect(revisionLabel('E2', null)).toBe('E2')
    expect(revisionLabel('E2', '  ')).toBe('E2')
    expect(revisionLabel(null, 'B')).toBe('')
  })
})

describe('RevisionBadge', () => {
  afterEach(cleanup)
  it('renders the label, colours by phase, and says no data when there is none', () => {
    render(<RevisionBadge name="1" index="C" phase="official" testId="b1" />)
    const b = screen.getByTestId('b1')
    expect(b.textContent).toBe('1 · C')
    expect(b.className).toContain('amber')
    cleanup()
    render(<RevisionBadge name={null} testId="b2" />)
    expect(screen.getByTestId('b2').textContent).toBe('no data')
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/parts/RevisionBadge.test.tsx`
Expected: FAIL, cannot resolve `./RevisionBadge`

- [ ] **Step 3: Create the component**

Create `frontend/src/components/parts/RevisionBadge.tsx`:

```tsx
/** One way to print a revision: name plus the customer's own index, "E2 · B". */
export function revisionLabel(name: string | null | undefined, index?: string | null): string {
  if (!name) return '';
  const idx = (index ?? '').trim();
  return idx ? `${name} · ${idx}` : name;
}

export default function RevisionBadge({ name, index, phase, testId }: {
  name: string | null | undefined; index?: string | null; phase?: 'review' | 'official' | null; testId?: string;
}) {
  if (!name) return <span data-testid={testId} className="text-xs text-slate-500">no data</span>;
  return (
    <span data-testid={testId} title={phase ?? undefined}
      className={`text-xs px-1.5 rounded font-mono ${phase === 'official' ? 'bg-amber-900/40 text-amber-300' : 'bg-blue-900/40 text-blue-300'}`}>
      {revisionLabel(name, index)}
    </span>
  );
}
```

- [ ] **Step 4: Run the badge test**

Run: `cd frontend && npx vitest run src/components/parts/RevisionBadge.test.tsx`
Expected: PASS

- [ ] **Step 5: Extend the existing component tests, then swap the call sites**

`BomTree.test.tsx`: in the `node` factory add `customer_index: null`; on the SUB child pass `customer_index: 'C'` and change the assertion to `expect(screen.getByTestId('bom-rev-10').textContent).toBe('1 · C')`.
`AssemblyTreeList.test.tsx`: give one root `customer_index: 'B'` in its mocked response and assert the rendered row `textContent` contains `E1 · B`.
`RevisionTimeline.test.tsx`: the existing assertion `toContain('index B')` becomes `toContain('1 · B')`.

Run: `cd frontend && npx vitest run src/components/parts` → expected FAIL on those three.

Then:
- `BomTree.tsx`: add `customer_index?: string | null;` to `BomNode`; replace the inline `<span data-testid={`bom-rev-${line.id}`} ...>{child.revision_name}</span>` and the `no data` span with `<RevisionBadge testId={`bom-rev-${line.id}`} name={child?.revision_name} index={child?.customer_index} phase={child?.revision_phase} />` (guard `child` exists as before). Also the heading `No BOM lines on {tree.revision_name}` uses `revisionLabel(tree.revision_name, tree.customer_index)`.
- `AssemblyTreeList.tsx`: add `customer_index?: string | null` to `AssemblyRoot` and to its `BomNode` import if separate; delete the local `RevBadge` and use `<RevisionBadge name={...} index={node.customer_index} phase={...} />` in both places.
- `RevisionTimeline.tsx`: line 43 shows `revisionLabel(major.revision_name, major.customer_index)`; drop the separate `<Badge>index …</Badge>` on line 48. Minors (line 69) keep `m.revision_name`.
- `PartDetail.tsx`: line 151 `active ? `${revisionLabel(active.revision_name, active.customer_index)} (active)` : …`; line 204 `u.revision_name` → `revisionLabel(u.revision_name, u.customer_index)` (add `customer_index?: string | null` to the `WhereUsed` type); line 212 BOM heading → `revisionLabel(bomTree.revision_name, bomTree.customer_index)`.
- `ProjectDetailPage.tsx`: line 272 (used-in chip) and line 1301 (revision dropdown option) and line 1448 (revision card) → `revisionLabel(rev.revision_name, rev.customer_index)`; add `customer_index?: string | null` to the used-in type near line 236.

- [ ] **Step 6: Type-check and run all frontend tests**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json && npx vitest run`
Expected: no type errors, all PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/parts frontend/src/pages/PartDetail.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(ui): customer index next to every revision name

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: `CustomerPackageDialog`

**Files:**
- Create: `frontend/src/components/parts/CustomerPackageDialog.tsx`, `frontend/src/components/parts/CustomerPackageDialog.test.tsx`
- Modify: `frontend/src/pages/PartDetail.tsx` (button next to "+ Customer data"), `frontend/src/pages/ProjectDetailPage.tsx` (same button where "+ Customer data" is rendered for the selected part)

**Interfaces:**
- Consumes: `POST …/customer-package/preview` and `POST …/customer-package` (Task 6), `revisionLabel` (Task 8).
- Produces:

```tsx
export interface PackageRow { filename: string; part_id: number | null; part_number: string | null; customer_part_number: string | null;
  customer_index: string | null; current_revision: string | null; current_index: string | null;
  action: 'new_major' | 'unchanged' | 'unmatched' | 'error'; suggested_name: string | null; major: number | null; error: string | null }
export default function CustomerPackageDialog({ open, assemblyId, projectParts, officialOnly, onClose, onDone }: {
  open: boolean; assemblyId: number; projectParts: { id: number; part_number: string; name: string }[];
  officialOnly?: boolean; onClose(): void; onDone(result: { created: unknown[]; kept: unknown[]; skipped: string[] }): void })
```

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/parts/CustomerPackageDialog.test.tsx`:

```tsx
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import CustomerPackageDialog from './CustomerPackageDialog'

const post = vi.fn()
vi.mock('../../api/client', () => ({ default: { post: (...a: unknown[]) => post(...a) } }))

const previewRows = [
  { filename: 'top.stp', part_id: 1, part_number: '1994-100', customer_part_number: '3CR.807.425', customer_index: 'B',
    current_revision: 'E1', current_index: 'A', action: 'new_major', suggested_name: 'E2', major: null, error: null },
  { filename: 'clamp.stp', part_id: 2, part_number: '1994-120', customer_part_number: null, customer_index: 'A',
    current_revision: 'E1', current_index: 'A', action: 'unchanged', suggested_name: null, major: null, error: null },
  { filename: 'x.stp', part_id: null, part_number: null, customer_part_number: null, customer_index: 'B',
    current_revision: null, current_index: null, action: 'unmatched', suggested_name: null, major: null, error: null },
]

describe('CustomerPackageDialog', () => {
  beforeEach(() => post.mockReset())
  afterEach(cleanup)

  it('previews, lets a row change, and confirms with the edited rows', async () => {
    post.mockResolvedValueOnce({ data: { rows: previewRows } })
    post.mockResolvedValueOnce({ data: { created: [{ revision_name: 'E2' }], kept: [{}], skipped: [] } })
    const onDone = vi.fn()
    render(<CustomerPackageDialog open assemblyId={1} projectParts={[{ id: 1, part_number: '1994-100', name: 'Top' }, { id: 3, part_number: '1994-130', name: 'Bracket' }]}
      onClose={() => {}} onDone={onDone} />)
    const input = screen.getByTestId('package-files') as HTMLInputElement
    const file = new File(['x'], 'top.stp')
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByText('Check package'))
    await waitFor(() => expect(screen.getByTestId('row-top.stp')).toBeTruthy())
    expect(screen.getByTestId('row-top.stp').textContent).toContain('E1 · A')
    expect(screen.getByTestId('row-top.stp').textContent).toContain('E2')
    expect(screen.getByTestId('row-clamp.stp').textContent).toContain('unchanged')

    fireEvent.change(screen.getByTestId('part-x.stp'), { target: { value: '3' } })
    fireEvent.change(screen.getByTestId('action-x.stp'), { target: { value: 'new_major' } })
    fireEvent.click(screen.getByText('Store package'))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const form = post.mock.calls[1][1] as FormData
    const rows = JSON.parse(form.get('rows') as string)
    expect(rows.find((r: { filename: string }) => r.filename === 'x.stp')).toMatchObject({ part_id: 3, action: 'new_major' })
  })

  it('shows row errors from a 409 and keeps the table', async () => {
    post.mockResolvedValueOnce({ data: { rows: previewRows } })
    post.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'x', rows: [{ ...previewRows[0], action: 'error', error: 'Revision number must be above E1' }] } } })
    render(<CustomerPackageDialog open assemblyId={1} projectParts={[]} onClose={() => {}} onDone={() => {}} />)
    fireEvent.change(screen.getByTestId('package-files'), { target: { files: [new File(['x'], 'top.stp')] } })
    fireEvent.click(screen.getByText('Check package'))
    await waitFor(() => screen.getByTestId('row-top.stp'))
    fireEvent.click(screen.getByText('Store package'))
    await waitFor(() => expect(screen.getByTestId('row-top.stp').textContent).toContain('above E1'))
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/parts/CustomerPackageDialog.test.tsx`
Expected: FAIL, cannot resolve `./CustomerPackageDialog`

- [ ] **Step 3: Build the dialog**

Create `frontend/src/components/parts/CustomerPackageDialog.tsx`. Two steps in one modal (same shell classes as `CustomerDataDialog`):

```tsx
import { useState } from 'react';
import client from '../../api/client';
import { revisionLabel } from './RevisionBadge';

export interface PackageRow {
  filename: string; part_id: number | null; part_number: string | null; customer_part_number: string | null;
  customer_index: string | null; current_revision: string | null; current_index: string | null;
  action: 'new_major' | 'unchanged' | 'unmatched' | 'error'; suggested_name: string | null; major: number | null; error: string | null;
}

interface Props {
  open: boolean; assemblyId: number;
  projectParts: { id: number; part_number: string; name: string }[];
  officialOnly?: boolean; onClose(): void;
  onDone(result: { created: unknown[]; kept: unknown[]; skipped: string[] }): void;
}

const ACTIONS: PackageRow['action'][] = ['new_major', 'unchanged', 'unmatched'];

export default function CustomerPackageDialog({ open, assemblyId, projectParts, officialOnly, onClose, onDone }: Props) {
  const [statement, setStatement] = useState<'review' | 'official'>(officialOnly ? 'official' : 'review');
  const [receivedAt, setReceivedAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [packageIndex, setPackageIndex] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState<PackageRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!open) return null;
  const effective = officialOnly ? 'official' : statement;

  const base = () => {
    const fd = new FormData();
    fd.append('statement', effective);
    fd.append('received_at', receivedAt);
    files.forEach((f) => fd.append('files', f, f.name));
    return fd;
  };

  const preview = async () => {
    setBusy(true); setError(null);
    try {
      const fd = base();
      if (packageIndex.trim()) fd.append('package_index', packageIndex.trim());
      const res = await client.post(`/v1/parts/${assemblyId}/revisions/customer-package/preview`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setRows(res.data.rows);
    } catch (e) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Preview failed');
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    if (!rows) return;
    setBusy(true); setError(null);
    try {
      const fd = base();
      fd.append('rows', JSON.stringify(rows.filter((r) => r.action !== 'error').map((r) => ({
        filename: r.filename, part_id: r.part_id, customer_index: r.customer_index, action: r.action, major: r.major }))));
      const res = await client.post(`/v1/parts/${assemblyId}/revisions/customer-package`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      onDone(res.data);
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string; rows?: PackageRow[] } } };
      if (err.response?.status === 409 && err.response.data?.rows) setRows(err.response.data.rows);
      setError(err.response?.data?.detail || 'Storing failed');
    } finally { setBusy(false); }
  };

  const patch = (filename: string, p: Partial<PackageRow>) =>
    setRows((rs) => rs ? rs.map((r) => r.filename === filename ? { ...r, ...p, ...(p.action && p.action !== 'error' ? { error: null } : {}) } : r) : rs);

  const canStore = !!rows && rows.some((r) => r.action === 'new_major') && !rows.some((r) => r.action === 'new_major' && r.part_id == null);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-4xl w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-auto">
        <h3 className="text-lg font-bold text-slate-100">Customer package received</h3>
        {/* step 1: statement, date, package index, files — same inputs as CustomerDataDialog, plus: */}
        <input data-testid="package-files" type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          className="block text-sm text-slate-300" />
        {/* statement radios (reuse markup from CustomerDataDialog), received date input, package index input */}
        {!rows && (
          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 text-slate-100">Cancel</button>
            <button disabled={busy || files.length === 0 || !receivedAt} onClick={preview}
              className="px-4 py-2 rounded bg-blue-600 text-white disabled:bg-slate-600">{busy ? 'Checking…' : 'Check package'}</button>
          </div>
        )}
        {rows && (
          <table className="w-full text-sm">
            <thead className="text-slate-400 text-left"><tr>
              <th>File</th><th>Part</th><th>Current</th><th>Index</th><th>Action</th><th>Rev. no.</th><th>Result</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.filename} data-testid={`row-${r.filename}`} className={r.action === 'error' ? 'bg-red-900/20' : ''}>
                  <td className="font-mono text-slate-100 truncate max-w-[16rem]" title={r.filename}>{r.filename}</td>
                  <td>
                    <select data-testid={`part-${r.filename}`} value={r.part_id ?? ''} className="bg-slate-900 border border-slate-700 rounded px-1 text-slate-100"
                      onChange={(e) => { const id = e.target.value ? parseInt(e.target.value, 10) : null;
                        const p = projectParts.find((x) => x.id === id);
                        patch(r.filename, { part_id: id, part_number: p?.part_number ?? null, action: id == null ? 'unmatched' : (r.action === 'unmatched' ? 'new_major' : r.action) }); }}>
                      <option value="">— not in project —</option>
                      {(r.part_id != null && !projectParts.some((p) => p.id === r.part_id)) && <option value={r.part_id}>{r.part_number}</option>}
                      {projectParts.map((p) => <option key={p.id} value={p.id}>{p.part_number} {p.name}</option>)}
                    </select>
                  </td>
                  <td className="font-mono text-slate-300">{revisionLabel(r.current_revision, r.current_index) || '—'}</td>
                  <td><input value={r.customer_index ?? ''} onChange={(e) => patch(r.filename, { customer_index: e.target.value || null })}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1 text-slate-100" /></td>
                  <td>
                    <select data-testid={`action-${r.filename}`} value={r.action === 'error' ? 'new_major' : r.action}
                      onChange={(e) => patch(r.filename, { action: e.target.value as PackageRow['action'] })}
                      className="bg-slate-900 border border-slate-700 rounded px-1 text-slate-100">
                      {ACTIONS.map((a) => <option key={a} value={a}>{a === 'new_major' ? 'new major' : a}</option>)}
                    </select>
                  </td>
                  <td><input type="number" min={1} value={r.major ?? ''} placeholder={r.suggested_name?.replace(/^E/, '') ?? ''}
                    disabled={r.action !== 'new_major'} onChange={(e) => patch(r.filename, { major: e.target.value ? parseInt(e.target.value, 10) : null })}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1 text-slate-100 disabled:opacity-40" /></td>
                  <td className="text-xs">
                    {r.action === 'error' && <span className="text-red-300">{r.error}</span>}
                    {r.action === 'new_major' && <span className="text-blue-300">→ {r.major ? `${effective === 'review' ? 'E' : ''}${r.major}` : (r.suggested_name ?? '?')}</span>}
                    {r.action === 'unchanged' && <span className="text-slate-400">kept {r.current_revision ?? '—'}</span>}
                    {r.action === 'unmatched' && <span className="text-slate-500">skipped</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {error && <p className="text-sm text-red-300">{error}</p>}
        {rows && (
          <div className="flex justify-between gap-2">
            <button onClick={() => setRows(null)} className="px-4 py-2 rounded bg-slate-700 text-slate-100">Back</button>
            <div className="flex gap-2">
              <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 text-slate-100">Cancel</button>
              <button disabled={busy || !canStore} onClick={confirm}
                className="px-4 py-2 rounded bg-blue-600 text-white disabled:bg-slate-600">{busy ? 'Storing…' : 'Store package'}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

Fill the two comment placeholders with the actual radio group, date input and index input copied from `CustomerDataDialog.tsx` (statement radios bound to `statement`/`effective`, date bound to `receivedAt`, index bound to `packageIndex` with placeholder "package index, e.g. B"). Do not leave the comments in.

- [ ] **Step 4: Run the dialog test**

Run: `cd frontend && npx vitest run src/components/parts/CustomerPackageDialog.test.tsx`
Expected: PASS

- [ ] **Step 5: Wire the button on both pages**

`PartDetail.tsx`: next to "+ Customer data" add

```tsx
<button onClick={() => setShowPackage(true)} className="px-4 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium">+ Customer package</button>
```

with `const [showPackage, setShowPackage] = useState(false);`, a query for the project's parts (`client.get(`/v1/parts/project/${part.project_id}`)` or whatever the project items call in `ProjectDetailPage` is; reuse its URL), and

```tsx
{showPackage && (
  <CustomerPackageDialog open assemblyId={part.id} projectParts={projectParts ?? []} officialOnly={hasOfficial}
    onClose={() => setShowPackage(false)}
    onDone={(r) => { toast.success(`Stored ${r.created.length} new, kept ${r.kept.length}`); setShowPackage(false); refetch();
      queryClient.invalidateQueries({ queryKey: ['where-used', partId] }); }} />
)}
```

`ProjectDetailPage.tsx`: same button next to the existing "+ Customer data" for the selected part; `projectParts` is the already-loaded `parts` list mapped to `{id, part_number, name}`; `onDone` invalidates `['part-revisions', selectedPartId]`, `['parts', id]`, `['bom-tree', selectedPartId]` and the assemblies query key used by `AssemblyTreeList`.

- [ ] **Step 6: Type-check and run all frontend tests**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json && npx vitest run`
Expected: no type errors, all PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/parts/CustomerPackageDialog.tsx frontend/src/components/parts/CustomerPackageDialog.test.tsx frontend/src/pages/PartDetail.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(ui): receive a customer package on an assembly

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Documentation

**Files:**
- Modify: `docs/CUSTOMER_DATA_INDEX.md` (sections "Recording customer data", "API"; new section "Receiving a package")
- Modify: `MODULES.md` (Items & Revisions row)

- [ ] **Step 1: Update the guide**

In `docs/CUSTOMER_DATA_INDEX.md`:
- "Recording customer data", step 3: add "Optionally type the revision number if the customer's numbering is ahead of ours (a part may start at E2). It must be above every existing revision of that kind."
- New section after "Proposals":

```markdown
## Receiving a package

A delivery is usually the assembly file plus one file per part, and not
every part changed. On the assembly, **+ Customer package**:

1. Pick review or official, the received date, and (optionally) the index
   the whole package carries. Drop all files.
2. **Check package.** Every file is matched to a part by the customer part
   number (or our number) in the filename. The index is read from the
   filename (`3CR807425B_…` → `B`), else the package index applies.
3. Per file the table says what will happen:
   - **new major**: the index differs from the part's active revision → the
     part gets its next major with this file.
   - **unchanged**: same index as the active revision → nothing is stored,
     the E stays. *If the data did not change, the E does not change.*
   - **unmatched**: pick the part yourself, or leave it and the file is
     skipped.
   Part, index, action and revision number can be corrected per row.
4. **Store package.** Children first, then the assembly, whose new major
   copies its BOM forward so lines point at the children's active
   revisions. Any row error (unsupported file, revision number not above
   the existing one, review after official) stops the whole package;
   nothing is stored until every row is fixed.

Revision names show the customer index everywhere as `E2 · B`.
```

- API table: add
`| `POST /api/v1/parts/{id}/revisions/customer-package/preview` | Match files to parts, decide new/unchanged |`
`| `POST /api/v1/parts/{id}/revisions/customer-package` | Store the confirmed package |`
and note `major` on the customer-data call.

In `MODULES.md`, extend the Items & Revisions row with "customer package receive, chosen major number, customer index shown next to every revision name".

- [ ] **Step 2: Commit**

```bash
git add docs/CUSTOMER_DATA_INDEX.md MODULES.md
git commit -m "docs: customer package receive and chosen revision number

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec §1 (chosen major) → Tasks 1, 2. Spec §2 flow steps 1–5 → Tasks 4, 5, 6, 9. Matching order and index parsing → Task 4. Errors and rollback → Task 5 (`PackageError`, file cleanup) and Task 6 (409 with rows). Spec §3 badge everywhere → Tasks 7, 8. Spec §5 testing list → covered task by task. Docs → Task 10.
- Names used across tasks: `store_revision_file`, `classify`, `UnsupportedFile` (Task 3) are what Task 5 imports; `PackageRow`, `PackageError`, `CustomerPackageService.preview/confirm` (Task 5) are what Task 6 imports; `revisionLabel`/`RevisionBadge` (Task 8) are what Task 9 imports; `major` is the field name in schemas, service and dialog alike.
