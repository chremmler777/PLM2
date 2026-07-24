# Process Flow View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a tool's process route — mold → in-cell station → secondary station → gauge, with upstream tools merging in — derived from `serves`/`feeds` relations rather than stored as a flow definition.

**Architecture:** A read-only endpoint resolves any part to its owning tool, collects the equipment that `serves` that tool, orders it by op code, and lists tools joined by `feeds`. The frontend renders the result as plain SVG/flex markup on `PartDetail` — no charting dependency is added.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest (backend); React + TypeScript + vitest, Tailwind (frontend).

## Global Constraints

- Backend tests run from `backend/` with `pytest`; frontend from `frontend/` with `npx vitest run`.
- Stations are found through `serves` relations, **never** by matching number prefixes. Tool `3455` owns no equipment of its own — its punch-and-weld is `3454-30`, discoverable only via the relation. A prefix match would show 3455 as having no process at all.
- Do not add a charting library. `frontend/package.json` has no mermaid/reactflow/d3 and this feature does not justify one.
- Commit after each task. Commit messages end with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/api/v1/items/part_relations.py` (modify) | Accept and label `serves`/`feeds`. |
| `backend/app/services/process_flow_service.py` (new) | Resolve a part to its tool, gather stations and feeds, order by op code. |
| `backend/app/api/v1/items/process_flow.py` (new) | `GET /parts/{part_id}/process-flow`. |
| `backend/tests/test_process_flow.py` (new) | Service + endpoint tests. |
| `frontend/src/components/parts/ProcessFlow.tsx` (new) | Renders the flow. |
| `frontend/src/components/parts/ProcessFlow.test.tsx` (new) | Component tests. |
| `frontend/src/pages/PartDetail.tsx` (modify) | Mounts the component. |

---

### Task 1: Teach the relations API the new vocabulary

The 168 `serves` and 2 `feeds` rows already in the database cannot be created or
labelled through the API, because `VALID_RELATION_TYPES` predates them.

**Files:**
- Modify: `backend/app/api/v1/items/part_relations.py:19-27`
- Test: `backend/tests/test_process_flow.py` (new file, first test)

**Interfaces:**
- Consumes: `POST /parts/{id}/relations`, `GET /parts/{id}/relations`.
- Produces: `serves`/`feeds` accepted by the create endpoint and labelled in list output.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_process_flow.py`:

```python
"""Process flow is derived from serves/feeds relations, never from number
prefixes: tool 3455's punch-and-weld is numbered 3454-30 and is reachable only
through the relation."""
import pytest

pytestmark = pytest.mark.asyncio


async def _tool(client, auth, seed, number, name, category="tool"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": name,
        "part_type": "purchased", "item_category": category,
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_serves_relation_is_accepted_and_labelled(client, admin_auth, seed):
    gauge = await _tool(client, admin_auth, seed, "3454-40", "gauge", "gauge")
    tool = await _tool(client, admin_auth, seed, "3454", "Rear Cladding")

    res = await client.post(f"/api/v1/parts/{gauge}/relations", json={
        "to_part_id": tool, "relation_type": "serves"}, headers=admin_auth)
    assert res.status_code == 201, res.text
    assert res.json()["label"] == "serves"

    rows = (await client.get(f"/api/v1/parts/{tool}/relations",
                             headers=admin_auth)).json()
    served_by = [r for r in rows if r["relation_type"] == "serves"]
    assert served_by and served_by[0]["label"] == "served by"


async def test_feeds_relation_is_accepted_and_labelled(client, admin_auth, seed):
    upstream = await _tool(client, admin_auth, seed, "3457", "PDC Brackets")
    downstream = await _tool(client, admin_auth, seed, "3454", "Rear Cladding")

    res = await client.post(f"/api/v1/parts/{upstream}/relations", json={
        "to_part_id": downstream, "relation_type": "feeds",
        "notes": "2 brackets"}, headers=admin_auth)
    assert res.status_code == 201, res.text
    assert res.json()["label"] == "feeds"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_process_flow.py -q -p no:logging`
Expected: FAIL with 400 — `Invalid relation_type. Valid: assembles, checks, produces, related`.

- [ ] **Step 3: Extend the vocabulary**

In `backend/app/api/v1/items/part_relations.py`, replace lines 19-27:

```python
VALID_RELATION_TYPES = {"produces", "checks", "assembles", "related"}

# Human-readable labels per direction
RELATION_LABELS = {
    "produces": ("produces", "produced by"),
    "checks": ("checks", "checked by"),
    "assembles": ("assembles", "assembled by"),
    "related": ("related to", "related to"),
}
```

with:

```python
VALID_RELATION_TYPES = {"produces", "checks", "assembles", "related",
                        "serves", "feeds"}

# Human-readable labels per direction
RELATION_LABELS = {
    "produces": ("produces", "produced by"),
    "checks": ("checks", "checked by"),
    "assembles": ("assembles", "assembled by"),
    "related": ("related to", "related to"),
    # serves: equipment -> every tool it covers (see equipment_numbering.py).
    # feeds: tool -> downstream tool whose station consumes its parts.
    "serves": ("serves", "served by"),
    "feeds": ("feeds", "fed by"),
}
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_process_flow.py -q -p no:logging`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/api/v1/items/part_relations.py backend/tests/test_process_flow.py
git commit -m "feat(equipment): accept and label serves/feeds in the relations API

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Process-flow service and endpoint

**Files:**
- Create: `backend/app/services/process_flow_service.py`
- Create: `backend/app/api/v1/items/process_flow.py`
- Modify: `backend/app/api/v1/__init__.py` (register the router next to `part_relations_router`)
- Test: `backend/tests/test_process_flow.py` (append)

**Interfaces:**
- Consumes: `PartRelation`, `Part`; `parse_equipment_number` from `app.services.equipment_numbering`.
- Produces: `ProcessFlowService.build(session, part_id) -> dict | None` and
  `GET /api/v1/parts/{part_id}/process-flow` returning:

```json
{
  "tool": {"id": 1, "part_number": "3454", "name": "Rear Cladding"},
  "upstream": [{"id": 4, "part_number": "3457", "name": "PDC Brackets", "note": "2 brackets"}],
  "downstream": [],
  "stations": [
    {"id": 9, "part_number": "3454-30", "name": "Punch & weld station",
     "op_code": "30", "kind": "secondary_station", "serves": ["3454", "3455", "3457"]}
  ]
}
```

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_process_flow.py`:

```python
async def _relate(client, auth, from_id, to_id, rel_type, notes=None):
    res = await client.post(f"/api/v1/parts/{from_id}/relations", json={
        "to_part_id": to_id, "relation_type": rel_type, "notes": notes},
        headers=auth)
    assert res.status_code == 201, res.text


async def _vw426_cell(client, auth, seed):
    """3454 + 3455 share a punch-and-weld; 3457 feeds both; 3454-40 gauges both."""
    ids = {}
    for number, name, cat in [
        ("3454", "Rear Cladding Basis", "tool"),
        ("3455", "Rear Cladding Peak", "tool"),
        ("3457", "PDC Brackets", "tool"),
        ("3454-30", "Punch & weld station", "assembly_equipment"),
        ("3454-40", "Rear Cladding gauge", "gauge"),
    ]:
        ids[number] = await _tool(client, auth, seed, number, name, cat)
    for tool in ("3454", "3455", "3457"):
        await _relate(client, auth, ids["3454-30"], ids[tool], "serves")
    for tool in ("3454", "3455"):
        await _relate(client, auth, ids["3454-40"], ids[tool], "serves")
    await _relate(client, auth, ids["3457"], ids["3454"], "feeds", "2 brackets")
    await _relate(client, auth, ids["3457"], ids["3455"], "feeds", "2 brackets")
    return ids


async def test_flow_orders_stations_by_op_code(client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3454']}/process-flow",
                             headers=admin_auth)).json()
    assert body["tool"]["part_number"] == "3454"
    assert [s["op_code"] for s in body["stations"]] == ["30", "40"]
    assert body["stations"][1]["kind"] == "gauge"


async def test_shared_station_appears_on_the_tool_it_does_not_own(
        client, admin_auth, seed):
    """3455 owns no equipment; its station is numbered 3454-30. Prefix matching
    would show an empty process — the serves relation must drive it."""
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3455']}/process-flow",
                             headers=admin_auth)).json()
    assert [s["part_number"] for s in body["stations"]] == ["3454-30", "3454-40"]


async def test_upstream_feeds_are_listed_with_their_note(client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3454']}/process-flow",
                             headers=admin_auth)).json()
    assert [u["part_number"] for u in body["upstream"]] == ["3457"]
    assert body["upstream"][0]["note"] == "2 brackets"


async def test_downstream_is_listed_for_the_feeding_tool(client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3457']}/process-flow",
                             headers=admin_auth)).json()
    assert sorted(d["part_number"] for d in body["downstream"]) == ["3454", "3455"]


async def test_asking_from_an_equipment_part_resolves_to_its_tool(
        client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3454-40']}/process-flow",
                             headers=admin_auth)).json()
    assert body["tool"]["part_number"] == "3454"


async def test_tool_with_no_equipment_returns_an_empty_flow(client, admin_auth, seed):
    lone = await _tool(client, admin_auth, seed, "3999", "Lonely tool")
    body = (await client.get(f"/api/v1/parts/{lone}/process-flow",
                             headers=admin_auth)).json()
    assert body["stations"] == []
    assert body["upstream"] == []


async def test_unknown_part_is_404(client, admin_auth, seed):
    res = await client.get("/api/v1/parts/999999/process-flow", headers=admin_auth)
    assert res.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_process_flow.py -q -p no:logging`
Expected: the seven new tests FAIL with 404 — the route does not exist.

- [ ] **Step 3: Write the service**

Create `backend/app/services/process_flow_service.py`:

```python
"""Derive a tool's process route from serves/feeds relations.

Nothing is stored: the flow is whatever the equipment records currently say, so
it cannot drift from them. The cost is that an ordering not implied by op code
(two secondary stations in a required sequence) cannot be expressed.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.part import Part, PartRelation
from app.services.equipment_numbering import classify, parse_equipment_number


def _part_brief(part: Part) -> dict:
    return {"id": part.id, "part_number": part.part_number, "name": part.name}


class ProcessFlowService:

    @staticmethod
    async def _resolve_tool(session: AsyncSession, part: Part) -> Optional[Part]:
        """Equipment resolves to the tool it serves; a tool resolves to itself.

        Uses the serves relation rather than the number, because the number only
        names the lowest tool a shared station covers.
        """
        if part.item_category == "tool":
            return part
        owner = (await session.execute(
            select(Part).join(PartRelation, PartRelation.to_part_id == Part.id)
            .where(PartRelation.from_part_id == part.id,
                   PartRelation.relation_type == "serves")
            .order_by(Part.part_number))).scalars().first()
        return owner

    @staticmethod
    async def build(session: AsyncSession, part_id: int) -> Optional[dict]:
        part = await session.get(Part, part_id)
        if part is None:
            return None
        tool = await ProcessFlowService._resolve_tool(session, part)
        if tool is None:
            return {"tool": _part_brief(part), "upstream": [], "downstream": [],
                    "stations": []}

        # Equipment that serves this tool — the relation, not the number, is
        # authoritative: 3455's station is numbered 3454-30.
        station_rows = (await session.execute(
            select(PartRelation)
            .where(PartRelation.to_part_id == tool.id,
                   PartRelation.relation_type == "serves")
            .options(joinedload(PartRelation.from_part)))).scalars().all()

        stations = []
        for rel in station_rows:
            equipment = rel.from_part
            _, op_code = parse_equipment_number(equipment.part_number)
            if op_code is None:
                continue
            covered = (await session.execute(
                select(Part.part_number).join(
                    PartRelation, PartRelation.to_part_id == Part.id)
                .where(PartRelation.from_part_id == equipment.id,
                       PartRelation.relation_type == "serves")
                .order_by(Part.part_number))).scalars().all()
            stations.append({
                "id": equipment.id,
                "part_number": equipment.part_number,
                "name": equipment.name,
                "op_code": op_code,
                "kind": classify(op_code),
                "serves": list(covered),
            })
        stations.sort(key=lambda s: (s["op_code"], s["part_number"]))

        upstream = [
            {**_part_brief(rel.from_part), "note": rel.notes}
            for rel in (await session.execute(
                select(PartRelation)
                .where(PartRelation.to_part_id == tool.id,
                       PartRelation.relation_type == "feeds")
                .options(joinedload(PartRelation.from_part)))).scalars().all()
        ]
        downstream = [
            {**_part_brief(rel.to_part), "note": rel.notes}
            for rel in (await session.execute(
                select(PartRelation)
                .where(PartRelation.from_part_id == tool.id,
                       PartRelation.relation_type == "feeds")
                .options(joinedload(PartRelation.to_part)))).scalars().all()
        ]

        return {"tool": _part_brief(tool), "upstream": upstream,
                "downstream": downstream, "stations": stations}
```

- [ ] **Step 4: Write the endpoint**

Create `backend/app/api/v1/items/process_flow.py`:

```python
"""Read-only process route for a tool, derived from serves/feeds relations."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.process_flow_service import ProcessFlowService

router = APIRouter(prefix="/parts", tags=["process-flow"])


@router.get("/{part_id}/process-flow", response_model=dict)
async def get_process_flow(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mold -> in-cell -> secondary -> gauge for this part's tool, plus the
    tools feeding into it. Asking from a gauge or station resolves to its tool.
    """
    flow = await ProcessFlowService.build(db, part_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Part not found")
    return flow
```

- [ ] **Step 5: Register the router**

In `backend/app/api/v1/__init__.py`, next to the existing `part_relations_router`
import and include, add:

```python
from app.api.v1.items.process_flow import router as process_flow_router
```

and, beside `api_router.include_router(part_relations_router)`:

```python
api_router.include_router(process_flow_router)
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_process_flow.py -q -p no:logging`
Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/process_flow_service.py backend/app/api/v1/items/process_flow.py backend/app/api/v1/__init__.py backend/tests/test_process_flow.py
git commit -m "feat(equipment): derived process-flow endpoint

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Frontend process-flow view

**Files:**
- Create: `frontend/src/components/parts/ProcessFlow.tsx`
- Create: `frontend/src/components/parts/ProcessFlow.test.tsx`
- Modify: `frontend/src/pages/PartDetail.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/parts/{id}/process-flow` (Task 2), `api` client from `../../api/client`.
- Produces: `<ProcessFlow partId={number} />`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/parts/ProcessFlow.test.tsx`:

```typescript
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ProcessFlow from './ProcessFlow'

const flow = {
  tool: { id: 1, part_number: '3454', name: 'Rear Cladding Basis' },
  upstream: [{ id: 4, part_number: '3457', name: 'PDC Brackets', note: '2 brackets' }],
  downstream: [],
  stations: [
    { id: 9, part_number: '3454-30', name: 'Punch & weld station', op_code: '30',
      kind: 'secondary_station', serves: ['3454', '3455', '3457'] },
    { id: 10, part_number: '3454-40', name: 'Rear Cladding gauge', op_code: '40',
      kind: 'gauge', serves: ['3454', '3455'] },
  ],
}

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: flow })) },
  api: { get: vi.fn(() => Promise.resolve({ data: flow })) },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({
    defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
)

describe('ProcessFlow', () => {
  afterEach(cleanup)

  it('renders the mold first, then stations in op-code order', async () => {
    render(wrap(<ProcessFlow partId={1} />))
    await waitFor(() => expect(screen.getByText('3454-30')).toBeDefined())
    const numbers = screen.getAllByTestId('flow-node').map((n) => n.textContent)
    expect(numbers[0]).toContain('3454')
    expect(numbers[1]).toContain('3454-30')
    expect(numbers[2]).toContain('3454-40')
  })

  it('marks a station shared with other tools', async () => {
    render(wrap(<ProcessFlow partId={1} />))
    await waitFor(() => expect(screen.getByText('3454-30')).toBeDefined())
    expect(screen.getByText(/3455/)).toBeDefined()
  })

  it('shows an upstream tool with its note', async () => {
    render(wrap(<ProcessFlow partId={1} />))
    await waitFor(() => expect(screen.getByText('3457')).toBeDefined())
    expect(screen.getByText(/2 brackets/)).toBeDefined()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/parts/ProcessFlow.test.tsx`
Expected: FAIL — `Failed to resolve import "./ProcessFlow"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/parts/ProcessFlow.tsx`:

```typescript
import { useQuery } from '@tanstack/react-query'
import api from '../../api/client'

type Station = {
  id: number
  part_number: string
  name: string
  op_code: string
  kind: string
  serves: string[]
}

type Flow = {
  tool: { id: number; part_number: string; name: string }
  upstream: { id: number; part_number: string; name: string; note: string | null }[]
  downstream: { id: number; part_number: string; name: string; note: string | null }[]
  stations: Station[]
}

const KIND_LABEL: Record<string, string> = {
  eoat: 'EOAT',
  in_cell_station: 'In-cell',
  secondary_station: 'Secondary',
  gauge: 'Gauge',
}

function Node({ number, name, sub }: { number: string; name: string; sub?: string }) {
  return (
    <div data-testid="flow-node"
         className="min-w-[9rem] rounded border border-slate-700 bg-slate-800 px-3 py-2">
      <div className="font-mono text-sm text-slate-100">{number}</div>
      <div className="text-xs text-slate-300">{name}</div>
      {sub && <div className="mt-1 text-[11px] text-slate-400">{sub}</div>}
    </div>
  )
}

export default function ProcessFlow({ partId }: { partId: number }) {
  const { data, isLoading } = useQuery<Flow>({
    queryKey: ['process-flow', partId],
    queryFn: async () => (await api.get(`/parts/${partId}/process-flow`)).data,
  })

  if (isLoading) return <p className="text-sm text-slate-400">Loading process…</p>
  if (!data) return null
  if (data.stations.length === 0 && data.upstream.length === 0)
    return <p className="text-sm text-slate-400">No equipment recorded for this tool yet.</p>

  return (
    <div className="space-y-3">
      {data.upstream.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">Feeds in</span>
          {data.upstream.map((u) => (
            <Node key={u.id} number={u.part_number} name={u.name}
                  sub={u.note ?? undefined} />
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 overflow-x-auto">
        <Node number={data.tool.part_number} name={data.tool.name} sub="Mold" />
        {data.stations.map((s) => (
          <div key={s.id} className="flex items-center gap-2">
            <span aria-hidden className="text-slate-500">→</span>
            <Node number={s.part_number} name={s.name}
                  sub={[KIND_LABEL[s.kind] ?? s.kind,
                       s.serves.length > 1 ? `shared: ${s.serves.join(', ')}` : null]
                       .filter(Boolean).join(' · ')} />
          </div>
        ))}
      </div>
      {data.downstream.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">Feeds into</span>
          {data.downstream.map((d) => (
            <Node key={d.id} number={d.part_number} name={d.name}
                  sub={d.note ?? undefined} />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/components/parts/ProcessFlow.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Mount it on PartDetail**

In `frontend/src/pages/PartDetail.tsx`, import the component:

```typescript
import ProcessFlow from '../components/parts/ProcessFlow'
```

and render it in a titled section alongside the existing detail sections, passing
the part id the page already holds:

```tsx
<section className="mt-6">
  <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
    Process
  </h2>
  <ProcessFlow partId={part.id} />
</section>
```

Match the surrounding section markup in that file rather than copying these class
names verbatim if they differ.

- [ ] **Step 6: Type-check and run the frontend suite**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc clean, all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/parts/ProcessFlow.tsx frontend/src/components/parts/ProcessFlow.test.tsx frontend/src/pages/PartDetail.tsx
git commit -m "feat(equipment): process-flow view on part detail

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Regression check

- [ ] **Step 1: Run both suites**

Run: `cd backend && pytest -q -p no:logging` (about 8 minutes — run in the background)
Run: `cd frontend && npx vitest run`
Expected: all pass.

- [ ] **Step 2: Check the live data through the endpoint**

The live database already holds 168 `serves` and 2 `feeds` rows. Spot-check that
3455 — which owns no equipment — reports the shared `3454-30` and `3454-40`.

## Self-Review

**Spec coverage:** §5 "process flow — derived view, walk serves/feeds, order by op
code, upstream tools render as merging branches" → Tasks 2 and 3. ✓ The spec's
stated limitation (no ordering beyond op code) is carried into the service
docstring rather than silently worked around. ✓

**Placeholder scan:** no TBD/TODO. Task 3 Step 5 tells the implementer to match
surrounding markup rather than prescribing class names for a file this plan has
not read in full — that is a deliberate instruction, not a placeholder. ✓

**Type consistency:** `ProcessFlowService.build(session, part_id) -> dict | None`
defined in Task 2 and called once, in the endpoint of the same task. The `Flow`
TypeScript type in Task 3 mirrors the JSON shape declared in Task 2's Interfaces
block field for field (`tool`, `upstream`, `downstream`, `stations`, and each
station's `op_code`/`kind`/`serves`). ✓
