# Project page redesign: slim overview, two panes, pop-out detail - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 1837-line project page into a fixed-height work surface: an icon-rail sidebar, one-line header with status chips and slide-over sections, a grouped slim items list on the left, a pinned-header tabbed detail on the right, a remembered splitter, keyboard navigation, and a pop-out detail window that follows the selection over a `BroadcastChannel`.

**Architecture:** First split `ProjectDetailPage.tsx` into `components/project/*` modules with no behaviour change (four extraction tasks, the existing 22 tests stay green). Selection state moves into a `useArticleSelection` hook so the main page and the pop-out page share one set of revision rules. Then each layout change lands as its own TDD task against the extracted components. The pop-out is a second route (`/projects/:projectId/detail`) that renders only `DetailPane` and talks to the main window through `useSelectionChannel`.

**Tech Stack:** React 18 + TypeScript, react-router-dom 6, TanStack Query 5, Tailwind, vitest 1 + @testing-library/react 14 (jsdom). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-projects-page-redesign-design.md`

## Global Constraints

- Sidebar on `/projects/:id` starts collapsed as a 48 px rail (`w-12`) with icons and hover labels; a click expands it; the choice is remembered per browser in `localStorage`; default collapsed on project pages, unchanged elsewhere.
- Every `localStorage` access goes through `frontend/src/lib/safeStorage.ts` (try/catch, sane default when storage throws or holds garbage).
- Header is one row: code, name, customer; three chips (SEP gate + progress, open change count, lessons state); chip opens its section (`ProjectSepSection`, `ProjectChangesSection`, `ProjectLessonsSection`, unchanged inside) in a slide-over from the right; Escape or a click outside closes it. The ⋯ menu holds Start change request, + Add Part, customer file naming and + Gate.
- `ProjectPaintSection` is not mounted on the project page. The "Painted" filter chip stays.
- Item groups, in this order, empty ones hidden: Articles, Tools, Equipment, Gauges, Assemblies. Collapsible, with count.
- Row line 1: customer number (mono) then short name (customer number and project code stripped). Items without a customer number show the internal number on line 1. Row line 2 (small, muted): internal number, active revision label (`E1 · 003`), lifecycle phase, icons for mirror, painted, proposal. Part-type badge moves to the detail header. Expand chevron content and drag-to-restructure keep working.
- Project page never scrolls as a whole: fixed header, independently scrolling items list, detail pane with pinned header and tab bar where only tab content scrolls. Splitter width remembered per browser with minimum widths.
- Detail tabs: Documents, Links, BOM, Workflow, Changelog. Selected tab survives switching items.
- Pop-out: ⧉ in the detail header opens `/projects/:id/detail` via `window.open` with a fixed window name (second click reuses it). Channel name `plm2-project-<id>`. Main posts the selected part and revision; pop-out follows and answers a "hello". While the pop-out is open the main window hides the detail and shows the items as a table: customer number, Tier 1 number, name, phase, active revision, tool, cavities (cavities only when the tool fields exist). Closing the pop-out brings the pane back. No ⧉ when `BroadcastChannel` is missing.
- Keyboard: Up/Down move the selection when the items list has focus, detail follows; Right/Left expand/collapse a row.
- Out of scope: mobile layout, a project dashboard page, always-on-top windows, dragging panes, any change to the sections' own content.
- No em dashes in code comments, UI copy or commit messages.
- Every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- New `.tsx` files export only components (plus types). Hooks, helpers and non-primitive constants live in `.ts` files, because `react-refresh/only-export-components` is a lint warning and `npm run lint` runs with `--max-warnings 0`.

## Review Focus

1. Stored splitter width or rail flag that is garbage (`"abc"`, `"99999"`, `"-5"`) or a storage that throws on read and write: the page must render with defaults (clamped), dragging must keep working, nothing may throw. Tests in Task 5 (rail) and Task 9 (splitter).
2. The pop-out window closed by the user, the OS or a crash without its `bye` message arriving: the main window must notice (poll `window.closed`) and bring the detail pane back. Test in Task 14.
3. A search that matches a part nested under an assembly whose own name does not match: the nested part must still be listed (search flattens the tree). Test in Task 8.
4. Arrow keys pressed while typing in the search box, and ArrowDown when the selected item sits in a collapsed group: typing must not move the selection; ArrowDown must jump to the first visible row. Tests in Task 11.
5. A selection message naming a part the pop-out does not know yet (created in the main window after the pop-out loaded): the pop-out must show its empty prompt, refetch the parts, and then show the part. Test in Task 13.

---

## File structure

Create:
- `frontend/src/components/project/projectTypes.ts` - shared shapes (`Project`, `Part`, `PartRevision`, `RevisionFile`, `TreeNode`, ...), `CATEGORY_META`, `CUSTOMER_NAMING_LABELS`, tree helpers, colour helpers.
- `frontend/src/components/project/projectTypes.test.ts`
- `frontend/src/hooks/queries/useProjectDetail.ts` - `useProject`, `useProjectParts`, `usePartRevisions`, `useRevisionFiles`, `useAssemblyFiles`, `useChangelog`, `useCatalogParts`.
- `frontend/src/hooks/queries/useProjectDetail.test.tsx`
- `frontend/src/hooks/queries/useSuppliers.ts` - only if it does not exist yet (the `feature/tool-dfm-archive` branch creates the same file).
- `frontend/src/components/project/RevisionFileRow.tsx` (+ `.test.tsx`, moved tests)
- `frontend/src/components/project/CustomerNamingSelect.tsx` (+ `.test.tsx`, moved tests)
- `frontend/src/components/project/BomTreeSection.tsx`
- `frontend/src/components/project/ChangelogModal.tsx` - modal and (Task 11) `ChangelogList`.
- `frontend/src/components/project/ProjectContextMenu.tsx`
- `frontend/src/components/project/AddPartModal.tsx`
- `frontend/src/components/project/ItemRow.tsx` - one item row and its expand block.
- `frontend/src/components/project/ItemsPane.tsx` (+ `.test.tsx`) - search, filters, groups, keyboard, table mode.
- `frontend/src/components/project/itemGroups.ts` (+ `.test.ts`) - grouping, search match, visible order, table cells.
- `frontend/src/hooks/useArticleSelection.ts` (+ `.test.tsx`) - selected part, revision, document; revision race guard.
- `frontend/src/components/project/DetailPane.tsx` - pinned header, tab bar, tab bodies.
- `frontend/src/components/project/DetailHeader.tsx` - pinned header.
- `frontend/src/components/project/DocumentsTab.tsx` - revision strip, document pane, files, uploads.
- `frontend/src/components/project/detailTabs.ts` - `DetailTab`, `DETAIL_TABS`.
- `frontend/src/components/project/ProjectHeaderBar.tsx` (+ `.test.tsx`)
- `frontend/src/hooks/queries/useProjectStatus.ts` (+ `.test.ts`) - chip data.
- `frontend/src/components/project/StatusSlideOver.tsx`
- `frontend/src/components/project/SplitPane.tsx` (+ `.test.tsx`)
- `frontend/src/lib/safeStorage.ts` (+ `.test.ts`)
- `frontend/src/hooks/useSelectionChannel.ts` (+ `.test.tsx`)
- `frontend/src/testing/fakeBroadcastChannel.ts` - in-memory `BroadcastChannel` for tests.
- `frontend/src/pages/ProjectDetailPopout.tsx` (+ `.test.tsx`)
- `frontend/src/pages/ProjectDetailPage.layout.test.tsx` - page-level tests for the new layout.

Modify:
- `frontend/src/pages/ProjectDetailPage.tsx` - shrinks to data hooks, selection state and the layout shell.
- `frontend/src/pages/ProjectDetailPage.files.test.tsx`, `ProjectDetailPage.article.test.tsx` - moved describe block out; small, named updates where the layout changes what a test clicks.
- Delete: `frontend/src/pages/ProjectDetailPage.naming.test.tsx` (moved).
- `frontend/src/components/parts/RevisionFilesGrouped.tsx`, `frontend/src/pages/PartDetail.tsx` - import `RevisionFileRow` / `RevisionFile` from the new module (breaks the page <-> component import cycle).
- `frontend/src/components/layout/Sidebar.tsx` (+ test) - project rail.
- `frontend/src/lib/partDisplay.ts` (+ test) - `shortName`.
- `frontend/src/App.tsx` - pop-out route, `ProtectedRoute bare`.

Commands used throughout (run from the frontend folder):
- One file: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run <path>`
- Page tests: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ProjectDetailPage src/components/project`
- Everything: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run && npx tsc --noEmit`
- Lint of touched files: `cd /home/nitrolinux/claude/plm2/frontend && npx eslint src/components/project src/hooks src/lib/safeStorage.ts src/pages/ProjectDetailPage.tsx src/pages/ProjectDetailPopout.tsx src/components/layout --max-warnings 0`

Baseline on `main` before Task 1: `npx vitest run src/pages/ProjectDetailPage` = 4 files, 22 tests passed. `npx eslint src/pages/ProjectDetailPage.tsx` = 5 problems (4 `no-explicit-any` errors, 1 `only-export-components` warning). The extraction removes all five.

### Coordination with `feature/tool-dfm-archive`

That branch (worktree `/home/nitrolinux/claude/plm2-dfm`) deletes the local `SupplierOption` / `useSuppliers` from `ProjectDetailPage.tsx` (~lines 655-678) and creates `frontend/src/hooks/queries/useSuppliers.ts` with `useSuppliers()` returning `SupplierOption[]` under query key `['suppliers', false]`. This plan never keeps a local copy: Task 1 creates the same file (byte-identical content) only if it is missing, and Task 2 moves `AddPartModal` (the only caller) out of the page with an import of that hook. Whichever branch merges second resolves the conflict by keeping the page as this plan leaves it and keeping one copy of `useSuppliers.ts`.

---

### Task 1: Shared types, tree helpers and query hooks in their own modules

Pure extraction. No behaviour change.

**Files:**
- Create: `frontend/src/components/project/projectTypes.ts`
- Create: `frontend/src/components/project/projectTypes.test.ts`
- Create: `frontend/src/hooks/queries/useProjectDetail.ts`
- Create: `frontend/src/hooks/queries/useProjectDetail.test.tsx`
- Create (only if missing): `frontend/src/hooks/queries/useSuppliers.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (delete lines 38-237 types/queries/tree helpers, 290-326 colour helpers and `useChangelog`, 435-448 `getDescendantIds`, 648-676 catalog/supplier queries; add imports)

**Interfaces:**
- Produces (`components/project/projectTypes.ts`): `type CustomerNaming`, `CUSTOMER_NAMING_LABELS`, `interface Project`, `interface Part`, `CATEGORY_META`, `interface PartRevision`, `interface ContextMenuState` (was `ContextMenu`), `interface TreeNode`, `interface RevisionFile`, `LOCKED_REVISION_STATUSES`, `interface AssemblyFileEntry`, `interface ChangelogEntry`, `interface CatalogPart`, `comparePartNodes(a, b)`, `buildPartTree(parts): TreeNode[]`, `getDescendantIds(parts, partId): Set<number>`, `typeColor(partType)`, `phaseColor(phase)`, `statusColor(status)`.
- Produces (`hooks/queries/useProjectDetail.ts`): `useProject(projectId)`, `useProjectParts(projectId)`, `usePartRevisions(partId)`, `useRevisionFiles(revisionId)`, `useAssemblyFiles(partId)`, `useChangelog(partId)`, `useCatalogParts()`; query keys unchanged (`['project', id]`, `['parts', id]`, `['part-revisions', id]`, `['revision-files', id]`, `['assembly-files', id]`, `['part-changelog', id]`, `['catalog-parts']`).
- Produces (`hooks/queries/useSuppliers.ts`): `interface SupplierOption { id: number; name: string }`, `useSuppliers()`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/project/projectTypes.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { buildPartTree, getDescendantIds, typeColor, type Part } from './projectTypes'

const p = (id: number, part_number: string, parent_part_id: number | null = null, over: Partial<Part> = {}): Part => ({
  id, part_number, name: `P${id}`, part_type: 'internal_mfg', active_revision_id: null,
  item_category: 'article', parent_part_id, ...over,
})

describe('buildPartTree', () => {
  it('nests children under their parent and sorts by the embedded number', () => {
    const tree = buildPartTree([p(1, '1994-10'), p(2, '1994-2'), p(3, '1994-3', 1), p(4, '1994-1', 1)])
    expect(tree.map((n) => n.part.part_number)).toEqual(['1994-2', '1994-10'])
    expect(tree[1].children.map((n) => n.part.part_number)).toEqual(['1994-1', '1994-3'])
  })

  it('drops parts caught in a parent cycle instead of looping', () => {
    expect(buildPartTree([p(1, 'A', 2), p(2, 'B', 1)])).toEqual([])
  })
})

describe('getDescendantIds', () => {
  it('collects children and grandchildren', () => {
    const parts = [p(1, 'A'), p(2, 'B', 1), p(3, 'C', 2), p(4, 'D')]
    expect([...getDescendantIds(parts, 1)].sort()).toEqual([2, 3])
  })
})

describe('typeColor', () => {
  it('falls back for unknown part types', () => {
    expect(typeColor('sub_assembly')).toContain('blue')
    expect(typeColor('whatever')).toBe('bg-slate-700 text-slate-300')
  })
})
```

`frontend/src/hooks/queries/useProjectDetail.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useProject, useProjectParts } from './useProjectDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
)

describe('useProjectDetail queries', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 1, name: 'Other', code: 'X' }, { id: 2, name: 'Atlas', code: '1994' }] })
      if (url === '/v1/parts/project/2') return Promise.resolve({ data: [{ id: 5 }] })
      return Promise.resolve({ data: [] })
    })
  })

  it('picks the project out of the organisation list', async () => {
    const { result } = renderHook(() => useProject(2), { wrapper })
    await waitFor(() => expect(result.current.data?.name).toBe('Atlas'))
  })

  it('loads the project parts', async () => {
    const { result } = renderHook(() => useProjectParts(2), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual([{ id: 5 }]))
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project/projectTypes.test.ts src/hooks/queries/useProjectDetail.test.tsx`
Expected: FAIL, "Failed to resolve import './projectTypes'" and "'./useProjectDetail'".

- [ ] **Step 3: Create `frontend/src/components/project/projectTypes.ts`**

```ts
/**
 * Shapes and helpers shared by the project page, its panes and the pop-out
 * detail window. Moved out of ProjectDetailPage without change.
 */
import { comparePartNumbers } from '../../lib/partDisplay';

export type CustomerNaming = 'vw' | 'scout' | null;
export const CUSTOMER_NAMING_LABELS: Record<Exclude<CustomerNaming, null>, string> = { vw: 'VW group', scout: 'Scout' };

export interface Project {
  id: number;
  name: string;
  code: string;
  status: string;
  customer_naming?: CustomerNaming;
}

export interface Part {
  id: number;
  part_number: string;
  customer_part_number?: string | null;
  tier1_part_number?: string | null;
  name: string;
  part_type: string;
  supplier?: string | null;
  data_classification?: string;
  active_revision_id: number | null;
  parent_part_id?: number | null;
  item_category: string;
  calibration_interval_months?: number | null;
  last_calibrated_at?: string | null;
  next_calibration_due?: string | null;
}

// Controlled item categories (automotive PLM)
export const CATEGORY_META: Record<string, { label: string; icon: string; badge: string }> = {
  article: { label: 'Article', icon: '📄', badge: 'bg-slate-600 text-slate-200' },
  tool: { label: 'Tool', icon: '🔧', badge: 'bg-orange-900/50 text-orange-300' },
  assembly_equipment: { label: 'Equipment', icon: '🏗️', badge: 'bg-cyan-900/50 text-cyan-300' },
  gauge: { label: 'Gauge', icon: '📏', badge: 'bg-pink-900/50 text-pink-300' },
};

export interface PartRevision {
  id: number;
  part_id: number;
  revision_name: string;
  phase: 'review' | 'official';
  status: string;
  created_at: string;
  summary?: string;
  part_phase_at_receipt?: string;
  customer_index?: string | null;
}

export interface ContextMenuState {
  partId: number;
  x: number;
  y: number;
}

export interface TreeNode {
  part: Part;
  children: TreeNode[];
}

export interface RevisionFile {
  id: number;
  revision_id: number;
  filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  cad_format: string | null;
  has_viewer: boolean;
  uploaded_at: string;
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
  kind?: string | null;
  note?: string | null;
}

export const LOCKED_REVISION_STATUSES = ['frozen', 'cancelled', 'archived'];

export interface AssemblyFileEntry {
  part_id: number;
  part_number: string;
  part_name: string;
  revision_id: number;
  revision_name: string;
  file_id: number;
  // Optional throughout: files uploaded before provenance was recorded have none.
  uploaded_at?: string | null;
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
}

export interface ChangelogEntry {
  id: number;
  action: string;
  action_description: string;
  performed_by_user: string | null;
  performed_at: string;
  revision_id: number | null;
}

export interface CatalogPart {
  id: number;
  part_number: string;
  name: string;
  supplier: string | null;
  unit: string;
}

// Order by the embedded tool number: "3450" for a tool, the middle "3450" for
// an article like "20-3450-001-0". Groups each tool with the articles it produces
// (tool first), so the list runs 3450 → 3457 instead of all 10-/20- prefixes first.
export function comparePartNodes(a: TreeNode, b: TreeNode): number {
  return comparePartNumbers(a.part.part_number, b.part.part_number);
}

// Build tree structure from flat parts list
export function buildPartTree(parts: Part[]): TreeNode[] {
  const partMap = new Map<number, Part>(parts.map((p) => [p.id, p]));
  const roots: TreeNode[] = [];
  const visited = new Set<number>();

  function buildNode(partId: number): TreeNode | null {
    if (visited.has(partId)) return null;
    visited.add(partId);

    const part = partMap.get(partId);
    if (!part) return null;

    const children: TreeNode[] = [];
    for (const candidate of parts) {
      if (candidate.parent_part_id === partId) {
        const childNode = buildNode(candidate.id);
        if (childNode) children.push(childNode);
      }
    }

    children.sort(comparePartNodes);
    return { part, children };
  }

  // Find root parts (no parent)
  for (const part of parts) {
    if (!part.parent_part_id) {
      const node = buildNode(part.id);
      if (node) roots.push(node);
    }
  }

  roots.sort(comparePartNodes);
  return roots;
}

// Collect a part's descendant ids (for drag-and-drop cycle prevention)
export function getDescendantIds(parts: Part[], partId: number): Set<number> {
  const ids = new Set<number>();
  const walk = (id: number) => {
    for (const p of parts) {
      if (p.parent_part_id === id && !ids.has(p.id)) {
        ids.add(p.id);
        walk(p.id);
      }
    }
  };
  walk(partId);
  return ids;
}

export function typeColor(partType: string): string {
  const colors: Record<string, string> = {
    purchased: 'bg-slate-600 text-slate-200',
    internal_mfg: 'bg-amber-900/50 text-amber-300',
    sub_assembly: 'bg-blue-900/50 text-blue-300',
  };
  return colors[partType] || 'bg-slate-700 text-slate-300';
}

export function phaseColor(phase: string): string {
  return phase === 'official' ? 'bg-amber-900/30 text-amber-300' : 'bg-blue-900/30 text-blue-300';
}

export function statusColor(status: string): string {
  const colors: Record<string, string> = {
    draft: 'text-slate-400',
    in_progress: 'text-blue-400',
    in_review: 'text-yellow-400',
    approved: 'text-green-400',
    frozen: 'text-green-500',
    rejected: 'text-red-400',
    cancelled: 'text-slate-500',
  };
  return colors[status] || 'text-slate-300';
}
```

- [ ] **Step 4: Create `frontend/src/hooks/queries/useProjectDetail.ts`**

```ts
/**
 * Queries behind the project page and the pop-out detail window.
 * Moved out of ProjectDetailPage without change; query keys are shared with
 * the invalidations spread across the page, so do not rename them.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import type {
  AssemblyFileEntry, CatalogPart, ChangelogEntry, Part, PartRevision, Project, RevisionFile,
} from '../../components/project/projectTypes';

export function useProject(projectId: number) {
  return useQuery<Project>({
    queryKey: ['project', projectId],
    queryFn: async () => {
      const res = await client.get(`/v1/plants/projects`);
      return res.data.find((p: Project) => p.id === projectId);
    },
    enabled: !!projectId,
  });
}

export function useProjectParts(projectId: number) {
  return useQuery<Part[]>({
    queryKey: ['parts', projectId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/project/${projectId}`);
      return res.data;
    },
    enabled: !!projectId,
  });
}

export function usePartRevisions(partId: number) {
  return useQuery<PartRevision[]>({
    queryKey: ['part-revisions', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/revisions`);
      return res.data;
    },
    enabled: !!partId,
  });
}

export function useRevisionFiles(revisionId: number) {
  return useQuery<RevisionFile[]>({
    queryKey: ['revision-files', revisionId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/revisions/${revisionId}/files`);
      return res.data;
    },
    enabled: !!revisionId,
  });
}

export function useAssemblyFiles(partId: number) {
  return useQuery<AssemblyFileEntry[]>({
    queryKey: ['assembly-files', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/assembly-files`);
      return res.data;
    },
    enabled: !!partId,
  });
}

export function useChangelog(partId: number) {
  return useQuery<ChangelogEntry[]>({
    queryKey: ['part-changelog', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/changelog`);
      return res.data;
    },
    enabled: !!partId,
  });
}

export function useCatalogParts() {
  return useQuery<CatalogPart[]>({
    queryKey: ['catalog-parts'],
    queryFn: async () => {
      const res = await client.get('/v1/catalog-parts?is_active=true');
      return res.data;
    },
  });
}
```

- [ ] **Step 5: Create `frontend/src/hooks/queries/useSuppliers.ts` only if it does not exist**

Run: `test -f /home/nitrolinux/claude/plm2/frontend/src/hooks/queries/useSuppliers.ts && echo EXISTS || echo MISSING`

If `EXISTS`: leave it as is and check it exports `useSuppliers` and `SupplierOption` with the shapes below. If `MISSING`, create it with exactly this content (identical to the `feature/tool-dfm-archive` plan, so a later merge is an add/add of identical files):

```ts
/**
 * Supplier options for pickers (part supplier, toolmaker). Active suppliers only.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export interface SupplierOption {
  id: number;
  name: string;
}

export function useSuppliers() {
  return useQuery<SupplierOption[]>({
    queryKey: ['suppliers', false],
    queryFn: async () => (await client.get('/v1/suppliers')).data,
  });
}
```

- [ ] **Step 6: Point the page at the new modules**

In `frontend/src/pages/ProjectDetailPage.tsx`:

1. Delete these top-level declarations (they now live in the new modules): the `// Types` block with `CustomerNaming` and `CUSTOMER_NAMING_LABELS`, `interface Project`, `interface Part`, `CATEGORY_META`, `interface PartRevision`, `interface ContextMenu`, `interface TreeNode`, `useProject`, `useProjectParts`, `usePartRevisions`, `interface RevisionFile`, `useRevisionFiles`, `LOCKED_REVISION_STATUSES`, `interface AssemblyFileEntry`, `useAssemblyFiles`, `comparePartNodes`, `buildPartTree`, `typeColor`, `phaseColor`, `statusColor`, `interface ChangelogEntry`, `useChangelog`, `getDescendantIds`, `interface CatalogPart`, `useCatalogParts`, `interface SupplierOption`, `useSuppliers` (if the DFM branch already replaced the last two with an import, delete that import line instead).
2. Add after the existing imports:

```ts
import {
  CATEGORY_META, LOCKED_REVISION_STATUSES, buildPartTree, comparePartNodes, getDescendantIds,
  phaseColor, statusColor, typeColor, CUSTOMER_NAMING_LABELS,
  type ContextMenuState, type CustomerNaming, type Part, type RevisionFile, type TreeNode,
} from '../components/project/projectTypes';
import {
  useAssemblyFiles, useCatalogParts, useChangelog, usePartRevisions, useProject, useProjectParts, useRevisionFiles,
} from '../hooks/queries/useProjectDetail';
import { useSuppliers } from '../hooks/queries/useSuppliers';
```

3. In the existing `import { comparePartNumbers, stripProjectCode } from '../lib/partDisplay';` line drop `comparePartNumbers` (only the moved `comparePartNodes` used it; `noUnusedLocals` is on).
4. Rename the two remaining uses of the old `ContextMenu` interface to `ContextMenuState` (`menu: ContextMenu | null` in `ContextMenuComponent`'s props and `useState<ContextMenu | null>` in the page).
5. `RevisionFile` was exported from the page and is imported by `pages/PartDetail.tsx` and `components/parts/RevisionFilesGrouped.tsx`. Keep them compiling for now with a type re-export right under the imports: `export type { RevisionFile } from '../components/project/projectTypes';` (Task 2 removes it).

- [ ] **Step 7: Run the new tests and the page tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/hooks/queries/useProjectDetail.test.tsx src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass (22 page tests plus 7 new), tsc clean.

- [ ] **Step 8: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/project/projectTypes.ts frontend/src/components/project/projectTypes.test.ts \
  frontend/src/hooks/queries/useProjectDetail.ts frontend/src/hooks/queries/useProjectDetail.test.tsx \
  frontend/src/hooks/queries/useSuppliers.ts frontend/src/pages/ProjectDetailPage.tsx
git commit -F - <<'MSG'
refactor(project-page): shared types, tree helpers and queries in their own modules

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: Leaf components out of the page

Pure extraction. No behaviour change. `RevisionFileRow` and `CustomerNamingSelect` tests move next to their components.

**Files:**
- Create: `frontend/src/components/project/RevisionFileRow.tsx`, `RevisionFileRow.test.tsx`
- Create: `frontend/src/components/project/CustomerNamingSelect.tsx`, `CustomerNamingSelect.test.tsx` (moved from `pages/ProjectDetailPage.naming.test.tsx`)
- Create: `frontend/src/components/project/BomTreeSection.tsx`
- Create: `frontend/src/components/project/ChangelogModal.tsx`
- Create: `frontend/src/components/project/ProjectContextMenu.tsx`
- Create: `frontend/src/components/project/AddPartModal.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`, `frontend/src/pages/ProjectDetailPage.files.test.tsx`
- Modify: `frontend/src/components/parts/RevisionFilesGrouped.tsx:3`, `frontend/src/pages/PartDetail.tsx:24`
- Delete: `frontend/src/pages/ProjectDetailPage.naming.test.tsx`

**Interfaces:**
- Consumes: Task 1 modules.
- Produces: `export function RevisionFileRow({ file, isViewing, locked, onView?, onOpen? })` in `RevisionFileRow.tsx`; `export function CustomerNamingSelect({ projectId, value })`; `export function BomTreeSection({ partId, revisionId, revisionName?, onOpenPart })`; `export default function ChangelogModal({ partId, onClose })`; `export default function ProjectContextMenu({ menu, onClose, onOpenDetails, onViewChangelog })`; `export default function AddPartModal({ projectId, parts, isOpen, onClose })`.

- [ ] **Step 1: Move the tests first (they fail until the modules exist)**

Run:

```bash
cd /home/nitrolinux/claude/plm2/frontend
git mv src/pages/ProjectDetailPage.naming.test.tsx src/components/project/CustomerNamingSelect.test.tsx
```

In `src/components/project/CustomerNamingSelect.test.tsx` change the import and mock path lines to:

```tsx
import { CustomerNamingSelect } from './CustomerNamingSelect'
```

```tsx
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
```

Create `src/components/project/RevisionFileRow.test.tsx` (the `RevisionFileRow provenance` block from `ProjectDetailPage.files.test.tsx`, unchanged apart from paths):

```tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RevisionFileRow } from './RevisionFileRow'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const file = (over: Record<string, unknown> = {}) => ({
  id: 3, revision_id: 9, filename: 'housing.step', file_type: 'cad_native',
  mime_type: 'application/step', file_size: 2_000_000, cad_format: 'step',
  has_viewer: true, uploaded_at: '2026-07-01T00:00:00', ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('RevisionFileRow provenance', () => {
  afterEach(cleanup)

  it('names who uploaded the revision file and when', () => {
    wrap(<RevisionFileRow file={file({ uploaded_by: 5, uploaded_by_name: 'Eva Eng' })}
      isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent)
      .toContain(`Eva Eng · ${new Date('2026-07-01T00:00:00').toLocaleDateString()}`)
  })

  it('shows the date alone for a file with no recorded uploader', () => {
    wrap(<RevisionFileRow file={file()} isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent).not.toContain('·')
  })

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

  it('shows Open when an onOpen handler is given', () => {
    const onOpen = vi.fn()
    wrap(<RevisionFileRow file={file({ file_type: 'drawing', mime_type: 'application/pdf', filename: 'd.pdf' })} isViewing={false} locked={false} onOpen={onOpen} />)
    fireEvent.click(screen.getByText('Open'))
    expect(onOpen).toHaveBeenCalled()
  })
})
```

In `src/pages/ProjectDetailPage.files.test.tsx`: delete the whole `describe('RevisionFileRow provenance', ...)` block, the `file` and `wrap` helpers above it, and change the import line to `import ProjectDetailPage from './ProjectDetailPage'`.

- [ ] **Step 2: Run the moved tests to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project/CustomerNamingSelect.test.tsx src/components/project/RevisionFileRow.test.tsx`
Expected: FAIL, "Failed to resolve import './CustomerNamingSelect'" and "'./RevisionFileRow'".

- [ ] **Step 3: Create the six component files by moving code out of the page**

Each file below gets the header shown, then the named function body moved verbatim from `ProjectDetailPage.tsx`, with two mechanical edits applied everywhere in the moved code:
- `onError: (error: any) => { const msg = error.response?.data?.detail || 'X'; toast.error(msg); }` and `onError: (error: any) => { toast.error(error.response?.data?.detail || 'X'); }` become `onError: (error: unknown) => { toast.error(apiErrorMessage(error, 'X')); }` (same fallback text `X`). This clears the four `no-explicit-any` lint errors.
- In `AddPartModal`, `const payload: any = {` becomes `const payload: Record<string, unknown> = {`.

`frontend/src/components/project/RevisionFileRow.tsx`:

```tsx
/**
 * One file of a revision: type chip, name, kind and note, provenance, and the
 * view / open / download / delete actions.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client, { API_BASE_URL } from '../../api/client';
import { UploadedBy } from '../common/UploadedBy';
import { apiErrorMessage } from '../../lib/apiError';
import type { RevisionFile } from './projectTypes';
```
Then move `function fileTypeColor` (page `// File type badge colors`, lines 952-962) and `export function RevisionFileRow` (page lines 998-1086) verbatim.

`frontend/src/components/project/CustomerNamingSelect.tsx`:

```tsx
/** Per-project choice of the customer's file naming convention (used by the guided upload). */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { CUSTOMER_NAMING_LABELS, type CustomerNaming } from './projectTypes';
```
Then move `export function CustomerNamingSelect` (page lines 964-996) verbatim.

`frontend/src/components/project/BomTreeSection.tsx`:

```tsx
/** Multi-level BOM of the selected revision, plus where the part is used. */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import BomTree, { type BomNode } from '../parts/BomTree';
import { revisionLabel } from '../parts/RevisionBadge';
```
Then move `interface WhereUsedEntry`, `function flattenUsedIn` and `export function BomTreeSection` (page lines 239-288) verbatim.

`frontend/src/components/project/ChangelogModal.tsx`:

```tsx
/** Changelog of one part in a modal (the context menu's "View Changelog"). */
import { useChangelog } from '../../hooks/queries/useProjectDetail';
```
Then move `function ChangelogModal` (page lines 327-368) verbatim and prefix it with `export default`.

`frontend/src/components/project/ProjectContextMenu.tsx`:

```tsx
/** Right-click menu on an item row. */
import { useEffect, useRef } from 'react';
import type { ContextMenuState } from './projectTypes';
```
Then move `function ContextMenuComponent` (page lines 370-433) verbatim, rename it to `ProjectContextMenu`, prefix `export default`; its `menu` prop type is `ContextMenuState | null`.

`frontend/src/components/project/AddPartModal.tsx`:

```tsx
/** "+ Add Part" dialog: any controlled item category, optional parent sub-assembly. */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../../api/client';
import { useCatalogParts } from '../../hooks/queries/useProjectDetail';
import { useSuppliers } from '../../hooks/queries/useSuppliers';
import type { Part } from './projectTypes';
```
Then move `function AddPartModal` (page lines 678-950) verbatim with `export default`, applying the `payload` type edit above.

- [ ] **Step 4: Update the page and the two importers**

In `ProjectDetailPage.tsx`: delete the moved functions (`WhereUsedEntry`, `flattenUsedIn`, `BomTreeSection`, `ChangelogModal`, `ContextMenuComponent`, `AddPartModal`, `fileTypeColor`, `CustomerNamingSelect`, `RevisionFileRow`) and the `export type { RevisionFile }` line from Task 1; replace `<ContextMenuComponent` with `<ProjectContextMenu`; add:

```ts
import { BomTreeSection } from '../components/project/BomTreeSection';
import { CustomerNamingSelect } from '../components/project/CustomerNamingSelect';
import ChangelogModal from '../components/project/ChangelogModal';
import ProjectContextMenu from '../components/project/ProjectContextMenu';
import AddPartModal from '../components/project/AddPartModal';
```

Remove imports the page no longer uses (`BomTree`, `UploadedBy`, `CUSTOMER_NAMING_LABELS`, `CustomerNaming`, `useCatalogParts`, `useChangelog`, `useSuppliers`, `useRef` only if unused; `tsc --noEmit` with `noUnusedLocals` tells you which).

In `frontend/src/components/parts/RevisionFilesGrouped.tsx` line 3:

```ts
import { RevisionFileRow } from '../project/RevisionFileRow';
import type { RevisionFile } from '../project/projectTypes';
```

In `frontend/src/pages/PartDetail.tsx` line 24:

```ts
import type { RevisionFile } from '../components/project/projectTypes';
```

- [ ] **Step 5: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/components/parts src/pages/ProjectDetailPage src/pages/PartDetail && npx tsc --noEmit`
Expected: all pass, tsc clean. The page test count drops by 7 (5 RevisionFileRow + 2 naming tests now run from `components/project`).

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add -A frontend/src/components/project frontend/src/pages/ProjectDetailPage.tsx \
  frontend/src/pages/ProjectDetailPage.files.test.tsx frontend/src/pages/ProjectDetailPage.naming.test.tsx \
  frontend/src/components/parts/RevisionFilesGrouped.tsx frontend/src/pages/PartDetail.tsx
git commit -F - <<'MSG'
refactor(project-page): file row, naming select, BOM tree, changelog, context menu and add-part dialog in their own files

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: Items list into `ItemsPane` and `ItemRow`

Pure extraction. No behaviour change. The page keeps the selection state; `ItemsPane` owns filter, drag state and the reparent mutation.

**Files:**
- Create: `frontend/src/components/project/ItemRow.tsx`
- Create: `frontend/src/components/project/ItemsPane.tsx`
- Create: `frontend/src/components/project/ItemsPane.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

**Interfaces:**
- Consumes: `buildPartTree`, `comparePartNodes`, `getDescendantIds`, `CATEGORY_META`, `typeColor`, `Part`, `TreeNode` (Task 1).
- Produces:

```ts
// ItemsPane.tsx
export interface ItemsPaneProps {
  projectId: number;
  projectCode: string;
  parts: Part[] | undefined;
  partsLoading: boolean;
  structure: ProjectStructure | undefined;
  paintByPartId: Map<number, PartPaintLayer>;
  paintedIds: Set<number>;
  paintedCount: number;
  selectedPartId: number | null;
  onSelect(partId: number): void;
  onOpenPart(partId: number): void;
  onPickRevision(partId: number, revisionId: number): void;
  onContextMenu(e: React.MouseEvent, partId: number): void;
}
export default function ItemsPane(props: ItemsPaneProps): JSX.Element
// ItemRow.tsx: export default function ItemRow(props) - same props as the old TreeNodeComponent
```

- [ ] **Step 1: Write the failing test**

`frontend/src/components/project/ItemsPane.test.tsx`:

```tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ItemsPane, { type ItemsPaneProps } from './ItemsPane'
import type { Part } from './projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../parts/AssemblyTreeList', () => ({ default: () => <div>assemblies</div> }))

const parts: Part[] = [
  { id: 1, part_number: '199401', name: '1994 TOOL Handle', part_type: 'purchased', item_category: 'tool', active_revision_id: null, parent_part_id: null },
  { id: 2, part_number: '20-1994-001-0', name: 'Handle LH', part_type: 'internal_mfg', item_category: 'article', active_revision_id: null, parent_part_id: null },
]

function mount(over: Partial<ItemsPaneProps> = {}) {
  const props: ItemsPaneProps = {
    projectId: 2, projectCode: '1994', parts, partsLoading: false, structure: { articles: [] },
    paintByPartId: new Map(), paintedIds: new Set(), paintedCount: 0, selectedPartId: null,
    onSelect: vi.fn(), onOpenPart: vi.fn(), onPickRevision: vi.fn(), onContextMenu: vi.fn(), ...over,
  }
  render(<QueryClientProvider client={new QueryClient()}><ItemsPane {...props} /></QueryClientProvider>)
  return props
}

describe('ItemsPane', () => {
  afterEach(cleanup)

  it('counts the items, filters by category and reports a row click', () => {
    const props = mount()
    expect(screen.getByText('Items (2)')).toBeTruthy()
    fireEvent.click(screen.getByText('🔧 Tool'))
    expect(screen.getByText('Items (1 of 2)')).toBeTruthy()
    fireEvent.click(screen.getByText('TOOL Handle'))
    expect(props.onSelect).toHaveBeenCalledWith(1)
  })

  it('shows the assembly tree for the assemblies filter', () => {
    mount()
    fireEvent.click(screen.getByText('🧩 Assemblies'))
    expect(screen.getByText('assemblies')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project/ItemsPane.test.tsx`
Expected: FAIL, "Failed to resolve import './ItemsPane'".

- [ ] **Step 3: Create `ItemRow.tsx` by moving `TreeNodeComponent`**

Header:

```tsx
/** One item row of the project list, its expand block and its nested children. */
import { useState } from 'react';
import ColourSwatch from '../paint/ColourSwatch';
import { revisionLabel } from '../parts/RevisionBadge';
import { stripProjectCode } from '../../lib/partDisplay';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import { CATEGORY_META, typeColor, type TreeNode } from './projectTypes';
```

Then move `function TreeNodeComponent` (page `// Tree Node Component`, lines 450-646) verbatim, renamed to `export default function ItemRow`, and change the recursive `<TreeNodeComponent` inside it to `<ItemRow`. In the comment above the expand block, replace the em dash in "are currently inert — kept as a" with a comma: "are currently inert, kept as a".

- [ ] **Step 4: Create `ItemsPane.tsx`**

```tsx
/**
 * ItemsPane - the project's items: category filter, the part tree, and
 * drag-to-restructure onto sub-assemblies.
 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import AssemblyTreeList from '../parts/AssemblyTreeList';
import { apiErrorMessage } from '../../lib/apiError';
import type { ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import ItemRow from './ItemRow';
import {
  CATEGORY_META, buildPartTree, comparePartNodes, getDescendantIds, type Part, type TreeNode,
} from './projectTypes';

export interface ItemsPaneProps {
  projectId: number;
  projectCode: string;
  parts: Part[] | undefined;
  partsLoading: boolean;
  structure: ProjectStructure | undefined;
  paintByPartId: Map<number, PartPaintLayer>;
  paintedIds: Set<number>;
  paintedCount: number;
  selectedPartId: number | null;
  onSelect(partId: number): void;
  onOpenPart(partId: number): void;
  onPickRevision(partId: number, revisionId: number): void;
  onContextMenu(e: React.MouseEvent, partId: number): void;
}

export default function ItemsPane({
  projectId, projectCode, parts, partsLoading, structure, paintByPartId, paintedIds, paintedCount,
  selectedPartId, onSelect, onOpenPart, onPickRevision, onContextMenu,
}: ItemsPaneProps) {
  const id = projectId;
  const queryClient = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);

  const reparentMutation = useMutation({
    mutationFn: async ({ partId, parentPartId }: { partId: number; parentPartId: number | null }) => {
      await client.put(`/v1/parts/${partId}`, { parent_part_id: parentPartId });
    },
    onSuccess: () => {
      toast.success('Part moved');
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
      queryClient.invalidateQueries({ queryKey: ['assembly-files'] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to move part'));
    },
  });

  const handleDropOnPart = (targetId: number) => {
    if (draggingPartId === null) return;
    const dragged = parts?.find((p) => p.id === draggingPartId);
    if (dragged?.parent_part_id === targetId) {
      setDraggingPartId(null);
      return; // already a child of the target
    }
    reparentMutation.mutate({ partId: draggingPartId, parentPartId: targetId });
    setDraggingPartId(null);
  };

  const invalidDropIds = draggingPartId !== null && parts ? getDescendantIds(parts, draggingPartId) : new Set<number>();

  const partTree = parts ? buildPartTree(parts) : [];
  const visibleNodes: TreeNode[] = categoryFilter === 'all' || categoryFilter === 'assemblies'
    ? partTree
    : (parts ?? [])
        .filter((p) =>
          categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter
        )
        .map((p) => ({ part: p, children: [] }))
        .sort(comparePartNodes);

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-1">
        Items ({visibleNodes.length}{categoryFilter !== 'all' ? ` of ${parts?.length ?? 0}` : ''})
      </h2>
      <p className="text-xs text-slate-500 mb-2">Drag a part onto a ★ sub-assembly to restructure</p>
      <div className="flex flex-wrap gap-1 mb-3">
        {[['all', 'All'], ...Object.entries(CATEGORY_META).map(([k, v]) => [k, `${v.icon} ${v.label}`]), ['assemblies', '🧩 Assemblies'], ['painted', `🎨 Painted (${paintedCount})`]].map(
          ([key, label]) => (
            <button
              key={key}
              onClick={() => setCategoryFilter(key)}
              className={`px-2 py-1 rounded text-xs font-medium transition ${
                categoryFilter === key
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {label}
            </button>
          )
        )}
      </div>
      {categoryFilter === 'assemblies' ? (
        <AssemblyTreeList projectId={Number(id)} selectedPartId={selectedPartId} onSelect={onOpenPart} />
      ) : partsLoading ? (
        <p className="text-slate-500 text-sm">Loading...</p>
      ) : (parts?.length ?? 0) === 0 ? (
        <p className="text-slate-500 text-sm">No parts yet</p>
      ) : (
        <div className="space-y-1">
          {visibleNodes.map((node) => (
            <ItemRow
              key={node.part.id}
              node={node}
              projectCode={projectCode}
              paintByPartId={paintByPartId}
              selectedPartId={selectedPartId}
              onSelect={onSelect}
              onContextMenu={onContextMenu}
              draggingPartId={draggingPartId}
              invalidDropIds={invalidDropIds}
              onDragStartPart={setDraggingPartId}
              onDragEndPart={() => setDraggingPartId(null)}
              onDropOnPart={handleDropOnPart}
              structure={structure}
              onSelectRevision={onPickRevision}
            />
          ))}
          {/* Top-level drop zone, visible while dragging a nested part */}
          {draggingPartId !== null &&
            parts?.find((p) => p.id === draggingPartId)?.parent_part_id != null && (
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setTopLevelDragOver(true);
                }}
                onDragLeave={() => setTopLevelDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setTopLevelDragOver(false);
                  if (draggingPartId !== null) {
                    reparentMutation.mutate({ partId: draggingPartId, parentPartId: null });
                    setDraggingPartId(null);
                  }
                }}
                className={`mt-2 px-3 py-3 rounded border-2 border-dashed text-center text-xs font-medium transition ${
                  topLevelDragOver
                    ? 'border-green-500 bg-green-900/30 text-green-300'
                    : 'border-slate-600 text-slate-400'
                }`}
              >
                Drop here to move to top level
              </div>
            )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Use it in the page**

In `ProjectDetailPage.tsx`:
1. Delete `TreeNodeComponent`, the `categoryFilter`, `draggingPartId` and `topLevelDragOver` states, `reparentMutation`, `handleDropOnPart`, `invalidDropIds`, `partTree` and `visibleNodes`.
2. Replace the whole `{/* Left: Parts Tree */}` column (`<div>` from the `Items (` heading to the end of the drop-zone block) with:

```tsx
        <ItemsPane
          projectId={id}
          projectCode={project.code}
          parts={parts}
          partsLoading={partsLoading}
          structure={structure}
          paintByPartId={paintByPartId}
          paintedIds={paintedIds}
          paintedCount={paintOverview?.length ?? 0}
          selectedPartId={selectedPartId}
          onSelect={setSelectedPartId}
          onOpenPart={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }}
          onPickRevision={(pid, rid) => { pendingRevisionRef.current = { partId: pid, revisionId: rid }; setSelectedPartId(pid); setSelectedRevisionId(rid); setViewingFileId(null); setOpenDocId(null); }}
          onContextMenu={handleContextMenu}
        />
```

3. Add `import ItemsPane from '../components/project/ItemsPane';` and drop now-unused imports (`AssemblyTreeList`, `ColourSwatch`, `stripProjectCode`, `comparePartNumbers`, `buildPartTree`, `comparePartNodes`, `getDescendantIds`, `TreeNode`).

- [ ] **Step 6: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass, tsc clean.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/project/ItemRow.tsx frontend/src/components/project/ItemsPane.tsx \
  frontend/src/components/project/ItemsPane.test.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -F - <<'MSG'
refactor(project-page): items list moves into ItemsPane and ItemRow

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: Selection hook, `DetailPane` and `ProjectHeaderBar`; the page becomes a shell

Pure extraction. No behaviour change. After this task the page holds data hooks, the selection hook, dialog flags and the layout.

**Files:**
- Create: `frontend/src/hooks/useArticleSelection.ts`
- Create: `frontend/src/hooks/useArticleSelection.test.tsx`
- Create: `frontend/src/components/project/DetailPane.tsx`
- Create: `frontend/src/components/project/ProjectHeaderBar.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (full rewrite below)

**Interfaces:**
- Consumes: `usePartRevisions` (Task 1), `Part`, `PartRevision`.
- Produces:

```ts
// hooks/useArticleSelection.ts
export interface ArticleSelection {
  partId: number | null;
  revisionId: number | null;
  viewingFileId: number | null;
  openDocId: number | null;
  partRevisions: PartRevision[] | undefined;
  selectPart(partId: number | null): void;      // raw select, the default-revision effect resets the document view on change
  openPart(partId: number | null): void;        // select and reset the document view now
  selectRevision(revisionId: number): void;     // select a revision of the current part, reset the document view
  pickRevision(partId: number, revisionId: number): void; // explicit jump that wins over the default revision
  setRevisionId(revisionId: number | null): void;
  setViewingFileId(fileId: number | null): void;
  setOpenDocId(fileId: number | null): void;
}
export function useArticleSelection(parts: Part[] | undefined, initialPartId?: number | null): ArticleSelection
// components/project/DetailPane.tsx (this task's shape; Task 11 changes the props)
export default function DetailPane(props: { projectId: number; project: Project; parts: Part[] | undefined; structure: ProjectStructure | undefined; sel: ArticleSelection; onShowChangelog(partId: number): void }): JSX.Element | null
// components/project/ProjectHeaderBar.tsx (this task's shape; Task 7 changes it)
export default function ProjectHeaderBar(props: { project: Project; onStartChange(): void; onAddPart(): void }): JSX.Element
```

- [ ] **Step 1: Write the failing hook test**

`frontend/src/hooks/useArticleSelection.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useArticleSelection } from './useArticleSelection'
import type { Part } from '../components/project/projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const parts: Part[] = [
  { id: 5, part_number: '20-1', name: 'Cover', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null },
  { id: 6, part_number: '20-2', name: 'Lid', part_type: 'internal_mfg', active_revision_id: null, item_category: 'article', parent_part_id: null },
]
const rev = (id: number, part_id: number, revision_name: string) =>
  ({ id, part_id, revision_name, phase: 'review', status: 'draft', created_at: '2026-05-28' })

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
)

describe('useArticleSelection', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: [rev(9, 5, 'E1'), rev(10, 5, 'E1.1')] })
      if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: [rev(20, 6, 'E1'), rev(21, 6, 'E2')] })
      return Promise.resolve({ data: [] })
    })
  })

  it('selects the active revision once the revisions load', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, 5), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(9))
  })

  it('falls back to the latest revision when the part has no active one', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, 6), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(21))
  })

  it('lets an explicit pick win over the active revision', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, null), { wrapper })
    act(() => result.current.pickRevision(5, 10))
    await waitFor(() => expect(result.current.partRevisions?.length).toBe(2))
    expect(result.current.revisionId).toBe(10)
  })

  it('openPart resets the document view even for the same part', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, 5), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(9))
    act(() => { result.current.setViewingFileId(3); result.current.setOpenDocId(4) })
    expect(result.current.viewingFileId).toBe(3)
    act(() => result.current.openPart(5))
    expect(result.current.viewingFileId).toBeNull()
    expect(result.current.openDocId).toBeNull()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/hooks/useArticleSelection.test.tsx`
Expected: FAIL, "Failed to resolve import './useArticleSelection'".

- [ ] **Step 3: Create `frontend/src/hooks/useArticleSelection.ts`**

```ts
/**
 * Which item, revision and document the project detail shows.
 *
 * Shared by the project page and the pop-out detail window so both apply the
 * same revision rules: an explicit pick wins, otherwise the active revision,
 * otherwise the latest one.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { usePartRevisions } from './queries/useProjectDetail';
import type { Part, PartRevision } from '../components/project/projectTypes';

export interface ArticleSelection {
  partId: number | null;
  revisionId: number | null;
  viewingFileId: number | null;
  openDocId: number | null;
  partRevisions: PartRevision[] | undefined;
  /** Select an item. The document view resets when the item actually changes. */
  selectPart(partId: number | null): void;
  /** Select an item and reset the document view right away. */
  openPart(partId: number | null): void;
  /** Select a revision of the current item and reset the document view. */
  selectRevision(revisionId: number): void;
  /** Jump to a given revision of a given item (tree revision chips, pop-out sync). */
  pickRevision(partId: number, revisionId: number): void;
  setRevisionId(revisionId: number | null): void;
  setViewingFileId(fileId: number | null): void;
  setOpenDocId(fileId: number | null): void;
}

export function useArticleSelection(parts: Part[] | undefined, initialPartId: number | null = null): ArticleSelection {
  const [partId, setPartId] = useState<number | null>(initialPartId);
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [viewingFileId, setViewingFileId] = useState<number | null>(null);
  const [openDocId, setOpenDocId] = useState<number | null>(null);
  const { data: partRevisions } = usePartRevisions(partId || 0);

  // An explicit revision pick (a revision chip in the tree, a pop-out sync)
  // wins over the default selection below, which otherwise resets to the
  // active or latest revision whenever partId changes.
  const pendingRevisionRef = useRef<{ partId: number; revisionId: number } | null>(null);

  useEffect(() => {
    setViewingFileId(null);
    setOpenDocId(null);
    // A pending pick only guards the part change it was made for. Once partId
    // has moved on, drop it, or a later re-select of the original part (with
    // revisions already cached) would wrongly reapply the stale pick.
    if (pendingRevisionRef.current && pendingRevisionRef.current.partId !== partId) {
      pendingRevisionRef.current = null;
    }
    if (pendingRevisionRef.current?.partId === partId) {
      const pending = pendingRevisionRef.current;
      if (partRevisions?.some((r) => r.id === pending.revisionId)) {
        pendingRevisionRef.current = null;
        setRevisionId(pending.revisionId);
        return;
      }
      if (!partRevisions || partRevisions.length === 0) {
        // Revisions for this part have not loaded yet: wait for the next run
        // instead of falling through to the default selection.
        return;
      }
      pendingRevisionRef.current = null;
    }
    if (!partRevisions || partRevisions.length === 0) {
      setRevisionId(null);
      return;
    }
    const activeId = parts?.find((p) => p.id === partId)?.active_revision_id;
    const fallback = partRevisions[partRevisions.length - 1].id;
    setRevisionId(partRevisions.some((r) => r.id === activeId) ? activeId! : fallback);
  }, [partId, partRevisions, parts]);

  const openPart = useCallback((id: number | null) => {
    setPartId(id);
    setViewingFileId(null);
    setOpenDocId(null);
  }, []);

  const selectRevision = useCallback((id: number) => {
    setRevisionId(id);
    setViewingFileId(null);
    setOpenDocId(null);
  }, []);

  const pickRevision = useCallback((pid: number, rid: number) => {
    pendingRevisionRef.current = { partId: pid, revisionId: rid };
    setPartId(pid);
    setRevisionId(rid);
    setViewingFileId(null);
    setOpenDocId(null);
  }, []);

  return {
    partId, revisionId, viewingFileId, openDocId, partRevisions,
    selectPart: setPartId, openPart, selectRevision, pickRevision,
    setRevisionId, setViewingFileId, setOpenDocId,
  };
}
```

- [ ] **Step 4: Run the hook test**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/hooks/useArticleSelection.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Create `ProjectHeaderBar.tsx` (today's header, unchanged)**

```tsx
/** Project page header. Task 7 turns it into the one-line header with status chips. */
import { useNavigate } from 'react-router-dom';
import MilestoneStrip from '../MilestoneStrip';
import StartChangeButton from '../changes/StartChangeButton';
import { CustomerNamingSelect } from './CustomerNamingSelect';
import type { Project } from './projectTypes';

export default function ProjectHeaderBar({ project, onStartChange, onAddPart }: {
  project: Project;
  onStartChange(): void;
  onAddPart(): void;
}) {
  const navigate = useNavigate();
  return (
    <div className="mb-6 flex items-center justify-between">
      <div>
        <button
          onClick={() => navigate('/projects')}
          className="text-sm text-blue-400 hover:text-blue-300 mb-3"
        >
          ← Back
        </button>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-100">
          {project.name} <span className="text-slate-400 text-sm">({project.code})</span>
        </h1>
        <div className="mt-2">
          <MilestoneStrip projectId={project.id} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <CustomerNamingSelect projectId={project.id} value={project.customer_naming ?? null} />
        <StartChangeButton label="Start change request"
          onClick={onStartChange}
          className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
        <button
          onClick={onAddPart}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
        >
          + Add Part
        </button>
      </div>
    </div>
  );
}
```

Note: the old header passed the route id (`id`) to `MilestoneStrip` and `CustomerNamingSelect`; `project.id` is the same number because `useProject` finds the project by that id.

- [ ] **Step 6: Create `DetailPane.tsx` by moving the right column**

Header and top of the component (write this out in full):

```tsx
/**
 * DetailPane - the selected item: info card, revision files and document
 * pane, relations, workflow, PPAP and BOM. Task 11 turns it into tabs.
 */
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client, { API_BASE_URL } from '../../api/client';
import Viewer3D from '../Viewer3D';
import UploadDialog from '../parts/UploadDialog';
import RevisionWorkflowSection from '../workflows/RevisionWorkflowSection';
import PartBOMSection from '../PartBOMSection';
import PartRelationsSection from '../PartRelationsSection';
import ProcessFlowSection from '../ProcessFlowSection';
import PPAPSection from '../PPAPSection';
import CustomerDataDialog, { type CustomerDataInput } from '../parts/CustomerDataDialog';
import CustomerPackageDialog from '../parts/CustomerPackageDialog';
import { revisionLabel } from '../parts/RevisionBadge';
import RevisionStrip from '../parts/RevisionStrip';
import DocumentPane, { type PaneDocument, type MirrorNotice } from '../parts/DocumentPane';
import RevisionFilesGrouped, { docKindFor } from '../parts/RevisionFilesGrouped';
import { stripProjectCode } from '../../lib/partDisplay';
import { apiErrorMessage } from '../../lib/apiError';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useAssemblyFiles, useRevisionFiles } from '../../hooks/queries/useProjectDetail';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { BomTreeSection } from './BomTreeSection';
import {
  CATEGORY_META, LOCKED_REVISION_STATUSES, phaseColor, statusColor, typeColor, type Part, type Project,
} from './projectTypes';

interface DetailPaneProps {
  projectId: number;
  project: Project;
  parts: Part[] | undefined;
  structure: ProjectStructure | undefined;
  sel: ArticleSelection;
  onShowChangelog(partId: number): void;
}

export default function DetailPane({ projectId, project, parts, structure, sel, onShowChangelog }: DetailPaneProps) {
  const id = projectId;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const selectedPartId = sel.partId;
  const selectedRevisionId = sel.revisionId;
  const viewingFileId = sel.viewingFileId;
  const openDocId = sel.openDocId;
  const partRevisions = sel.partRevisions;

  const { data: revisionFiles } = useRevisionFiles(selectedRevisionId || 0);
  const article = articleOf(structure, selectedPartId);
  const mirrorSource = article?.mirror_of ? articleOf(structure, article.mirror_of.part_id) : undefined;
  const mirrorFiles = useRevisionFiles(mirrorSource?.active_revision_id ?? 0);

  const isSubAssembly = parts?.find((p) => p.id === selectedPartId)?.part_type === 'sub_assembly';
  const { data: assemblyFiles } = useAssemblyFiles(isSubAssembly && selectedPartId ? selectedPartId : 0);
  const assemblyAvailable = isSubAssembly && (assemblyFiles?.length ?? 0) > 1;
  const assemblyActive = assemblyAvailable && viewingFileId === null;
  const assemblyModels = useMemo(
    () =>
      assemblyFiles?.map((f) => ({
        id: f.file_id,
        url: `${API_BASE_URL}/v1/parts/revision-files/${f.file_id}/viewer`,
        label: f.uploaded_by_name
          ? `${f.part_name} (${f.revision_name}) · ${f.uploaded_by_name}`
          : `${f.part_name} (${f.revision_name})`,
      })),
    [assemblyFiles]
  );

  const [showCustomerData, setShowCustomerData] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[] | null>(null);
  const [uploadDrag, setUploadDrag] = useState(false);
```

Then move, in this order, from the page into the component body:
1. `markCalibratedMutation` (page `const markCalibratedMutation = useMutation({`), `customerDataMutation` and `proposalMutation`, applying the `apiErrorMessage` edit from Task 2 to `markCalibratedMutation`'s `onError`.
2. The derived values from `const selectedPart = parts?.find(...)` through `const paneViewerUrl = ...`, except `partTree` and `visibleNodes` (already gone in Task 3).
3. `if (!selectedPart) return null;`
4. `return (` followed by the inner block of the old right column: the `<div onClick={(e) => e.stopPropagation()} className="space-y-4">` element and everything inside it up to its matching `</div>` (the old `{selectedPart ? ( ... ) : null}` wrapper is gone; the early return above replaces it), then `);` and `}`.

Apply these renames inside everything moved in this step (the left side is the page's name, the right side is what it becomes):

| Page code | DetailPane code |
|---|---|
| `setSelectedPartId(x); setViewingFileId(null); setOpenDocId(null);` | `sel.openPart(x);` |
| `setSelectedPartId` (any other use, including `onSelectPart={setSelectedPartId}`) | `sel.selectPart` |
| `setSelectedRevisionId(revId); setViewingFileId(null); setOpenDocId(null);` | `sel.selectRevision(revId);` |
| `setSelectedRevisionId` (other uses: proposal `onSuccess`, upload `onClose` / `onDone`) | `sel.setRevisionId` |
| `setViewingFileId` | `sel.setViewingFileId` |
| `setOpenDocId` | `sel.setOpenDocId` |
| `setChangelogPartId(selectedPart.id)` | `onShowChangelog(selectedPart.id)` |
| `project?.code`, `project?.customer_naming` | `project.code`, `project.customer_naming` |

`id` keeps meaning the project id through the `const id = projectId;` line above, so the `['parts', id]` / `['project-structure', id]` invalidations move unchanged. In the gauge line, the copy `' — OVERDUE'` stays for now (Task 10 rewrites the header).

- [ ] **Step 7: Rewrite `frontend/src/pages/ProjectDetailPage.tsx` as the shell**

```tsx
/**
 * ProjectDetailPage - the project work surface: header, items list and the
 * selected item's detail. Data hooks and selection state live here; the
 * panes live in components/project.
 */
import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import ProjectLessonsSection from '../components/ProjectLessonsSection';
import ProjectSepSection from '../components/ProjectSepSection';
import ProjectChangesSection from '../components/ProjectChangesSection';
import ProjectPaintSection from '../components/paint/ProjectPaintSection';
import StartChangeModal from '../components/changes/StartChangeModal';
import { projectPaintOverview } from '../api/paints';
import type { PartPaintLayer } from '../types/paint';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useProject, useProjectParts } from '../hooks/queries/useProjectDetail';
import { useArticleSelection } from '../hooks/useArticleSelection';
import ProjectHeaderBar from '../components/project/ProjectHeaderBar';
import ItemsPane from '../components/project/ItemsPane';
import DetailPane from '../components/project/DetailPane';
import ProjectContextMenu from '../components/project/ProjectContextMenu';
import ChangelogModal from '../components/project/ChangelogModal';
import AddPartModal from '../components/project/AddPartModal';
import type { ContextMenuState } from '../components/project/projectTypes';

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const navigate = useNavigate();

  const [searchParams] = useSearchParams();
  const initialPartId = searchParams.get('part');

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: structure } = useProjectStructure(id);
  const sel = useArticleSelection(parts, initialPartId ? parseInt(initialPartId, 10) : null);
  const { selectPart, openPart, pickRevision } = sel;

  // Follow ?part= deep links from global search while already on the page
  useEffect(() => {
    if (initialPartId) selectPart(parseInt(initialPartId, 10));
  }, [initialPartId, selectPart]);

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showStartChange, setShowStartChange] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);

  const { data: paintOverview } = useQuery({
    queryKey: ['project-paint-overview', id],
    queryFn: () => projectPaintOverview(id),
    enabled: !!id,
  });
  // Top layer (layer_order 1) per painted part, for the swatch on the item row.
  const paintByPartId = useMemo(() => {
    const map = new Map<number, PartPaintLayer>();
    for (const part of paintOverview ?? []) {
      const top = part.layers.find((l) => l.layer_order === 1) ?? part.layers[0];
      if (top) map.set(part.part_id, top);
    }
    return map;
  }, [paintOverview]);
  // Every part that requires paint, layer or not: the Painted chip counts
  // these, so the filter must select the same set (a part marked required
  // with no layer yet was counted but filtered out, 2026-09-21).
  const paintedIds = useMemo(
    () => new Set((paintOverview ?? []).map((part) => part.part_id)),
    [paintOverview],
  );

  if (projectLoading) {
    return <div className="p-6 text-slate-400">Loading project...</div>;
  }

  if (!project) {
    return (
      <div className="p-6 text-center">
        <p className="text-red-400 mb-4">Project not found</p>
        <button onClick={() => navigate('/projects')} className="text-blue-400 hover:text-blue-300">
          Back to projects
        </button>
      </div>
    );
  }

  const handleContextMenu = (e: React.MouseEvent, partId: number) => {
    e.preventDefault();
    setContextMenu({ partId, x: e.clientX, y: e.clientY });
  };

  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <ProjectHeaderBar
        project={project}
        onStartChange={() => setShowStartChange(true)}
        onAddPart={() => setShowAddModal(true)}
      />

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <ProjectSepSection projectId={id} />

      <ProjectChangesSection projectId={id} />

      <ProjectPaintSection projectId={id} />

      <ProjectLessonsSection projectId={id} />

      {/* Two-column layout */}
      <div className="grid grid-cols-3 gap-6">
        <ItemsPane
          projectId={id}
          projectCode={project.code}
          parts={parts}
          partsLoading={partsLoading}
          structure={structure}
          paintByPartId={paintByPartId}
          paintedIds={paintedIds}
          paintedCount={paintOverview?.length ?? 0}
          selectedPartId={sel.partId}
          onSelect={selectPart}
          onOpenPart={openPart}
          onPickRevision={pickRevision}
          onContextMenu={handleContextMenu}
        />

        {/* Right: Part Detail */}
        <div className="col-span-2 space-y-4 min-h-96" onClick={() => selectPart(null)}>
          <DetailPane
            projectId={id}
            project={project}
            parts={parts}
            structure={structure}
            sel={sel}
            onShowChangelog={setChangelogPartId}
          />
        </div>
      </div>

      <ProjectContextMenu
        menu={contextMenu}
        onClose={() => setContextMenu(null)}
        onOpenDetails={(partId) => navigate(`/parts/${partId}`)}
        onViewChangelog={(partId) => setChangelogPartId(partId)}
      />

      {changelogPartId && <ChangelogModal partId={changelogPartId} onClose={() => setChangelogPartId(null)} />}

      <AddPartModal projectId={id} parts={parts} isOpen={showAddModal} onClose={() => setShowAddModal(false)} />
    </div>
  );
}
```

- [ ] **Step 8: Run all page and project tests, tsc and lint**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages src/components/project src/hooks && npx tsc --noEmit && npx eslint src/components/project src/hooks src/pages/ProjectDetailPage.tsx --max-warnings 0`
Expected: all tests pass (the article race-guard test `a pending revision pick abandoned by switching parts...` is the key one), tsc clean, eslint clean (the 5 baseline problems are gone).

- [ ] **Step 9: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/hooks/useArticleSelection.ts frontend/src/hooks/useArticleSelection.test.tsx \
  frontend/src/components/project/DetailPane.tsx frontend/src/components/project/ProjectHeaderBar.tsx \
  frontend/src/pages/ProjectDetailPage.tsx
git commit -F - <<'MSG'
refactor(project-page): selection hook, DetailPane and header bar; page is a layout shell

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: Safe storage helper and the sidebar icon rail on project pages

**Files:**
- Create: `frontend/src/lib/safeStorage.ts`
- Create: `frontend/src/lib/safeStorage.test.ts`
- Modify: `frontend/src/components/layout/Sidebar.tsx` (full replacement below)
- Modify: `frontend/src/components/layout/Sidebar.test.tsx` (append a describe block)

**Interfaces:**
- Produces (`lib/safeStorage.ts`): `readStored(key: string): string | null`, `writeStored(key: string, value: string): void`, `readStoredNumber(key: string, fallback: number, min: number, max: number): number`. None of them ever throws.
- Storage key: `plm2.sidebar.projectRail` with values `'collapsed' | 'expanded'`.
- Sidebar DOM contract used by tests: `<aside data-testid="sidebar" data-collapsed="true|false">`; collapsed nav buttons carry `title` and `aria-label` = the item label.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/safeStorage.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readStored, readStoredNumber, writeStored } from './safeStorage'

describe('safeStorage', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('round-trips a value', () => {
    writeStored('k', 'v')
    expect(readStored('k')).toBe('v')
  })

  it('returns null and swallows the error when reading throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    expect(readStored('k')).toBeNull()
  })

  it('swallows the error when writing throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(() => writeStored('k', 'v')).not.toThrow()
  })

  it('reads numbers with a fallback for garbage and clamps the range', () => {
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(420)
    localStorage.setItem('w', 'abc')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(420)
    localStorage.setItem('w', '99999')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(1600)
    localStorage.setItem('w', '-5')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(280)
    localStorage.setItem('w', '512.6')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(513)
  })
})
```

Append to `frontend/src/components/layout/Sidebar.test.tsx` (it already mocks the client, `changesApi`, `AuthContext` and `ActsAsSwitch`; add `fireEvent` to the `@testing-library/react` import):

```tsx
describe('Sidebar rail on project pages', () => {
  const RAIL_KEY = 'plm2.sidebar.projectRail'
  const wrapAt = (path: string) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}><Sidebar /></MemoryRouter>
      </QueryClientProvider>
    )
  }
  const spies: { mockRestore(): void }[] = []

  beforeEach(() => {
    localStorage.clear()
    authMock.current = { role: 'engineer', username: 'tester', logout: vi.fn() }
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
  })
  afterEach(() => {
    cleanup()
    while (spies.length) spies.pop()!.mockRestore()
  })

  it('starts as a collapsed 48 px rail with hover labels on a project page', async () => {
    wrapAt('/projects/2')
    const aside = await screen.findByTestId('sidebar')
    expect(aside.getAttribute('data-collapsed')).toBe('true')
    expect(aside.className).toContain('w-12')
    expect(screen.queryByText('Dashboard')).toBeNull()
    expect(screen.getByTitle('Dashboard')).toBeTruthy()
  })

  it('stays expanded on other pages', async () => {
    wrapAt('/dashboard')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('false')
    expect(screen.getByText('Dashboard')).toBeTruthy()
  })

  it('remembers an expanded rail for the next project page', async () => {
    wrapAt('/projects/2')
    fireEvent.click(await screen.findByTitle('Expand'))
    expect(screen.getByText('Dashboard')).toBeTruthy()
    expect(localStorage.getItem(RAIL_KEY)).toBe('expanded')
    cleanup()
    wrapAt('/projects/7')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('false')
  })

  it('does not store a toggle made outside project pages', async () => {
    wrapAt('/dashboard')
    fireEvent.click(await screen.findByTitle('Collapse'))
    expect(localStorage.getItem(RAIL_KEY)).toBeNull()
  })

  it('falls back to the collapsed rail and keeps toggling when storage throws', async () => {
    spies.push(vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') }))
    spies.push(vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') }))
    wrapAt('/projects/2')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('true')
    fireEvent.click(screen.getByTitle('Expand'))
    expect(screen.getByTestId('sidebar').getAttribute('data-collapsed')).toBe('false')
  })

  it('treats a garbage stored value as the default', async () => {
    localStorage.setItem(RAIL_KEY, '{oops')
    wrapAt('/projects/2')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('true')
  })
})
```

Do not use `vi.restoreAllMocks()` in `Sidebar.test.tsx`: it would also wipe the `changesApi.myTasks` mock set up by the module factory. The spies are restored one by one above.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/lib/safeStorage.test.ts src/components/layout/Sidebar.test.tsx`
Expected: FAIL, "Failed to resolve import './safeStorage'"; the new Sidebar tests fail on `findByTestId('sidebar')`.

- [ ] **Step 3: Create `frontend/src/lib/safeStorage.ts`**

```ts
/**
 * localStorage that never throws. Private windows, blocked site data and full
 * quotas make the Storage API throw; a remembered layout choice is a
 * convenience, so every failure falls back to the caller's default.
 */

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable: the in-memory state still applies for this visit.
  }
}

/** A stored number clamped to [min, max]; the fallback when missing or not a number. */
export function readStoredNumber(key: string, fallback: number, min: number, max: number): number {
  const raw = readStored(key);
  const n = raw === null || raw.trim() === '' ? NaN : Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.round(Math.min(max, Math.max(min, n)));
}
```

- [ ] **Step 4: Replace `frontend/src/components/layout/Sidebar.tsx`**

```tsx
/**
 * Sidebar - Main navigation component with collapse/expand.
 *
 * On a project page it starts as a 48 px icon rail so the items list and the
 * detail get the width; the choice made there is remembered per browser.
 * Everywhere else it starts expanded, as before, and is not remembered.
 */

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import SearchBox from '../SearchBox';
import NotificationBell from '../NotificationBell';
import { useOpenTaskCount } from '../../hooks/queries/useOpenTaskCount';
import { readStored, writeStored } from '../../lib/safeStorage';
import ActsAsSwitch from './ActsAsSwitch';

const RAIL_KEY = 'plm2.sidebar.projectRail';

function isProjectPage(path: string): boolean {
  return /^\/projects\/\d+(\/|$)/.test(path);
}

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, username, role } = useAuth();
  const onProjectPage = isProjectPage(location.pathname);
  // Anything but an explicit "expanded" (missing, garbage, unreadable) means the rail.
  const [railCollapsed, setRailCollapsed] = useState(() => readStored(RAIL_KEY) !== 'expanded');
  const [pageCollapsed, setPageCollapsed] = useState(false);
  const isCollapsed = onProjectPage ? railCollapsed : pageCollapsed;

  const toggleCollapsed = () => {
    if (onProjectPage) {
      const next = !railCollapsed;
      setRailCollapsed(next);
      writeStored(RAIL_KEY, next ? 'collapsed' : 'expanded');
    } else {
      setPageCollapsed(!pageCollapsed);
    }
  };

  // Workflow tasks + change tasks: whatever My Tasks would show.
  const openTasks = useOpenTaskCount();

  const dailyItems = [
    { path: '/dashboard', label: 'Dashboard', icon: '🏠' },
    { path: '/projects', label: 'Projects', icon: '📁' },
    { path: '/catalog', label: 'Purchased Parts', icon: '🛒' },
    { path: '/paints', label: 'Paints', icon: '🎨' },
    { path: '/suppliers', label: 'Suppliers', icon: '🏭' },
    { path: '/lessons', label: 'Lessons Learned', icon: '📘' },
    { path: '/changes', label: 'Changes', icon: '🔄' },
    { path: '/process-map', label: 'Process Flow', icon: '🗺️' },
    { path: '/pnl', label: 'P&L', icon: '💰' },
    { path: '/reports', label: 'Reports', icon: '📊' },
    { path: '/my-tasks', label: 'My Tasks', icon: '✅' },
  ];

  const setupItems = [
    { path: '/workflows', label: 'Workflows', icon: '⚙️' },
  ];

  const showSetup = role === 'admin' || role === 'engineer';

  const isActive = (path: string) => location.pathname === path;

  const renderNavItem = (item: { path: string; label: string; icon: string }) => {
    const active = isActive(item.path);
    return (
      <button
        key={item.path}
        onClick={() => navigate(item.path)}
        aria-current={active ? 'page' : undefined}
        aria-label={isCollapsed ? item.label : undefined}
        className={`relative w-full text-left py-2.5 rounded-md text-sm font-medium ${
          isCollapsed ? 'justify-center px-0' : 'px-3'
        } flex items-center gap-3 ${
          active
            ? 'bg-sky-500/10 text-sky-300'
            : 'text-slate-400 hover:bg-slate-700/60 hover:text-slate-200 hover:translate-x-0.5'
        }`}
        title={isCollapsed ? item.label : ''}
      >
        {active && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 rounded-full bg-sky-400" />
        )}
        <span className={`text-base flex-shrink-0 ${active ? '' : 'opacity-80'}`}>{item.icon}</span>
        {!isCollapsed && <span className="flex-1">{item.label}</span>}
        {item.path === '/my-tasks' && openTasks > 0 && (
          <span className={isCollapsed
            ? 'absolute top-0.5 right-0.5 min-w-[1rem] px-1 rounded bg-amber-500 text-slate-900 text-[10px] leading-4 font-bold text-center'
            : 'px-1.5 py-0.5 rounded-md bg-amber-500 text-slate-900 text-xs font-bold flex-shrink-0'}>
            {openTasks}
          </span>
        )}
      </button>
    );
  };

  return (
    <aside
      data-testid="sidebar"
      data-collapsed={isCollapsed ? 'true' : 'false'}
      className={`bg-slate-800/80 border-r border-slate-700/70 min-h-screen flex flex-col flex-shrink-0 transition-all duration-200 ${
        isCollapsed ? 'w-12' : 'w-64'
      }`}
    >
      {/* Logo / Collapse Button */}
      <div className={`border-b border-slate-700/70 flex items-center ${isCollapsed ? 'justify-center py-3' : 'p-4 justify-between'}`}>
        {!isCollapsed && (
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-sky-500 to-blue-700 shadow-lift flex items-center justify-center text-white font-bold text-lg select-none">
              P
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-100 tracking-tight leading-none">PLM v2</h1>
              <p className="text-[11px] text-slate-500 mt-1">Product lifecycle</p>
            </div>
          </div>
        )}
        <button
          onClick={toggleCollapsed}
          className="p-1.5 hover:bg-slate-700 rounded-md text-slate-400 hover:text-slate-100"
          title={isCollapsed ? 'Expand' : 'Collapse'}
        >
          {isCollapsed ? '▶' : '◀'}
        </button>
      </div>

      {/* Search */}
      {!isCollapsed && (
        <div className="p-2 border-b border-slate-700/70">
          <SearchBox />
        </div>
      )}

      {/* Navigation Items */}
      <nav className={`flex-1 space-y-0.5 ${isCollapsed ? 'p-1' : 'p-2'}`}>
        {dailyItems.map(renderNavItem)}
        {showSetup && (
          <>
            {!isCollapsed ? (
              <p className="text-[10px] uppercase tracking-wider text-slate-500 px-3 pt-4 pb-1">SETUP</p>
            ) : (
              <div className="border-t border-slate-700/70 mt-2 pt-2" />
            )}
            {setupItems.map(renderNavItem)}
          </>
        )}
      </nav>

      {/* User block + Logout */}
      <div className={`border-t border-slate-700/70 space-y-1 ${isCollapsed ? 'p-1' : 'p-2'}`}>
        {username && (
          <div className={`flex items-center gap-2.5 py-2 ${isCollapsed ? 'justify-center px-0' : 'px-2'}`}>
            <div
              className="w-8 h-8 rounded-lg bg-gradient-to-br from-slate-600 to-slate-700 text-slate-100 flex items-center justify-center text-sm font-semibold flex-shrink-0 ring-1 ring-slate-600"
              title={username}
            >
              {username.charAt(0).toUpperCase()}
            </div>
            {!isCollapsed && (
              <div className="min-w-0">
                <p className="text-sm text-slate-200 font-medium truncate leading-tight">{username}</p>
                {role && <p className="text-[11px] text-slate-500 capitalize">{role}</p>}
              </div>
            )}
          </div>
        )}
        {role === 'admin' && <ActsAsSwitch collapsed={isCollapsed} />}
        <NotificationBell collapsed={isCollapsed} />
        <button
          onClick={logout}
          className={`w-full py-2 rounded-md border border-slate-700 text-slate-400 hover:border-red-500/50 hover:text-red-300 hover:bg-red-500/10 font-medium text-sm ${isCollapsed ? 'px-0' : 'px-3'}`}
          title={isCollapsed ? 'Logout' : ''}
        >
          {isCollapsed ? '↪' : 'Logout'}
        </button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 5: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/lib/safeStorage.test.ts src/components/layout && npx tsc --noEmit`
Expected: PASS (existing Sidebar and ActsAsSwitch tests included).

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/lib/safeStorage.ts frontend/src/lib/safeStorage.test.ts \
  frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/Sidebar.test.tsx
git commit -F - <<'MSG'
feat(layout): sidebar starts as a remembered icon rail on project pages

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 6: One-line header with status chips, slide-over sections and the ⋯ menu

**Files:**
- Create: `frontend/src/hooks/queries/useProjectStatus.ts`
- Create: `frontend/src/hooks/queries/useProjectStatus.test.ts`
- Create: `frontend/src/components/project/StatusSlideOver.tsx`
- Modify: `frontend/src/components/project/ProjectHeaderBar.tsx` (full replacement)
- Create: `frontend/src/components/project/ProjectHeaderBar.test.tsx`
- Create: `frontend/src/pages/ProjectDetailPage.layout.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.files.test.tsx` (the two add-part tests open the ⋯ menu first)

**Interfaces:**
- Consumes: `SepState` (`types/sep.ts`), `changesApi.list`, the query keys `['sep', id]`, `['changes', 'project', id]`, `['lesson-references', id]` (shared with the three sections so the cache is shared).
- Produces:

```ts
// hooks/queries/useProjectStatus.ts
export type ChipTone = 'neutral' | 'green' | 'yellow' | 'red' | 'amber';
export interface StatusChip { label: string; tone: ChipTone; title: string }
export function sepChip(sep: SepState | undefined): StatusChip
export function changesChip(changes: { status: string }[] | undefined): StatusChip
export function lessonsChip(references: unknown[] | undefined): StatusChip
export function useProjectStatus(projectId: number): { sep: StatusChip; changes: StatusChip; lessons: StatusChip }
// components/project/StatusSlideOver.tsx
export type StatusSection = 'sep' | 'changes' | 'lessons';
export default function StatusSlideOver(props: { section: StatusSection | null; projectId: number; onClose(): void }): JSX.Element | null
// components/project/ProjectHeaderBar.tsx
export default function ProjectHeaderBar(props: { project: Project; onOpenSection(section: StatusSection): void; onStartChange(): void; onAddPart(): void }): JSX.Element
```

Test ids: `project-header`, `chip-sep`, `chip-changes`, `chip-lessons`, `status-slideover`, `slideover-backdrop`; the ⋯ button has `aria-label="Project actions"`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/hooks/queries/useProjectStatus.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { changesChip, lessonsChip, sepChip } from './useProjectStatus'
import type { SepGate, SepState } from '../../types/sep'

const gate = (over: Partial<SepGate>): SepGate => ({
  id: 1, project_id: 2, code: 'K0/RG1', seq: 1, phase_de: '', phase_en: 'Kick-off', status: 'pending', color: 'green',
  target_date: null, pm_signed_name: null, pm_signed_at: null, quality_signed_name: null, quality_signed_at: null,
  progress: { done: 0, open: 10, not_applicable: 0, total: 10, pct: 0 }, open_risks: 0, items: [], ...over,
})

describe('sepChip', () => {
  it('shows the current gate and its progress', () => {
    const sep: SepState = { active: true, gates: [gate({ status: 'closed', code: 'K0' }), gate({ id: 2, code: 'K0/RG1', status: 'in_progress', color: 'yellow', progress: { done: 3, open: 7, not_applicable: 0, total: 10, pct: 30 } })] }
    expect(sepChip(sep)).toEqual({ label: 'K0/RG1 30%', tone: 'yellow', title: 'Kick-off: 3 of 10 done' })
  })
  it('says when SEP is off, done, or still loading', () => {
    expect(sepChip({ active: false, gates: [] }).label).toBe('SEP off')
    expect(sepChip({ active: true, gates: [gate({ status: 'closed' })] }).label).toBe('SEP done')
    expect(sepChip(undefined).label).toBe('SEP')
  })
})

describe('changesChip', () => {
  it('counts only open changes', () => {
    expect(changesChip([{ status: 'scoping' }, { status: 'closed' }, { status: 'rejected' }, { status: 'cancelled' }]).label).toBe('1 change')
    expect(changesChip([]).label).toBe('0 changes')
    expect(changesChip(undefined).label).toBe('Changes')
  })
})

describe('lessonsChip', () => {
  it('warns in amber when no lessons review is recorded', () => {
    expect(lessonsChip([])).toEqual({ label: 'No lessons review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' })
    expect(lessonsChip([{}, {}]).label).toBe('2 lessons reviewed')
    expect(lessonsChip([{}]).label).toBe('1 lesson reviewed')
    expect(lessonsChip(undefined).label).toBe('Lessons')
  })
})
```

`frontend/src/components/project/ProjectHeaderBar.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ProjectHeaderBar from './ProjectHeaderBar'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../MilestoneStrip', () => ({ default: () => <div>milestones</div> }))

const project = { id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' as const }

function mount() {
  const props = { onOpenSection: vi.fn(), onStartChange: vi.fn(), onAddPart: vi.fn() }
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ProjectHeaderBar project={project} {...props} /></MemoryRouter>
    </QueryClientProvider>)
  return props
}

describe('ProjectHeaderBar', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/sep/projects/2') return Promise.resolve({ data: { active: true, gates: [
        { id: 1, code: 'K0/RG1', status: 'in_progress', color: 'green', phase_en: 'Kick-off', progress: { done: 0, open: 5, not_applicable: 0, total: 5, pct: 0 } },
      ] } })
      if (url === '/v1/changes') return Promise.resolve({ data: [{ id: 1, status: 'scoping' }, { id: 2, status: 'closed' }] })
      if (url === '/v1/lessons/projects/2/references') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows code, name and customer on one row with the three status chips', async () => {
    mount()
    const header = screen.getByTestId('project-header')
    expect(header.textContent).toContain('1994')
    expect(header.textContent).toContain('Seat Trim')
    expect(header.textContent).toContain('VW group')
    expect((await screen.findByText('K0/RG1 0%'))).toBeTruthy()
    expect(await screen.findByText('1 change')).toBeTruthy()
    expect(await screen.findByText('No lessons review')).toBeTruthy()
    expect(screen.getByTestId('chip-lessons').className).toContain('amber')
  })

  it('opens the matching section from each chip', async () => {
    const props = mount()
    fireEvent.click(screen.getByTestId('chip-sep'))
    fireEvent.click(screen.getByTestId('chip-changes'))
    fireEvent.click(screen.getByTestId('chip-lessons'))
    expect(props.onOpenSection.mock.calls).toEqual([['sep'], ['changes'], ['lessons']])
  })

  it('keeps the project actions in the ⋯ menu', async () => {
    const props = mount()
    expect(screen.queryByText('+ Add Part')).toBeNull()
    fireEvent.click(screen.getByLabelText('Project actions'))
    expect(screen.getByText('Start change request')).toBeTruthy()
    expect(screen.getByLabelText('Customer file naming')).toBeTruthy()
    expect(screen.getByText('milestones')).toBeTruthy()
    fireEvent.click(screen.getByText('+ Add Part'))
    expect(props.onAddPart).toHaveBeenCalled()
    expect(screen.queryByText('+ Add Part')).toBeNull()
  })

  it('closes the menu on Escape', () => {
    mount()
    fireEvent.click(screen.getByLabelText('Project actions'))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText('+ Add Part')).toBeNull()
  })
})
```

`frontend/src/pages/ProjectDetailPage.layout.test.tsx` (later tasks append describe blocks to this file):

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/workflows/RevisionWorkflowSection', () => stub('workflow-section'))
vi.mock('../components/PartBOMSection', () => stub('bom-section'))
vi.mock('../components/PartRelationsSection', () => stub('relations-section'))
vi.mock('../components/ProcessFlowSection', () => stub('process-flow-section'))
vi.mock('../components/PPAPSection', () => stub('ppap-section'))
vi.mock('../components/MilestoneStrip', () => stub('milestones'))
vi.mock('../components/ProjectLessonsSection', () => stub('lessons-section'))
vi.mock('../components/ProjectSepSection', () => stub('sep-section'))
vi.mock('../components/ProjectChangesSection', () => stub('changes-section'))
vi.mock('../components/parts/AssemblyTreeList', () => stub('assemblies'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

// Some tests replace these two; keep them at the jsdom defaults otherwise.
const realOpen = window.open

const LH = { id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null, lifecycle_phase: 'nominated' }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null, lifecycle_phase: 'nominated' }
const TOOL = { id: 30, part_number: '199401', name: '1994 TOOL Handle', part_type: 'purchased', active_revision_id: null, item_category: 'tool', parent_part_id: null, lifecycle_phase: 'rfq' }
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

let partsData: unknown[] = [LH, RH, TOOL]

function routeGet(url: string) {
  if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' }] })
  if (url === '/v1/parts/project/2') return Promise.resolve({ data: partsData })
  if (url === '/v1/parts/project/2/structure') return Promise.resolve({ data: structure })
  if (url === '/v1/parts/project/2/paint-overview') return Promise.resolve({ data: [
    { part_id: 6, part_number: RH.part_number, name: RH.name, process: null, layers: [{ layer_order: 1, area: null, notes: null,
      paint: { id: 7, name: 'Black', paint_type: 'basecoat', colour_code: 'RAL 9005', colour_name: 'Black', colour_hex: '#111111', supplier_id: null, supplier_text: null, spec_reference: null, notes: null, is_active: true } }] },
  ] })
  if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
  if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: structure.articles[1].revisions.map((r) => ({ ...r, part_id: 6, created_at: '2026-05-28' })) })
  if (url.includes('/bom-tree')) return Promise.resolve({ data: { part_id: 5, part_number: LH.part_number, name: LH.name, revision_name: 'E1', customer_index: '003', lines: [] } })
  if (url === '/v1/sep/projects/2') return Promise.resolve({ data: { active: true, gates: [
    { id: 1, code: 'K0/RG1', status: 'in_progress', color: 'green', phase_en: 'Kick-off', progress: { done: 0, open: 5, not_applicable: 0, total: 5, pct: 0 } },
  ] } })
  if (url === '/v1/lessons/projects/2/references') return Promise.resolve({ data: [] })
  return Promise.resolve({ data: [] })
}

function mount(path = '/projects/2') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
  return queryClient
}

beforeEach(() => {
  partsData = [LH, RH, TOOL]
  localStorage.clear()
  clientMocks.get.mockReset()
  clientMocks.get.mockImplementation(routeGet)
})
afterEach(() => {
  cleanup()
  window.open = realOpen
  vi.unstubAllGlobals()
})

describe('project header and slide-over', () => {
  it('no longer stacks the SEP, changes and lessons blocks above the items', async () => {
    mount()
    expect(await screen.findByTestId('project-header')).toBeTruthy()
    expect(screen.queryByText('sep-section')).toBeNull()
    expect(screen.queryByText('changes-section')).toBeNull()
    expect(screen.queryByText('lessons-section')).toBeNull()
  })

  it('opens each section in the slide-over and closes it with Escape or a click outside', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('chip-sep'))
    expect(within(screen.getByTestId('status-slideover')).getByText('sep-section')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('status-slideover')).toBeNull()

    fireEvent.click(screen.getByTestId('chip-lessons'))
    expect(screen.getByText('lessons-section')).toBeTruthy()
    fireEvent.click(screen.getByTestId('slideover-backdrop'))
    expect(screen.queryByTestId('status-slideover')).toBeNull()

    fireEvent.click(screen.getByTestId('chip-changes'))
    expect(screen.getByText('changes-section')).toBeTruthy()
  })

  it('the ⋯ menu still reaches the add-part dialog', async () => {
    mount()
    fireEvent.click(await screen.findByLabelText('Project actions'))
    fireEvent.click(screen.getByText('+ Add Part'))
    expect(screen.getByText('Add New Item')).toBeTruthy()
  })
})
```

`tsc` checks test files with `noUnusedLocals`, so this file imports only what it uses; later tasks that append blocks name the extra imports they add to this line.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/hooks/queries/useProjectStatus.test.ts src/components/project/ProjectHeaderBar.test.tsx src/pages/ProjectDetailPage.layout.test.tsx`
Expected: FAIL: `useProjectStatus` cannot be resolved; header tests fail on `project-header`; page tests fail on `project-header` / `chip-sep`.

- [ ] **Step 3: Create `frontend/src/hooks/queries/useProjectStatus.ts`**

```ts
/**
 * Data behind the three status chips in the project header. Uses the same
 * query keys as the SEP, changes and lessons sections so the slide-over
 * opens on a warm cache.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import { changesApi } from '../../api/changes';
import type { SepState } from '../../types/sep';

export type ChipTone = 'neutral' | 'green' | 'yellow' | 'red' | 'amber';
export interface StatusChip { label: string; tone: ChipTone; title: string }

const CLOSED_CHANGE_STATUSES = ['closed', 'rejected', 'cancelled'];

export function sepChip(sep: SepState | undefined): StatusChip {
  if (!sep) return { label: 'SEP', tone: 'neutral', title: 'SEP Q-gates' };
  if (!sep.active) return { label: 'SEP off', tone: 'neutral', title: 'SEP not active for this project' };
  const gates = Array.isArray(sep.gates) ? sep.gates : [];
  const current = gates.find((g) => g.status === 'in_progress');
  if (!current) {
    const done = gates.length > 0 && gates.every((g) => g.status === 'closed');
    return { label: done ? 'SEP done' : 'SEP', tone: done ? 'green' : 'neutral', title: 'SEP Q-gates' };
  }
  const applicable = current.progress.total - current.progress.not_applicable;
  return {
    label: `${current.code} ${current.progress.pct}%`,
    tone: current.color,
    title: `${current.phase_en}: ${current.progress.done} of ${applicable} done`,
  };
}

export function changesChip(changes: { status: string }[] | undefined): StatusChip {
  if (!changes) return { label: 'Changes', tone: 'neutral', title: 'Change requests' };
  const open = changes.filter((c) => !CLOSED_CHANGE_STATUSES.includes(c.status)).length;
  return {
    label: `${open} change${open === 1 ? '' : 's'}`,
    tone: 'neutral',
    title: `${open} open of ${changes.length} change requests`,
  };
}

export function lessonsChip(references: unknown[] | undefined): StatusChip {
  if (!references) return { label: 'Lessons', tone: 'neutral', title: 'Lessons learned' };
  if (references.length === 0) {
    return { label: 'No lessons review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' };
  }
  const n = references.length;
  return { label: `${n} lesson${n === 1 ? '' : 's'} reviewed`, tone: 'green', title: 'Lessons reviewed for reuse' };
}

export function useProjectStatus(projectId: number) {
  const sep = useQuery({
    queryKey: ['sep', projectId],
    queryFn: async () => (await client.get(`/v1/sep/projects/${projectId}`)).data as SepState,
    enabled: !!projectId,
  });
  const changes = useQuery({
    queryKey: ['changes', 'project', projectId],
    queryFn: () => changesApi.list({ project_id: projectId }),
    enabled: !!projectId,
  });
  const references = useQuery({
    queryKey: ['lesson-references', projectId],
    queryFn: async () => (await client.get(`/v1/lessons/projects/${projectId}/references`)).data as unknown[],
    enabled: !!projectId,
  });
  return {
    sep: sepChip(sep.data),
    changes: changesChip(Array.isArray(changes.data) ? changes.data : undefined),
    lessons: lessonsChip(Array.isArray(references.data) ? references.data : undefined),
  };
}
```

- [ ] **Step 4: Create `frontend/src/components/project/StatusSlideOver.tsx`**

```tsx
/**
 * Slide-over from the right that hosts one of the project status sections
 * (SEP Q-gates, changes, lessons) unchanged. Escape or a click outside closes it.
 */
import { useEffect } from 'react';
import ProjectSepSection from '../ProjectSepSection';
import ProjectChangesSection from '../ProjectChangesSection';
import ProjectLessonsSection from '../ProjectLessonsSection';

export type StatusSection = 'sep' | 'changes' | 'lessons';

const TITLES: Record<StatusSection, string> = {
  sep: 'SEP Q-Gates',
  changes: 'Changes',
  lessons: 'Lessons',
};

export default function StatusSlideOver({ section, projectId, onClose }: {
  section: StatusSection | null;
  projectId: number;
  onClose(): void;
}) {
  useEffect(() => {
    if (!section) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [section, onClose]);

  if (!section) return null;

  return (
    <div className="fixed inset-0 z-30" data-testid="status-slideover">
      <div data-testid="slideover-backdrop" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={TITLES[section]}
        className="absolute right-0 top-0 h-full w-full max-w-2xl bg-slate-900 border-l border-slate-700 shadow-xl flex flex-col"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 flex-shrink-0">
          <h2 className="text-sm font-semibold text-slate-200">{TITLES[section]}</h2>
          <button aria-label="Close" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-lg leading-none">×</button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          {section === 'sep' && <ProjectSepSection projectId={projectId} />}
          {section === 'changes' && <ProjectChangesSection projectId={projectId} />}
          {section === 'lessons' && <ProjectLessonsSection projectId={projectId} />}
        </div>
      </aside>
    </div>
  );
}
```

- [ ] **Step 5: Replace `frontend/src/components/project/ProjectHeaderBar.tsx`**

```tsx
/**
 * One-line project header: code, name and customer, three status chips that
 * open their section in the slide-over, and the project actions menu.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import MilestoneStrip from '../MilestoneStrip';
import StartChangeButton from '../changes/StartChangeButton';
import { useProjectStatus, type ChipTone, type StatusChip } from '../../hooks/queries/useProjectStatus';
import { CustomerNamingSelect } from './CustomerNamingSelect';
import { CUSTOMER_NAMING_LABELS, type Project } from './projectTypes';
import type { StatusSection } from './StatusSlideOver';

const TONE_CLASS: Record<ChipTone, string> = {
  neutral: 'border-slate-600 bg-slate-800 text-slate-200',
  green: 'border-emerald-700 bg-emerald-900/30 text-emerald-200',
  yellow: 'border-yellow-700 bg-yellow-900/30 text-yellow-200',
  red: 'border-red-700 bg-red-900/30 text-red-200',
  amber: 'border-amber-600 bg-amber-600/20 text-amber-300',
};

function Chip({ chip, testId, onClick }: { chip: StatusChip; testId: string; onClick(): void }) {
  return (
    <button
      type="button"
      data-testid={testId}
      title={chip.title}
      onClick={onClick}
      className={`px-2 py-0.5 rounded-full border text-xs font-medium whitespace-nowrap hover:brightness-125 ${TONE_CLASS[chip.tone]}`}
    >
      {chip.label}
    </button>
  );
}

export default function ProjectHeaderBar({ project, onOpenSection, onStartChange, onAddPart }: {
  project: Project;
  onOpenSection(section: StatusSection): void;
  onStartChange(): void;
  onAddPart(): void;
}) {
  const navigate = useNavigate();
  const status = useProjectStatus(project.id);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const customer = project.customer_naming ? CUSTOMER_NAMING_LABELS[project.customer_naming] : null;
  const menuItem = 'w-full text-left px-3 py-2 rounded text-sm text-slate-200 hover:bg-slate-700';

  return (
    <header
      data-testid="project-header"
      className="flex-shrink-0 h-12 px-4 flex items-center gap-3 border-b border-slate-700 bg-slate-900"
    >
      <button
        aria-label="Back to projects"
        title="Back to projects"
        onClick={() => navigate('/projects')}
        className="text-slate-400 hover:text-slate-200 text-sm"
      >
        ←
      </button>
      <h1 className="min-w-0 truncate text-sm text-slate-100">
        <span className="font-mono font-semibold">{project.code}</span>{' '}
        <span className="font-semibold">{project.name}</span>
        {customer && <span className="text-slate-400"> · {customer}</span>}
      </h1>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <Chip chip={status.sep} testId="chip-sep" onClick={() => onOpenSection('sep')} />
        <Chip chip={status.changes} testId="chip-changes" onClick={() => onOpenSection('changes')} />
        <Chip chip={status.lessons} testId="chip-lessons" onClick={() => onOpenSection('lessons')} />
      </div>
      <div className="ml-auto relative" ref={menuRef}>
        <button
          aria-label="Project actions"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((o) => !o)}
          className="px-2 py-1 rounded text-slate-300 hover:bg-slate-700 text-lg leading-none"
        >
          ⋯
        </button>
        {menuOpen && (
          <div role="menu" className="absolute right-0 top-full mt-1 z-40 w-80 rounded-lg border border-slate-700 bg-slate-800 shadow-lg p-2 space-y-1">
            <StartChangeButton
              label="Start change request"
              onClick={() => { setMenuOpen(false); onStartChange(); }}
              className={menuItem}
            />
            <button role="menuitem" onClick={() => { setMenuOpen(false); onAddPart(); }} className={menuItem}>
              + Add Part
            </button>
            <div className="px-3 py-2">
              <CustomerNamingSelect projectId={project.id} value={project.customer_naming ?? null} />
            </div>
            <div className="px-3 pt-2 pb-1 border-t border-slate-700">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Timing gates</p>
              <MilestoneStrip projectId={project.id} />
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
```

The "+ Gate" action lives inside `MilestoneStrip` (its "+ Gate" button), which the menu now hosts.

- [ ] **Step 6: Wire the page**

In `frontend/src/pages/ProjectDetailPage.tsx`:
1. Remove the imports of `ProjectLessonsSection`, `ProjectSepSection`, `ProjectChangesSection`; add `import StatusSlideOver, { type StatusSection } from '../components/project/StatusSlideOver';` and add `useCallback` to the `react` import.
2. Next to the other dialog states add:

```tsx
  const [openSection, setOpenSection] = useState<StatusSection | null>(null);
  const closeSection = useCallback(() => setOpenSection(null), []);
```

3. Replace the header and the three section mounts (keep `<ProjectPaintSection projectId={id} />` for now, Task 7 removes it):

```tsx
      <ProjectHeaderBar
        project={project}
        onOpenSection={setOpenSection}
        onStartChange={() => setShowStartChange(true)}
        onAddPart={() => setShowAddModal(true)}
      />
      <StatusSlideOver section={openSection} projectId={id} onClose={closeSection} />

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <ProjectPaintSection projectId={id} />
```

The `useCallback` must sit above the `if (projectLoading)` early return with the other hooks.

- [ ] **Step 7: Update the two add-part tests in `ProjectDetailPage.files.test.tsx`**

In both tests of `describe('ProjectDetailPage add part form')` replace

```tsx
    fireEvent.click(await screen.findByText('+ Add Part'))
```

with

```tsx
    fireEvent.click(await screen.findByLabelText('Project actions'))
    fireEvent.click(screen.getByText('+ Add Part'))
```

- [ ] **Step 8: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/hooks/queries src/components/project src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/hooks/queries/useProjectStatus.ts frontend/src/hooks/queries/useProjectStatus.test.ts \
  frontend/src/components/project/StatusSlideOver.tsx frontend/src/components/project/ProjectHeaderBar.tsx \
  frontend/src/components/project/ProjectHeaderBar.test.tsx frontend/src/pages/ProjectDetailPage.tsx \
  frontend/src/pages/ProjectDetailPage.layout.test.tsx frontend/src/pages/ProjectDetailPage.files.test.tsx
git commit -F - <<'MSG'
feat(project-page): one-line header with status chips, slide-over sections and actions menu

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 7: Paint leaves the project page

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.layout.test.tsx` (append)

**Interfaces:** none new. The paint overview query and `paintByPartId` / `paintedIds` stay: the Painted filter chip and the row swatch use them.

- [ ] **Step 1: Write the failing test**

Append to `ProjectDetailPage.layout.test.tsx`:

```tsx
describe('paint on the project page', () => {
  it('does not mount the paint section but keeps the Painted filter', async () => {
    mount()
    expect(await screen.findByText('🎨 Painted (1)')).toBeTruthy()
    expect(screen.queryByTestId('project-paint-toggle')).toBeNull()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ProjectDetailPage.layout.test.tsx -t "paint on the project page"`
Expected: FAIL, `project-paint-toggle` is found.

- [ ] **Step 3: Remove the mount**

In `ProjectDetailPage.tsx` delete `<ProjectPaintSection projectId={id} />` and `import ProjectPaintSection from '../components/paint/ProjectPaintSection';`. Leave `frontend/src/components/paint/ProjectPaintSection.tsx` and its tests in place (the spec only removes it from this page).

- [ ] **Step 4: Run the page tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass, including `ProjectDetailPage painted filter` in the files test.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.layout.test.tsx
git commit -F - <<'MSG'
feat(project-page): paint section no longer mounted on the project page

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 8: Grouped, searchable list with slim two-line rows

**Files:**
- Modify: `frontend/src/lib/partDisplay.ts`, `frontend/src/lib/partDisplay.test.ts` (add `shortName`)
- Modify: `frontend/src/components/project/projectTypes.ts` (`Part.lifecycle_phase`)
- Create: `frontend/src/components/project/itemGroups.ts`, `frontend/src/components/project/itemGroups.test.ts`
- Modify: `frontend/src/components/project/ItemRow.tsx` (full replacement)
- Modify: `frontend/src/components/project/ItemsPane.tsx` (full replacement)
- Modify: `frontend/src/pages/ProjectDetailPage.layout.test.tsx` (append)
- Modify: `frontend/src/pages/ProjectDetailPage.files.test.tsx` (one selector)

**Interfaces:**
- Consumes: `buildPartTree`, `comparePartNodes`, `getDescendantIds`, `CATEGORY_META` (Task 1); `articleOf`, `ProjectStructure`.
- Produces:

```ts
// lib/partDisplay.ts
export function shortName(name: string, code: string | undefined | null, customerNumber: string | undefined | null): string
// components/project/itemGroups.ts
export type GroupKey = 'article' | 'tool' | 'equipment' | 'gauge' | 'assemblies';
export interface ItemGroup { key: GroupKey; label: string; nodes: TreeNode[] }
export const ITEM_GROUPS: { key: GroupKey; label: string }[];
export function groupOf(part: Part): GroupKey;
export function matchesSearch(part: Part, query: string): boolean;
export function groupNodes(nodes: TreeNode[]): ItemGroup[];
export function visibleOrder(groups: ItemGroup[], collapsed: ReadonlySet<GroupKey>, isExpanded: (node: TreeNode) => boolean): number[];
// ItemRow props (replaces the old TreeNodeComponent props)
export interface ItemRowProps {
  node: TreeNode; depth?: number; projectCode?: string; structure?: ProjectStructure;
  paintByPartId?: Map<number, PartPaintLayer>; selectedPartId: number | null;
  isExpanded(node: TreeNode): boolean; onSetExpanded(partId: number, next: boolean): void;
  onSelect(id: number): void; onContextMenu(e: React.MouseEvent, id: number): void;
  onSelectRevision?(partId: number, revisionId: number): void;
  draggingPartId: number | null; invalidDropIds: Set<number>;
  onDragStartPart(id: number): void; onDragEndPart(): void; onDropOnPart(targetId: number): void;
}
```
- DOM contract: group toggle `data-testid="group-toggle-<key>"` with `aria-expanded`; row button `data-testid="item-row-<id>"` and `data-row-id="<id>"`; search input `aria-label="Search items"`; list scroll container `data-testid="items-scroll"`. Kept test ids: `tree-mirror-of-<id>`, `tree-mirrored-by-<id>`, `paint-swatch-<id>`, `tree-numbers-<id>`, `tree-rev-<id>`, `tree-rel-<id>`. New: `row-rev-<id>`, `row-proposal-<id>`.

Grouping rule: a part with `part_type === 'sub_assembly'` goes to Assemblies (its children stay nested under it); otherwise `item_category` `tool` -> Tools, `assembly_equipment` or `eoat` -> Equipment, `gauge` -> Gauges, anything else -> Articles. Groups are built from root nodes only. Search (number, customer number, Tier 1 number, name; case-insensitive) flattens the tree so a nested hit is listed on its own.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/partDisplay.test.ts` (and add `shortName` to its import):

```ts
describe('shortName', () => {
  it('drops the customer number and the project code the row already shows', () => {
    expect(shortName('206.882.251 Handle LH', '1994', '206.882.251')).toBe('Handle LH')
    expect(shortName('1994 206.882.251 Cover', '1994', '206.882.251')).toBe('Cover')
    expect(shortName('Handle 206.882.251 LH', '1994', '206.882.251')).toBe('Handle LH')
    expect(shortName('1994 TOOL Handle', '1994', null)).toBe('TOOL Handle')
  })
  it('keeps the full name when stripping would leave nothing', () => {
    expect(shortName('206.882.251', '1994', '206.882.251')).toBe('206.882.251')
  })
  it('does not cut a number that only shares a prefix', () => {
    expect(shortName('206.882.2519 Special', null, '206.882.251')).toBe('206.882.2519 Special')
  })
})
```

`frontend/src/components/project/itemGroups.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { groupNodes, groupOf, matchesSearch, visibleOrder } from './itemGroups'
import type { Part, TreeNode } from './projectTypes'

const part = (id: number, over: Partial<Part> = {}): Part => ({
  id, part_number: `P${id}`, name: `Part ${id}`, part_type: 'internal_mfg', active_revision_id: null,
  item_category: 'article', parent_part_id: null, ...over,
})
const node = (p: Part, children: TreeNode[] = []): TreeNode => ({ part: p, children })

describe('groupOf', () => {
  it('maps categories and sub-assemblies to the five groups', () => {
    expect(groupOf(part(1))).toBe('article')
    expect(groupOf(part(2, { item_category: 'tool' }))).toBe('tool')
    expect(groupOf(part(3, { item_category: 'assembly_equipment' }))).toBe('equipment')
    expect(groupOf(part(4, { item_category: 'eoat' }))).toBe('equipment')
    expect(groupOf(part(5, { item_category: 'gauge' }))).toBe('gauge')
    expect(groupOf(part(6, { part_type: 'sub_assembly' }))).toBe('assemblies')
    expect(groupOf(part(7, { item_category: 'something_new' }))).toBe('article')
  })
})

describe('groupNodes', () => {
  it('keeps the fixed group order and hides empty groups', () => {
    const groups = groupNodes([node(part(1, { item_category: 'gauge' })), node(part(2)), node(part(3, { item_category: 'tool' }))])
    expect(groups.map((g) => [g.key, g.label, g.nodes.length])).toEqual([
      ['article', 'Articles', 1], ['tool', 'Tools', 1], ['gauge', 'Gauges', 1],
    ])
  })
})

describe('matchesSearch', () => {
  const p = part(1, { part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: 'Handle LH' })
  it('matches number, customer number, tier 1 number and name, ignoring case', () => {
    for (const q of ['1994-001', '882.251', 's00h4x', 'handle', '  HANDLE  ']) expect(matchesSearch(p, q)).toBe(true)
    expect(matchesSearch(p, 'bracket')).toBe(false)
    expect(matchesSearch(p, '')).toBe(true)
  })
})

describe('visibleOrder', () => {
  it('walks open groups and expanded children in display order', () => {
    const child = node(part(11))
    const assy = node(part(10, { part_type: 'sub_assembly' }), [child])
    const groups = groupNodes([node(part(1)), node(part(2, { item_category: 'tool' })), assy])
    expect(visibleOrder(groups, new Set(), () => true)).toEqual([1, 2, 10, 11])
    expect(visibleOrder(groups, new Set(['tool']), () => true)).toEqual([1, 10, 11])
    expect(visibleOrder(groups, new Set(), () => false)).toEqual([1, 2, 10])
  })
})
```

Append to `frontend/src/pages/ProjectDetailPage.layout.test.tsx`:

```tsx
describe('grouped slim item rows', () => {
  it('groups the items by category in a fixed order and hides empty groups', async () => {
    mount()
    await screen.findByTestId('group-toggle-article')
    expect(screen.getAllByTestId(/^group-toggle-/).map((el) => el.getAttribute('data-testid')))
      .toEqual(['group-toggle-article', 'group-toggle-tool'])
    expect(screen.getByTestId('group-toggle-article').textContent).toContain('Articles')
    expect(screen.getByTestId('group-toggle-article').textContent).toContain('2')
  })

  it('shows customer number and short name on line 1, internal number, revision, phase and icons on line 2', async () => {
    mount()
    const lh = await screen.findByTestId('item-row-5')
    await within(lh).findByTestId('row-rev-5')
    const [line1, line2] = Array.from(lh.children) as HTMLElement[]
    expect(line1.textContent).toContain('206.882.251')
    // the name span holds the short name alone (customer number stripped)
    expect(within(line1).getByText('Handle LH')).toBeTruthy()
    expect(line2.textContent).toContain('20-1994-001-0')
    expect(within(lh).getByTestId('row-rev-5').textContent).toBe('E1 · 003')
    expect(line2.textContent).toContain('nominated')
    expect(within(lh).getByTestId('row-proposal-5')).toBeTruthy()
    const rh = screen.getByTestId('item-row-6')
    expect(within(rh).getByTestId('tree-mirror-of-6')).toBeTruthy()
    expect(await within(rh).findByTestId('paint-swatch-6')).toBeTruthy()
    // no part-type badge on the rows any more
    expect(screen.queryByText('internal mfg')).toBeNull()
  })

  it('shows the internal number on line 1 when there is no customer number, and only once', async () => {
    mount()
    const tool = await screen.findByTestId('item-row-30')
    expect(tool.children[0].textContent).toContain('199401')
    expect(tool.children[0].textContent).toContain('TOOL Handle')
    expect(tool.textContent!.split('199401').length - 1).toBe(1)
  })

  it('collapses a group from its header', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('group-toggle-tool'))
    expect(screen.getByTestId('group-toggle-tool').getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('item-row-30')).toBeNull()
  })

  it('search finds a part nested under an assembly whose own name does not match', async () => {
    partsData = [
      { id: 40, part_number: '1994-40', name: 'Seat frame assy', part_type: 'sub_assembly', item_category: 'article', active_revision_id: null, parent_part_id: null },
      { id: 41, part_number: '1994-41', name: 'Bracket inner', part_type: 'internal_mfg', item_category: 'article', active_revision_id: null, parent_part_id: 40 },
      LH, TOOL,
    ]
    mount()
    await screen.findByTestId('item-row-41')
    fireEvent.change(screen.getByLabelText('Search items'), { target: { value: 'bracket' } })
    expect(screen.getByText('Items (1 of 4)')).toBeTruthy()
    expect(screen.getByTestId('item-row-41')).toBeTruthy()
    expect(screen.queryByTestId('item-row-40')).toBeNull()
    fireEvent.change(screen.getByLabelText('Search items'), { target: { value: '' } })
    expect(screen.getByTestId('item-row-40')).toBeTruthy()
  })
})
```

In `frontend/src/pages/ProjectDetailPage.files.test.tsx`, test `sorts numerically, drops the project code from names, and counts the filtered rows`: the new "Tools" group header also matches `/Tool/`, so click the chip by its exact label:

```tsx
    fireEvent.click(screen.getByText('🔧 Tool'))
```

(replacing `fireEvent.click(screen.getByText(/Tool/))`).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/lib/partDisplay.test.ts src/components/project/itemGroups.test.ts src/pages/ProjectDetailPage.layout.test.tsx`
Expected: FAIL: `shortName` is not exported, `./itemGroups` does not resolve, the page tests do not find `group-toggle-article` / `item-row-5`.

- [ ] **Step 3: Add `shortName` to `frontend/src/lib/partDisplay.ts`**

```ts
const SEPARATORS = '[\\s\\-_:·•]';

/** Row name without the customer number and the project code: the row
 *  already shows the number, so repeating it only pushes the name out. */
export function shortName(name: string, code: string | undefined | null, customerNumber: string | undefined | null): string {
  let out = name;
  if (customerNumber) {
    const escaped = customerNumber.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`(^|${SEPARATORS})${escaped}(?=$|${SEPARATORS})${SEPARATORS}*`, 'i'), '$1');
  }
  out = stripProjectCode(out.trim(), code).trim();
  return out.length ? out : name;
}
```

- [ ] **Step 4: Add the phase to `Part` in `projectTypes.ts`**

In `interface Part`, after `next_calibration_due?: string | null;` add:

```ts
  lifecycle_phase?: string;
```

(`PartResponse` in the backend already returns `lifecycle_phase` for every part; tools have no structure entry, so the row reads the phase from the part.)

- [ ] **Step 5: Create `frontend/src/components/project/itemGroups.ts`**

```ts
/** Grouping, search and display order of the project items list. */
import type { Part, TreeNode } from './projectTypes';

export type GroupKey = 'article' | 'tool' | 'equipment' | 'gauge' | 'assemblies';

export interface ItemGroup {
  key: GroupKey;
  label: string;
  nodes: TreeNode[];
}

export const ITEM_GROUPS: { key: GroupKey; label: string }[] = [
  { key: 'article', label: 'Articles' },
  { key: 'tool', label: 'Tools' },
  { key: 'equipment', label: 'Equipment' },
  { key: 'gauge', label: 'Gauges' },
  { key: 'assemblies', label: 'Assemblies' },
];

export function groupOf(part: Part): GroupKey {
  if (part.part_type === 'sub_assembly') return 'assemblies';
  if (part.item_category === 'tool') return 'tool';
  if (part.item_category === 'assembly_equipment' || part.item_category === 'eoat') return 'equipment';
  if (part.item_category === 'gauge') return 'gauge';
  return 'article';
}

export function matchesSearch(part: Part, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [part.part_number, part.customer_part_number, part.tier1_part_number, part.name]
    .some((v) => !!v && v.toLowerCase().includes(q));
}

/** Root nodes into the fixed groups; empty groups are left out. */
export function groupNodes(nodes: TreeNode[]): ItemGroup[] {
  return ITEM_GROUPS
    .map((g) => ({ ...g, nodes: nodes.filter((n) => groupOf(n.part) === g.key) }))
    .filter((g) => g.nodes.length > 0);
}

/** Part ids in the order the list shows them: open groups, expanded children. */
export function visibleOrder(
  groups: ItemGroup[],
  collapsed: ReadonlySet<GroupKey>,
  isExpanded: (node: TreeNode) => boolean,
): number[] {
  const out: number[] = [];
  const walk = (n: TreeNode) => {
    out.push(n.part.id);
    if (n.children.length > 0 && isExpanded(n)) n.children.forEach(walk);
  };
  for (const g of groups) {
    if (!collapsed.has(g.key)) g.nodes.forEach(walk);
  }
  return out;
}
```

- [ ] **Step 6: Replace `frontend/src/components/project/ItemRow.tsx`**

```tsx
/**
 * One slim item row: customer number and short name on line 1; internal
 * number, active revision, phase and mirror / paint / proposal marks on
 * line 2. The expand block (numbers, revisions, linked items) and
 * drag-to-restructure onto a sub-assembly work as before.
 */
import { useState } from 'react';
import ColourSwatch from '../paint/ColourSwatch';
import { revisionLabel } from '../parts/RevisionBadge';
import { shortName, stripProjectCode } from '../../lib/partDisplay';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import { CATEGORY_META, type TreeNode } from './projectTypes';

export interface ItemRowProps {
  node: TreeNode;
  depth?: number;
  projectCode?: string;
  structure?: ProjectStructure;
  paintByPartId?: Map<number, PartPaintLayer>;
  selectedPartId: number | null;
  isExpanded(node: TreeNode): boolean;
  onSetExpanded(partId: number, next: boolean): void;
  onSelect(id: number): void;
  onContextMenu(e: React.MouseEvent, id: number): void;
  onSelectRevision?(partId: number, revisionId: number): void;
  draggingPartId: number | null;
  invalidDropIds: Set<number>;
  onDragStartPart(id: number): void;
  onDragEndPart(): void;
  onDropOnPart(targetId: number): void;
}

export default function ItemRow(props: ItemRowProps) {
  const {
    node, depth = 0, projectCode, structure, paintByPartId, selectedPartId, isExpanded, onSetExpanded,
    onSelect, onContextMenu, onSelectRevision, draggingPartId, invalidDropIds,
    onDragStartPart, onDragEndPart, onDropOnPart,
  } = props;
  const [dragOver, setDragOver] = useState(false);
  const part = node.part;
  const article = articleOf(structure, part.id);
  const hasChildren = node.children.length > 0;
  const hasStructure = !!article && (article.revisions.length > 0 || article.related.length > 0);
  const expandable = hasChildren || hasStructure;
  const expanded = expandable && isExpanded(node);
  const selected = selectedPartId === part.id;
  const isDropTarget =
    draggingPartId !== null &&
    draggingPartId !== part.id &&
    part.part_type === 'sub_assembly' &&
    !invalidDropIds.has(part.id);

  const customerNumber = part.customer_part_number ?? article?.customer_part_number ?? null;
  const activeRevision = article?.revisions.find((r) => r.is_active);
  const hasProposal = !!article?.revisions.some((r) => r.parent_revision_id !== null);
  const phase = article?.lifecycle_phase ?? part.lifecycle_phase;
  const paint = paintByPartId?.get(part.id);
  const indent = depth * 16;

  return (
    <div>
      <div className="flex items-stretch gap-1" style={{ paddingLeft: `${indent}px` }}>
        {expandable ? (
          <button
            type="button"
            aria-label={expanded ? 'Collapse' : 'Expand'}
            onClick={() => onSetExpanded(part.id, !expanded)}
            className="w-4 flex-shrink-0 text-[10px] text-slate-500 hover:text-slate-200"
          >
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}
        <button
          type="button"
          data-testid={`item-row-${part.id}`}
          data-row-id={part.id}
          aria-current={selected ? 'true' : undefined}
          onClick={() => onSelect(part.id)}
          onContextMenu={(e) => onContextMenu(e, part.id)}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move';
            onDragStartPart(part.id);
          }}
          onDragEnd={onDragEndPart}
          onDragOver={(e) => {
            if (isDropTarget) {
              e.preventDefault();
              setDragOver(true);
            }
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            if (isDropTarget) onDropOnPart(part.id);
          }}
          className={`flex-1 min-w-0 text-left px-2 py-1 rounded border transition ${
            dragOver && isDropTarget
              ? 'bg-green-900/40 border-green-500'
              : selected
                ? 'bg-blue-900/40 border-blue-500'
                : 'border-transparent hover:bg-slate-800'
          } ${draggingPartId === part.id ? 'opacity-40' : ''}`}
        >
          <div className="flex items-center gap-2 min-w-0 text-sm">
            <span className="font-mono text-slate-200 flex-shrink-0">{customerNumber ?? part.part_number}</span>
            <span className="truncate text-slate-100">{shortName(part.name, projectCode, customerNumber)}</span>
            {part.part_type === 'sub_assembly' && <span className="text-yellow-400 flex-shrink-0" title="Sub-assembly">★</span>}
            {hasChildren && <span className="text-xs text-slate-500 flex-shrink-0">({node.children.length})</span>}
          </div>
          <div className="flex items-center gap-2 min-w-0 text-[11px] text-slate-500">
            {customerNumber && <span className="font-mono">{part.part_number}</span>}
            {activeRevision && (
              <span data-testid={`row-rev-${part.id}`} className="font-mono text-slate-400">
                {revisionLabel(activeRevision.revision_name, activeRevision.customer_index)}
              </span>
            )}
            {phase && <span>{phase}</span>}
            {article?.mirror_of && (
              <span data-testid={`tree-mirror-of-${part.id}`} title={`mirror of ${article.mirror_of.part_number}`} className="text-red-300">
                ⇄<span className="sr-only">mirror of {article.mirror_of.part_number}</span>
              </span>
            )}
            {article && article.mirrored_by.length > 0 && (
              <span data-testid={`tree-mirrored-by-${part.id}`} title={`mirrored by ${article.mirrored_by.map((m) => m.part_number).join(', ')}`} className="text-red-300">
                ⇄<span className="sr-only">mirrored by {article.mirrored_by.map((m) => m.part_number).join(', ')}</span>
              </span>
            )}
            {paint && (
              <span data-testid={`paint-swatch-${part.id}`} className="flex items-center" title="Painted">
                <ColourSwatch hex={paint.paint.colour_hex} code={paint.paint.colour_code} />
              </span>
            )}
            {hasProposal && (
              <span data-testid={`row-proposal-${part.id}`} title="Has a proposal" className="text-amber-300">✎</span>
            )}
          </div>
        </button>
      </div>

      {expanded && hasStructure && (
        <div className="my-1 space-y-1 text-xs" style={{ marginLeft: `${indent + 24}px` }}>
          {(part.customer_part_number || part.tier1_part_number) && (
            <div className="flex flex-wrap items-center gap-1" data-testid={`tree-numbers-${part.id}`}>
              <span className="text-slate-500 w-16">Numbers</span>
              {part.customer_part_number && (
                <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono" title="Customer (OEM) part number">{part.customer_part_number}</span>
              )}
              {part.tier1_part_number && (
                <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono" title="Tier 1 part number">Tier 1 {part.tier1_part_number}</span>
              )}
            </div>
          )}
          {article!.revisions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Revisions</span>
              {article!.revisions.map((r) => (
                <button key={r.id} type="button" data-testid={`tree-rev-${r.id}`} onClick={() => onSelectRevision?.(part.id, r.id)}
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
                <button key={`${r.relation_type}-${r.part_id}`} type="button" data-testid={`tree-rel-${r.part_id}`} onClick={() => onSelect(r.part_id)}
                  className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                  {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, projectCode)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <ItemRow key={child.part.id} {...props} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
```

The chevron is now a sibling of the row button, not nested inside it (nested buttons are invalid HTML). The existing article test finds it with `within(row.closest('button')!.parentElement!)`, which still works: the row button's parent holds both.

- [ ] **Step 7: Replace `frontend/src/components/project/ItemsPane.tsx`**

```tsx
/**
 * ItemsPane - the project's items: search, category filter, collapsible
 * groups of slim rows, and drag-to-restructure onto sub-assemblies. Only the
 * list below the controls scrolls.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import AssemblyTreeList from '../parts/AssemblyTreeList';
import { apiErrorMessage } from '../../lib/apiError';
import type { ProjectStructure } from '../../hooks/queries/useProjectStructure';
import type { PartPaintLayer } from '../../types/paint';
import ItemRow from './ItemRow';
import { groupNodes, matchesSearch, type GroupKey } from './itemGroups';
import {
  CATEGORY_META, buildPartTree, comparePartNodes, getDescendantIds, type Part, type TreeNode,
} from './projectTypes';

export interface ItemsPaneProps {
  projectId: number;
  projectCode: string;
  parts: Part[] | undefined;
  partsLoading: boolean;
  structure: ProjectStructure | undefined;
  paintByPartId: Map<number, PartPaintLayer>;
  paintedIds: Set<number>;
  paintedCount: number;
  selectedPartId: number | null;
  onSelect(partId: number): void;
  onOpenPart(partId: number): void;
  onPickRevision(partId: number, revisionId: number): void;
  onContextMenu(e: React.MouseEvent, partId: number): void;
}

export default function ItemsPane({
  projectId, projectCode, parts, partsLoading, structure, paintByPartId, paintedIds, paintedCount,
  selectedPartId, onSelect, onOpenPart, onPickRevision, onContextMenu,
}: ItemsPaneProps) {
  const queryClient = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<GroupKey>>(() => new Set());
  // Rows with children start expanded, everything else collapsed; a click overrides.
  const [expandOverride, setExpandOverride] = useState<Record<number, boolean>>({});
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);

  const reparentMutation = useMutation({
    mutationFn: async ({ partId, parentPartId }: { partId: number; parentPartId: number | null }) => {
      await client.put(`/v1/parts/${partId}`, { parent_part_id: parentPartId });
    },
    onSuccess: () => {
      toast.success('Part moved');
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      queryClient.invalidateQueries({ queryKey: ['assembly-files'] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to move part'));
    },
  });

  const handleDropOnPart = (targetId: number) => {
    if (draggingPartId === null) return;
    const dragged = parts?.find((p) => p.id === draggingPartId);
    if (dragged?.parent_part_id === targetId) {
      setDraggingPartId(null);
      return; // already a child of the target
    }
    reparentMutation.mutate({ partId: draggingPartId, parentPartId: targetId });
    setDraggingPartId(null);
  };

  const invalidDropIds = draggingPartId !== null && parts ? getDescendantIds(parts, draggingPartId) : new Set<number>();

  const query = search.trim();
  const partTree = useMemo(() => (parts ? buildPartTree(parts) : []), [parts]);
  const visibleNodes: TreeNode[] = useMemo(() => {
    if (categoryFilter === 'assemblies' || (categoryFilter === 'all' && !query)) return partTree;
    // A filter or a search lists the matching parts flat, so a hit nested
    // under a non-matching assembly still shows.
    return (parts ?? [])
      .filter((p) => matchesSearch(p, query))
      .filter((p) => categoryFilter === 'all'
        || (categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter))
      .map((p) => ({ part: p, children: [] }))
      .sort(comparePartNodes);
  }, [categoryFilter, query, partTree, parts, paintedIds]);
  const groups = useMemo(() => groupNodes(visibleNodes), [visibleNodes]);

  const isExpanded = (n: TreeNode) => expandOverride[n.part.id] ?? n.children.length > 0;
  const setExpanded = (partId: number, next: boolean) =>
    setExpandOverride((o) => ({ ...o, [partId]: next }));
  const toggleGroup = (key: GroupKey) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const filtered = categoryFilter !== 'all' || !!query;

  return (
    <div className="h-full flex flex-col min-h-0" data-testid="items-pane">
      <div className="flex-shrink-0 px-3 pt-3 pb-2 space-y-2 border-b border-slate-800">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
            Items ({visibleNodes.length}{filtered ? ` of ${parts?.length ?? 0}` : ''})
          </h2>
          <span className="text-[11px] text-slate-500">Drag onto a ★ sub-assembly to restructure</span>
        </div>
        <input
          type="search"
          aria-label="Search items"
          placeholder="Search number or name"
          value={search}
          disabled={categoryFilter === 'assemblies'}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-500 disabled:opacity-50"
        />
        <div className="flex flex-wrap gap-1">
          {[['all', 'All'], ...Object.entries(CATEGORY_META).map(([k, v]) => [k, `${v.icon} ${v.label}`]), ['assemblies', '🧩 Assemblies'], ['painted', `🎨 Painted (${paintedCount})`]].map(
            ([key, label]) => (
              <button
                key={key}
                onClick={() => setCategoryFilter(key)}
                className={`px-2 py-1 rounded text-xs font-medium transition ${
                  categoryFilter === key
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                }`}
              >
                {label}
              </button>
            )
          )}
        </div>
      </div>

      <div data-testid="items-scroll" className="flex-1 min-h-0 overflow-y-auto px-2 py-2">
        {categoryFilter === 'assemblies' ? (
          <AssemblyTreeList projectId={projectId} selectedPartId={selectedPartId} onSelect={onOpenPart} />
        ) : partsLoading ? (
          <p className="text-slate-500 text-sm">Loading...</p>
        ) : (parts?.length ?? 0) === 0 ? (
          <p className="text-slate-500 text-sm">No parts yet</p>
        ) : visibleNodes.length === 0 ? (
          <p className="text-slate-500 text-sm">No items match</p>
        ) : (
          <div className="space-y-2">
            {groups.map((g) => {
              const open = !collapsedGroups.has(g.key);
              return (
                <section key={g.key}>
                  <button
                    type="button"
                    data-testid={`group-toggle-${g.key}`}
                    aria-expanded={open}
                    onClick={() => toggleGroup(g.key)}
                    className="w-full flex items-center gap-2 px-1 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200"
                  >
                    <span className="w-3">{open ? '▾' : '▸'}</span>
                    <span>{g.label}</span>
                    <span className="text-slate-500 font-normal">{g.nodes.length}</span>
                  </button>
                  {open && (
                    <div className="space-y-0.5">
                      {g.nodes.map((node) => (
                        <ItemRow
                          key={node.part.id}
                          node={node}
                          projectCode={projectCode}
                          structure={structure}
                          paintByPartId={paintByPartId}
                          selectedPartId={selectedPartId}
                          isExpanded={isExpanded}
                          onSetExpanded={setExpanded}
                          onSelect={onSelect}
                          onContextMenu={onContextMenu}
                          onSelectRevision={onPickRevision}
                          draggingPartId={draggingPartId}
                          invalidDropIds={invalidDropIds}
                          onDragStartPart={setDraggingPartId}
                          onDragEndPart={() => setDraggingPartId(null)}
                          onDropOnPart={handleDropOnPart}
                        />
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
            {/* Top-level drop zone, visible while dragging a nested part */}
            {draggingPartId !== null &&
              parts?.find((p) => p.id === draggingPartId)?.parent_part_id != null && (
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setTopLevelDragOver(true);
                  }}
                  onDragLeave={() => setTopLevelDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setTopLevelDragOver(false);
                    if (draggingPartId !== null) {
                      reparentMutation.mutate({ partId: draggingPartId, parentPartId: null });
                      setDraggingPartId(null);
                    }
                  }}
                  className={`mt-2 px-3 py-3 rounded border-2 border-dashed text-center text-xs font-medium transition ${
                    topLevelDragOver
                      ? 'border-green-500 bg-green-900/30 text-green-300'
                      : 'border-slate-600 text-slate-400'
                  }`}
                >
                  Drop here to move to top level
                </div>
              )}
          </div>
        )}
      </div>
    </div>
  );
}
```

The page still renders `ItemsPane` inside the old grid; its `h-full` has no effect until Task 9 gives it a fixed-height parent.

- [ ] **Step 8: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/lib/partDisplay.test.ts src/components/project src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass. In particular the article test `tree rows expand to revisions and tools, and mark mirrors` still finds the Expand chevron, `tree-numbers-5`, `tree-rev-10`, `tree-rel-30`, and `tree-mirror-of-6` whose text contains `mirror of 20-1994-001-0` (screen-reader text).

- [ ] **Step 9: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/lib/partDisplay.ts frontend/src/lib/partDisplay.test.ts \
  frontend/src/components/project/projectTypes.ts frontend/src/components/project/itemGroups.ts \
  frontend/src/components/project/itemGroups.test.ts frontend/src/components/project/ItemRow.tsx \
  frontend/src/components/project/ItemsPane.tsx frontend/src/pages/ProjectDetailPage.layout.test.tsx \
  frontend/src/pages/ProjectDetailPage.files.test.tsx
git commit -F - <<'MSG'
feat(project-page): items grouped by category with search and slim two-line rows

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 9: Fixed-height page with a remembered splitter

**Files:**
- Create: `frontend/src/components/project/SplitPane.tsx`
- Create: `frontend/src/components/project/SplitPane.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (layout part of the return)
- Modify: `frontend/src/components/layout/AppLayout.tsx` (content column gets `min-w-0`)
- Modify: `frontend/src/pages/ProjectDetailPage.layout.test.tsx` (append)

**Interfaces:**
- Consumes: `readStoredNumber`, `writeStored` (Task 5).
- Produces:

```ts
export default function SplitPane(props: {
  storageKey: string;
  left: React.ReactNode;
  right: React.ReactNode;
  rightHidden?: boolean;   // Task 14 uses it for table mode
  defaultLeft?: number;    // 420
  minLeft?: number;        // 280
  minRight?: number;       // 420
}): JSX.Element
```
- Storage key: `plm2.project.splitLeft` (left pane width in px). DOM: `role="separator"` with `aria-label="Resize items list"` and `aria-valuenow` = width; page root `data-testid="project-page"`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/project/SplitPane.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import SplitPane from './SplitPane'

const mount = (rightHidden = false) =>
  render(<SplitPane storageKey="k" rightHidden={rightHidden} left={<div>left</div>} right={<div>right</div>} />)
const width = () => screen.getByRole('separator').getAttribute('aria-valuenow')

describe('SplitPane', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('starts at the default width', () => {
    mount()
    expect(width()).toBe('420')
    expect(screen.getByText('left')).toBeTruthy()
    expect(screen.getByText('right')).toBeTruthy()
  })

  it('follows a drag and remembers where it was dropped', () => {
    mount()
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 500 })
    fireEvent.mouseMove(window, { clientX: 530 })
    expect(width()).toBe('450')
    fireEvent.mouseUp(window, { clientX: 560 })
    expect(width()).toBe('480')
    expect(localStorage.getItem('k')).toBe('480')
    cleanup()
    mount()
    expect(width()).toBe('480')
  })

  it('never goes below the minimum width', () => {
    mount()
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 500 })
    fireEvent.mouseUp(window, { clientX: 0 })
    expect(width()).toBe('280')
  })

  it('moves with the arrow keys', () => {
    mount()
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowRight' })
    expect(width()).toBe('436')
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowLeft' })
    expect(width()).toBe('420')
  })

  it('treats garbage in storage as the default and clamps stored extremes', () => {
    localStorage.setItem('k', 'abc')
    mount()
    expect(width()).toBe('420')
    cleanup()
    localStorage.setItem('k', '99999')
    mount()
    expect(width()).toBe('1600')
    cleanup()
    localStorage.setItem('k', '-5')
    mount()
    expect(width()).toBe('280')
  })

  it('keeps working when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    mount()
    expect(width()).toBe('420')
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 500 })
    expect(() => fireEvent.mouseUp(window, { clientX: 560 })).not.toThrow()
    expect(width()).toBe('480')
  })

  it('hides the right pane and the splitter on request', () => {
    mount(true)
    expect(screen.queryByRole('separator')).toBeNull()
    expect(screen.queryByText('right')).toBeNull()
    expect(screen.getByText('left')).toBeTruthy()
  })
})
```

Append to `ProjectDetailPage.layout.test.tsx`:

```tsx
describe('fixed-height layout', () => {
  it('fills the viewport, never scrolls as a whole, and scrolls the list on its own', async () => {
    mount()
    const page = await screen.findByTestId('project-page')
    expect(page.className).toContain('h-full')
    expect(page.className).toContain('overflow-hidden')
    expect(screen.getByTestId('items-scroll').className).toContain('overflow-y-auto')
    expect(screen.getByRole('separator', { name: 'Resize items list' })).toBeTruthy()
  })

  it('opens with the splitter where it was left last time', async () => {
    localStorage.setItem('plm2.project.splitLeft', '520')
    mount()
    expect((await screen.findByRole('separator')).getAttribute('aria-valuenow')).toBe('520')
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project/SplitPane.test.tsx src/pages/ProjectDetailPage.layout.test.tsx -t "SplitPane|fixed-height"`
Expected: FAIL, `./SplitPane` does not resolve; the page has no `project-page`.

- [ ] **Step 3: Create `frontend/src/components/project/SplitPane.tsx`**

```tsx
/**
 * Two panes side by side with a draggable splitter. The left width is
 * remembered per browser; minimum widths keep both panes usable. Arrow keys
 * on the focused splitter move it too.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { readStoredNumber, writeStored } from '../../lib/safeStorage';

const MAX_LEFT = 1600;
const KEY_STEP = 16;

interface SplitPaneProps {
  storageKey: string;
  left: ReactNode;
  right: ReactNode;
  /** Hide the right pane and the splitter; the left pane takes the full width. */
  rightHidden?: boolean;
  defaultLeft?: number;
  minLeft?: number;
  minRight?: number;
}

export default function SplitPane({
  storageKey, left, right, rightHidden = false, defaultLeft = 420, minLeft = 280, minRight = 420,
}: SplitPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(() => readStoredNumber(storageKey, defaultLeft, minLeft, MAX_LEFT));
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const clamp = useCallback((w: number) => {
    const total = containerRef.current?.getBoundingClientRect().width ?? 0;
    // A container that has not been laid out (or jsdom) reports 0: only the fixed bounds apply then.
    const max = total > 0 ? Math.max(minLeft, total - minRight) : MAX_LEFT;
    return Math.round(Math.min(max, Math.max(minLeft, w)));
  }, [minLeft, minRight]);

  const commit = useCallback((w: number) => {
    const next = clamp(w);
    setWidth(next);
    writeStored(storageKey, String(next));
  }, [clamp, storageKey]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!drag.current) return;
      setWidth(clamp(drag.current.startWidth + e.clientX - drag.current.startX));
    };
    const onUp = (e: MouseEvent) => {
      if (!drag.current) return;
      const { startWidth, startX } = drag.current;
      drag.current = null;
      document.body.style.userSelect = '';
      commit(startWidth + e.clientX - startX);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [clamp, commit]);

  return (
    <div ref={containerRef} className="h-full min-h-0 flex" data-testid="split-pane">
      <div
        className={`h-full min-h-0 min-w-0 ${rightHidden ? 'flex-1' : 'flex-shrink-0'}`}
        style={rightHidden ? undefined : { width, minWidth: minLeft, maxWidth: `calc(100% - ${minRight}px)` }}
      >
        {left}
      </div>
      {!rightHidden && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize items list"
            aria-valuenow={width}
            aria-valuemin={minLeft}
            tabIndex={0}
            onMouseDown={(e) => {
              e.preventDefault();
              drag.current = { startX: e.clientX, startWidth: width };
              document.body.style.userSelect = 'none';
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.preventDefault();
                commit(width + (e.key === 'ArrowRight' ? KEY_STEP : -KEY_STEP));
              }
            }}
            className="w-1.5 flex-shrink-0 cursor-col-resize bg-slate-800 hover:bg-sky-600/60 focus:bg-sky-600/60 focus:outline-none"
          />
          <div className="flex-1 min-w-0 h-full min-h-0">{right}</div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Make the page fill the viewport**

In `frontend/src/components/layout/AppLayout.tsx` change the content column to:

```tsx
      <div className="flex-1 min-w-0 overflow-auto">{children}</div>
```

In `frontend/src/pages/ProjectDetailPage.tsx`: add `import SplitPane from '../components/project/SplitPane';`, add below the imports

```tsx
const SPLIT_KEY = 'plm2.project.splitLeft';
```

and replace the returned layout (from the root `<div className="p-6 bg-slate-900 min-h-screen">` down to and including the closing `</div>` of the `grid grid-cols-3` block) with:

```tsx
    <div data-testid="project-page" className="h-full flex flex-col overflow-hidden bg-slate-900">
      <ProjectHeaderBar
        project={project}
        onOpenSection={setOpenSection}
        onStartChange={() => setShowStartChange(true)}
        onAddPart={() => setShowAddModal(true)}
      />
      <StatusSlideOver section={openSection} projectId={id} onClose={closeSection} />

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <div className="flex-1 min-h-0">
        <SplitPane
          storageKey={SPLIT_KEY}
          left={
            <ItemsPane
              projectId={id}
              projectCode={project.code}
              parts={parts}
              partsLoading={partsLoading}
              structure={structure}
              paintByPartId={paintByPartId}
              paintedIds={paintedIds}
              paintedCount={paintOverview?.length ?? 0}
              selectedPartId={sel.partId}
              onSelect={selectPart}
              onOpenPart={openPart}
              onPickRevision={pickRevision}
              onContextMenu={handleContextMenu}
            />
          }
          right={
            // Until Task 10 pins the detail header, the whole detail column scrolls.
            <div data-testid="detail-column" className="h-full min-h-0 overflow-y-auto p-4 space-y-4" onClick={() => selectPart(null)}>
              <DetailPane
                projectId={id}
                project={project}
                parts={parts}
                structure={structure}
                sel={sel}
                onShowChangelog={setChangelogPartId}
              />
            </div>
          }
        />
      </div>
```

The context menu, changelog modal and add-part modal stay after this block, inside the root `div`, as before.

- [ ] **Step 5: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/project/SplitPane.tsx frontend/src/components/project/SplitPane.test.tsx \
  frontend/src/pages/ProjectDetailPage.tsx frontend/src/components/layout/AppLayout.tsx \
  frontend/src/pages/ProjectDetailPage.layout.test.tsx
git commit -F - <<'MSG'
feat(project-page): fixed-height page with independently scrolling panes and a remembered splitter

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 10: Detail as tabs under a pinned header

**Files:**
- Create: `frontend/src/components/project/detailTabs.ts`
- Create: `frontend/src/components/project/DetailHeader.tsx`
- Create: `frontend/src/components/project/DocumentsTab.tsx`
- Modify: `frontend/src/components/project/DetailPane.tsx` (full replacement)
- Modify: `frontend/src/components/project/ChangelogModal.tsx` (add `ChangelogList`)
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.article.test.tsx` (first test clicks the Links tab)
- Modify: `frontend/src/pages/ProjectDetailPage.layout.test.tsx` (append; add `waitFor` to the testing-library import)

**Interfaces:**
- Consumes: `ArticleSelection` (Task 4), `useRevisionFiles`, `useAssemblyFiles`, `BomTreeSection`, `projectTypes` helpers.
- Produces:

```ts
// detailTabs.ts
export type DetailTab = 'documents' | 'links' | 'bom' | 'workflow' | 'changelog';
export const DETAIL_TABS: { key: DetailTab; label: string }[];
// DetailPane.tsx
export interface DetailPaneProps {
  projectId: number; project: Project; parts: Part[] | undefined; structure: ProjectStructure | undefined;
  sel: ArticleSelection; tab: DetailTab; onTabChange(tab: DetailTab): void;
  onPopOut?: () => void;   // Task 14 passes it; no button when undefined
  emptyText?: string;      // shown when no part is selected; default 'Select an item from the list'
}
// DetailHeader.tsx
export default function DetailHeader(props: { projectId: number; part: Part; article: StructureArticle | undefined; sel: ArticleSelection; onPopOut?: () => void }): JSX.Element
// DocumentsTab.tsx
export default function DocumentsTab(props: { projectId: number; project: Project; parts: Part[] | undefined; structure: ProjectStructure | undefined; sel: ArticleSelection; part: Part }): JSX.Element
// ChangelogModal.tsx
export function ChangelogList(props: { partId: number }): JSX.Element
```
- DOM: `detail-pane` (root, does not scroll), `detail-header`, `role="tablist"` named "Detail sections", tabs `detail-tab-<key>` with `aria-selected`, `detail-scroll` (the only scrolling element), `detail-phase`, `detail-active-revision`; the ⧉ button has `aria-label="Open detail in new window"`.

Tab contents (existing components, unchanged inside):
- Documents: `DocumentsTab` = revision strip, document pane, grouped files, upload drop zone, customer data and customer package entry points.
- Links: relation chips (`relation-chip-<id>`, mirrored-by chips) and `PartRelationsSection`.
- BOM: `BomTreeSection` and `PartBOMSection` (not for purchased parts).
- Workflow: revisions list, `RevisionWorkflowSection`, `ProcessFlowSection` (non-articles), `PPAPSection` (articles).
- Changelog: `ChangelogList` (was only a modal; the context menu keeps the modal).

- [ ] **Step 1: Write the failing tests**

Change the `@testing-library/react` import of `ProjectDetailPage.layout.test.tsx` to `import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'` and append:

```tsx
describe('detail tabs under a pinned header', () => {
  const selectLH = async () => {
    fireEvent.click(await screen.findByTestId('item-row-5'))
    return screen.findByTestId('detail-header')
  }

  it('pins header and tab bar while only the tab content scrolls', async () => {
    mount()
    const header = await selectLH()
    expect(header.textContent).toContain('206.882.251 Handle LH')
    expect(within(header).getByText('internal mfg')).toBeTruthy()
    expect((await within(header).findByTestId('detail-active-revision')).textContent).toBe('E1 · 003')
    expect(within(header).getByTestId('detail-phase').textContent).toBe('nominated')
    expect(screen.getByRole('tablist', { name: 'Detail sections' })).toBeTruthy()
    expect(screen.getByTestId('detail-scroll').className).toContain('overflow-y-auto')
    expect(screen.getByTestId('detail-pane').className).not.toContain('overflow-y-auto')
    expect(await screen.findByTestId('rev-tab-9')).toBeTruthy()

    fireEvent.click(screen.getByTestId('detail-tab-links'))
    expect(screen.queryByTestId('rev-tab-9')).toBeNull()
    expect(screen.getByTestId('detail-header')).toBe(header)
    expect(screen.getByTestId('relation-chip-30')).toBeTruthy()
    expect(screen.getByText('relations-section')).toBeTruthy()
  })

  it('shows the existing sections under BOM, Workflow and Changelog', async () => {
    mount()
    await selectLH()
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByTestId('detail-tab-bom'))
    expect(await screen.findByTestId('bom-tree-section')).toBeTruthy()
    expect(screen.getByText('bom-section')).toBeTruthy()
    fireEvent.click(screen.getByTestId('detail-tab-workflow'))
    expect(screen.getByText('workflow-section')).toBeTruthy()
    expect(screen.getByText('ppap-section')).toBeTruthy()
    fireEvent.click(screen.getByTestId('detail-tab-changelog'))
    expect(await screen.findByText('No changelog entries yet')).toBeTruthy()
  })

  it('keeps the selected tab when switching items', async () => {
    mount()
    await selectLH()
    fireEvent.click(screen.getByTestId('detail-tab-bom'))
    fireEvent.click(screen.getByTestId('item-row-6'))
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle RH'))
    expect(screen.getByTestId('detail-tab-bom').getAttribute('aria-selected')).toBe('true')
  })

  it('shows a prompt instead of an empty pane when nothing is selected', async () => {
    mount()
    expect(await screen.findByText('Select an item from the list')).toBeTruthy()
  })
})
```

In `ProjectDetailPage.article.test.tsx`, first test (`shows the revision strip with the proposal nested, grouped files and relation chips`): relation chips moved to the Links tab. Replace

```tsx
    expect(screen.getByTestId('relation-chip-30').textContent).toContain('199401')
```

with

```tsx
    fireEvent.click(screen.getByTestId('detail-tab-links'))
    expect(screen.getByTestId('relation-chip-30').textContent).toContain('199401')
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ProjectDetailPage.layout.test.tsx src/pages/ProjectDetailPage.article.test.tsx`
Expected: FAIL on `detail-header` / `detail-tab-links` not found.

- [ ] **Step 3: Create `frontend/src/components/project/detailTabs.ts`**

```ts
/** The detail pane's tabs, in display order. */
export type DetailTab = 'documents' | 'links' | 'bom' | 'workflow' | 'changelog';

export const DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: 'documents', label: 'Documents' },
  { key: 'links', label: 'Links' },
  { key: 'bom', label: 'BOM' },
  { key: 'workflow', label: 'Workflow' },
  { key: 'changelog', label: 'Changelog' },
];
```

- [ ] **Step 4: Add `ChangelogList` to `frontend/src/components/project/ChangelogModal.tsx`**

Add above `ChangelogModal`:

```tsx
export function ChangelogList({ partId }: { partId: number }) {
  const { data: entries, isLoading } = useChangelog(partId);
  if (isLoading) return <p className="text-slate-400 text-sm">Loading...</p>;
  if (!entries || entries.length === 0) return <p className="text-slate-500 text-sm">No changelog entries yet</p>;
  return (
    <div className="space-y-2">
      {[...entries].reverse().map((entry) => (
        <div key={entry.id} className="p-3 bg-slate-700/50 rounded border border-slate-600 text-sm">
          <div className="flex items-center justify-between">
            <span className="px-2 py-0.5 rounded text-xs font-medium bg-slate-600 text-slate-200">
              {entry.action.replace(/_/g, ' ')}
            </span>
            <span className="text-slate-500 text-xs">
              {new Date(entry.performed_at).toLocaleString()}
            </span>
          </div>
          <p className="text-slate-200 mt-1.5">{entry.action_description}</p>
          {entry.performed_by_user && (
            <p className="text-slate-500 text-xs mt-1">by {entry.performed_by_user}</p>
          )}
        </div>
      ))}
    </div>
  );
}
```

and in `ChangelogModal` replace the whole `<div className="overflow-y-auto space-y-2"> ... </div>` block (the loading / empty / entries ternary) with:

```tsx
        <div className="overflow-y-auto">
          <ChangelogList partId={partId} />
        </div>
```

and remove the now unused `const { data: entries, isLoading } = useChangelog(partId);` line from `ChangelogModal`.

- [ ] **Step 5: Create `frontend/src/components/project/DetailHeader.tsx`**

```tsx
/**
 * Pinned detail header: name, numbers, phase, active revision, type and
 * category, mirror link, gauge calibration, and the part actions. It never
 * scrolls; the tab content below it does.
 */
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { revisionLabel } from '../parts/RevisionBadge';
import { apiErrorMessage } from '../../lib/apiError';
import type { StructureArticle } from '../../hooks/queries/useProjectStructure';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { CATEGORY_META, typeColor, type Part } from './projectTypes';

export default function DetailHeader({ projectId, part, article, sel, onPopOut }: {
  projectId: number;
  part: Part;
  article: StructureArticle | undefined;
  sel: ArticleSelection;
  onPopOut?: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const markCalibratedMutation = useMutation({
    mutationFn: async (partId: number) => {
      await client.put(`/v1/parts/${partId}`, { last_calibrated_at: new Date().toISOString() });
    },
    onSuccess: () => {
      toast.success('Calibration recorded');
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to record calibration'));
    },
  });

  const activeRevision = sel.partRevisions?.find((r) => r.id === part.active_revision_id);
  const phase = article?.lifecycle_phase ?? part.lifecycle_phase;
  const category = CATEGORY_META[part.item_category];
  const overdue = !!part.next_calibration_due && new Date(part.next_calibration_due) < new Date();
  const facts = [
    part.supplier ? `Supplier: ${part.supplier}` : null,
    part.data_classification ? `Classification: ${part.data_classification}` : null,
  ].filter(Boolean).join(' · ');

  return (
    <div data-testid="detail-header" className="flex-shrink-0 px-4 py-3 border-b border-slate-700 bg-slate-800">
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 truncate text-lg font-bold text-slate-100">{part.name}</h2>
        <div className="flex gap-2 flex-shrink-0">
          {onPopOut && (
            <button
              aria-label="Open detail in new window"
              title="Open detail in new window"
              onClick={onPopOut}
              className="px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs"
            >
              ⧉
            </button>
          )}
          <button
            onClick={() => navigate(`/parts/${part.id}`)}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium"
          >
            Revisions & Lifecycle →
          </button>
        </div>
      </div>
      <div className="text-slate-400 text-sm mt-1 flex items-center gap-2 flex-wrap">
        <span className="font-mono">{part.part_number}</span>
        {part.customer_part_number && <span className="font-mono" title="Customer (OEM) part number">{part.customer_part_number}</span>}
        {part.tier1_part_number && <span className="font-mono" data-testid="selected-tier1-number" title="Tier 1 part number">Tier 1 {part.tier1_part_number}</span>}
        {phase && <span data-testid="detail-phase" className="text-xs text-slate-300">{phase}</span>}
        {activeRevision && (
          <span data-testid="detail-active-revision" title="Active revision" className="px-1.5 py-0.5 rounded bg-slate-700 text-xs text-slate-200 font-mono">
            {revisionLabel(activeRevision.revision_name, activeRevision.customer_index)}
          </span>
        )}
        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${typeColor(part.part_type)}`}>
          {part.part_type.replace(/_/g, ' ')}
        </span>
        {category && (
          <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${category.badge}`}>
            {category.icon} {category.label}
          </span>
        )}
        {article?.mirror_of && (
          <button data-testid="mirror-chip" onClick={() => sel.openPart(article.mirror_of!.part_id)}
            className="px-2 py-0.5 rounded border border-red-500 text-red-300 text-xs">
            ⇄ Mirror of {article.mirror_of.customer_part_number ?? article.mirror_of.part_number} · data on that part
          </button>
        )}
      </div>
      {part.item_category === 'gauge' && (
        <div className="mt-2 flex items-center gap-3 text-sm">
          {part.next_calibration_due ? (
            <span className={overdue ? 'text-red-400 font-medium' : 'text-slate-300'}>
              📏 Calibration due {new Date(part.next_calibration_due).toLocaleDateString()}
              {overdue && ' (overdue)'}
            </span>
          ) : (
            <span className="text-amber-400">📏 No calibration recorded</span>
          )}
          <button
            onClick={() => markCalibratedMutation.mutate(part.id)}
            disabled={markCalibratedMutation.isPending}
            className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium"
          >
            {markCalibratedMutation.isPending ? 'Saving...' : 'Mark calibrated today'}
          </button>
        </div>
      )}
      {facts && <p className="text-slate-500 text-xs mt-1">{facts}</p>}
    </div>
  );
}
```

- [ ] **Step 6: Create `frontend/src/components/project/DocumentsTab.tsx`**

This is the old "Revision Files & CAD Viewer" card from `DetailPane`, with its state and mutations, reading the selection from `sel`. The file list no longer has its own `max-h-56 overflow-y-auto` box: the tab body scrolls, so there is one scroll area.

```tsx
/**
 * Documents tab: revision strip, document pane (drawing / 3D), grouped files,
 * uploads, and the customer data / customer package entry points.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client, { API_BASE_URL } from '../../api/client';
import Viewer3D from '../Viewer3D';
import UploadDialog from '../parts/UploadDialog';
import CustomerDataDialog, { type CustomerDataInput } from '../parts/CustomerDataDialog';
import CustomerPackageDialog from '../parts/CustomerPackageDialog';
import RevisionStrip from '../parts/RevisionStrip';
import DocumentPane, { type PaneDocument, type MirrorNotice } from '../parts/DocumentPane';
import RevisionFilesGrouped, { docKindFor } from '../parts/RevisionFilesGrouped';
import { revisionLabel } from '../parts/RevisionBadge';
import { apiErrorMessage } from '../../lib/apiError';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useAssemblyFiles, useRevisionFiles } from '../../hooks/queries/useProjectDetail';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { LOCKED_REVISION_STATUSES, type Part, type Project } from './projectTypes';

export default function DocumentsTab({ projectId, project, parts, structure, sel, part }: {
  projectId: number;
  project: Project;
  parts: Part[] | undefined;
  structure: ProjectStructure | undefined;
  sel: ArticleSelection;
  part: Part;
}) {
  const queryClient = useQueryClient();
  const partRevisions = sel.partRevisions;
  const hasRevisions = !!partRevisions && partRevisions.length > 0;
  const { data: revisionFiles } = useRevisionFiles(sel.revisionId || 0);
  const article = articleOf(structure, part.id);
  const mirrorSource = article?.mirror_of ? articleOf(structure, article.mirror_of.part_id) : undefined;
  const mirrorFiles = useRevisionFiles(mirrorSource?.active_revision_id ?? 0);

  const isSubAssembly = part.part_type === 'sub_assembly';
  const { data: assemblyFiles } = useAssemblyFiles(isSubAssembly ? part.id : 0);
  const assemblyAvailable = isSubAssembly && (assemblyFiles?.length ?? 0) > 1;
  const assemblyActive = assemblyAvailable && sel.viewingFileId === null;
  const assemblyModels = useMemo(
    () =>
      assemblyFiles?.map((f) => ({
        id: f.file_id,
        url: `${API_BASE_URL}/v1/parts/revision-files/${f.file_id}/viewer`,
        label: f.uploaded_by_name
          ? `${f.part_name} (${f.revision_name}) · ${f.uploaded_by_name}`
          : `${f.part_name} (${f.revision_name})`,
      })),
    [assemblyFiles]
  );

  const [showCustomerData, setShowCustomerData] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[] | null>(null);
  const [uploadDrag, setUploadDrag] = useState(false);

  const customerDataMutation = useMutation({
    mutationFn: async (v: CustomerDataInput) => {
      const res = await client.post(`/v1/parts/${part.id}/revisions/customer-data`, v);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Recorded ${data.revision_name}`);
      setShowCustomerData(false);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to record customer data'));
    },
  });

  const proposalMutation = useMutation({
    mutationFn: async (parentRevisionId: number) => {
      const res = await client.post(`/v1/parts/${part.id}/revisions/proposals`, { parent_revision_id: parentRevisionId });
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}`);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
      sel.selectRevision(data.id);
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to create proposal'));
    },
  });

  const afterUpload = (targetRevisionId: number) => {
    queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
    queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
    queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
    sel.setRevisionId(targetRevisionId);
  };

  const selectedRevision = partRevisions?.find((r) => r.id === sel.revisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const viewableFiles = revisionFiles?.filter((f) => f.has_viewer) ?? [];
  const viewingFile = viewableFiles.find((f) => f.id === sel.viewingFileId) ?? viewableFiles[0] ?? null;
  const viewerUrl = viewingFile
    ? `${API_BASE_URL}/v1/parts/revision-files/${viewingFile.id}/viewer`
    : null;

  const openDoc = revisionFiles?.find((f) => f.id === sel.openDocId) ?? null;
  const revName = selectedRevision ? revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index) : '';
  let paneDoc: PaneDocument | null = null;
  let paneMirror: MirrorNotice | null = null;
  if (openDoc) {
    const kind = docKindFor(openDoc);
    if (kind) paneDoc = { fileId: openDoc.id, filename: openDoc.filename, kind, revisionName: revName };
  } else if (viewingFile || assemblyActive) paneDoc = { fileId: viewingFile?.id ?? 0, filename: assemblyActive ? 'Assembly' : viewingFile!.filename, kind: '3d', revisionName: revName };
  else if (article?.mirror_of && mirrorSource) {
    const src = mirrorFiles.data ?? [];
    const pick = src.find((f) => f.has_viewer) ?? src.find((f) => f.file_type === 'drawing' && docKindFor(f)) ?? null;
    const sourceActiveRev = mirrorSource.revisions.find((r) => r.is_active);
    const sourceRevName = sourceActiveRev
      ? revisionLabel(sourceActiveRev.revision_name, sourceActiveRev.customer_index)
      : mirrorSource.part_number;
    if (pick) {
      const kind = pick.has_viewer ? '3d' : docKindFor(pick);
      if (kind) paneDoc = { fileId: pick.id, filename: pick.filename, kind, revisionName: sourceRevName };
    }
    paneMirror = { sourcePartId: mirrorSource.part_id, sourceNumber: mirrorSource.customer_part_number ?? mirrorSource.part_number, sourceName: mirrorSource.name };
  }
  const paneViewerUrl = paneMirror && paneDoc?.kind === '3d' ? `${API_BASE_URL}/v1/parts/revision-files/${paneDoc.fileId}/viewer` : viewerUrl;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 bg-slate-700/30">
        <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
          {article ? `${article.part_number} · ${article.name} · ${article.lifecycle_phase}` : 'Files & 3D Model'}
        </h3>
        <div className="flex items-center gap-2">
          {revisionLocked && (
            <span className="text-xs text-amber-400" title="This revision is locked; files are read-only">🔒 {selectedRevision?.status}</span>
          )}
          <button onClick={() => setShowPackage(true)}
            className="bg-blue-700 hover:bg-blue-600 border border-blue-600 rounded px-2 py-1 text-white text-xs font-medium">+ Customer package</button>
        </div>
      </div>
      {hasRevisions && (
        <div className="border-b border-slate-700 bg-slate-800/60">
          <RevisionStrip
            revisions={partRevisions!}
            selectedId={sel.revisionId}
            activeId={part.active_revision_id}
            onSelect={sel.selectRevision}
            onNewProposal={(majorId) => proposalMutation.mutate(majorId)}
          />
        </div>
      )}

      {showPackage && (
        <CustomerPackageDialog open assemblyId={part.id}
          projectParts={(parts ?? []).map((p) => ({ id: p.id, part_number: p.part_number, name: p.name }))}
          officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
          onClose={() => setShowPackage(false)}
          onDone={(r) => {
            toast.success(`Stored ${r.created.length} new, kept ${r.kept.length}`);
            setShowPackage(false);
            queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
            queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
            queryClient.invalidateQueries({ queryKey: ['bom-tree'] });
            queryClient.invalidateQueries({ queryKey: ['project-assemblies', projectId] });
            queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
          }} />
      )}

      {!hasRevisions ? (
        <div className="p-6 text-center">
          {article?.mirror_of && (
            <div className="mb-4 text-left">
              <DocumentPane document={paneDoc} mirror={paneMirror} onOpenPart={sel.openPart}>
                <Viewer3D fileId={paneDoc?.fileId ?? null} viewerUrl={paneViewerUrl} />
              </DocumentPane>
            </div>
          )}
          <p className="text-slate-400 text-sm mb-3">
            Files are managed per revision. Record the first customer data to upload files.
          </p>
          <button
            onClick={() => setShowCustomerData(true)}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
          >
            + Customer data
          </button>
          {showCustomerData && (() => {
            const majorsOf = (revs: { revision_name: string }[]) => revs.filter((r) => !r.revision_name.includes('.'));
            const revs = partRevisions || [];
            const nextMajor = {
              review: Math.max(0, ...majorsOf(revs).filter((r) => r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name.slice(1), 10))) + 1,
              official: Math.max(0, ...majorsOf(revs).filter((r) => !r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name, 10))) + 1,
            };
            return (
              <CustomerDataDialog open title="Customer data received" nextMajor={nextMajor}
                pending={customerDataMutation.isPending} onClose={() => setShowCustomerData(false)}
                onSubmit={(v) => customerDataMutation.mutate(v)} />
            );
          })()}
        </div>
      ) : (
        <>
          {/* Document pane: openDoc (Open) -> 3D viewer -> mirror fallback -> none */}
          <DocumentPane document={paneDoc} mirror={paneMirror} onOpenPart={sel.openPart}>
            <Viewer3D
              fileId={assemblyActive ? null : paneDoc?.fileId ?? null}
              viewerUrl={assemblyActive ? null : paneViewerUrl}
              models={assemblyActive ? assemblyModels : undefined}
            />
            {assemblyActive && (
              <div className="absolute top-2 right-2 z-10 px-2 py-1 rounded bg-blue-900/70 text-blue-200 text-xs font-medium">
                Assembly · {assemblyFiles?.length} components
              </div>
            )}
            {assemblyAvailable && !assemblyActive && (
              <button
                onClick={() => sel.setViewingFileId(null)}
                className="absolute top-2 right-2 z-10 px-2 py-1 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-200 text-xs font-medium"
              >
                ← Assembly view
              </button>
            )}
          </DocumentPane>
          {/* Files list + uploader */}
          <div className="p-2 bg-slate-700/50 space-y-1">
            <RevisionFilesGrouped
              files={revisionFiles ?? []}
              locked={revisionLocked}
              viewingFileId={viewingFile?.id ?? null}
              revisionName={revName}
              onView={(f) => { sel.setViewingFileId(f.id); sel.setOpenDocId(null); }}
              onOpen={(f) => sel.setOpenDocId(f.id)}
            />
            {!revisionLocked && sel.revisionId && (
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
            )}
          </div>
          {uploadFiles && selectedRevision && (
            <UploadDialog
              open
              partId={part.id}
              currentRevision={{ id: selectedRevision.id, revision_name: selectedRevision.revision_name,
                customer_index: selectedRevision.customer_index, phase: selectedRevision.phase }}
              revisionNames={(partRevisions ?? []).map((r) => r.revision_name)}
              officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
              projectNaming={project.customer_naming ?? null}
              initialFiles={uploadFiles}
              onClose={(targetRevisionId) => {
                setUploadFiles(null);
                if (targetRevisionId != null) afterUpload(targetRevisionId);
              }}
              onDone={(targetRevisionId) => {
                setUploadFiles(null);
                afterUpload(targetRevisionId);
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Replace `frontend/src/components/project/DetailPane.tsx`**

```tsx
/**
 * DetailPane - the selected item. A pinned header and tab bar; only the tab
 * content below them scrolls. Used by the project page and the pop-out
 * detail window.
 */
import RevisionWorkflowSection from '../workflows/RevisionWorkflowSection';
import PartBOMSection from '../PartBOMSection';
import PartRelationsSection from '../PartRelationsSection';
import ProcessFlowSection from '../ProcessFlowSection';
import PPAPSection from '../PPAPSection';
import { revisionLabel } from '../parts/RevisionBadge';
import { stripProjectCode } from '../../lib/partDisplay';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useRevisionFiles } from '../../hooks/queries/useProjectDetail';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { BomTreeSection } from './BomTreeSection';
import { ChangelogList } from './ChangelogModal';
import DetailHeader from './DetailHeader';
import DocumentsTab from './DocumentsTab';
import { DETAIL_TABS, type DetailTab } from './detailTabs';
import {
  CATEGORY_META, LOCKED_REVISION_STATUSES, phaseColor, statusColor, type Part, type Project,
} from './projectTypes';

export interface DetailPaneProps {
  projectId: number;
  project: Project;
  parts: Part[] | undefined;
  structure: ProjectStructure | undefined;
  sel: ArticleSelection;
  tab: DetailTab;
  onTabChange(tab: DetailTab): void;
  onPopOut?: () => void;
  emptyText?: string;
}

export default function DetailPane({
  projectId, project, parts, structure, sel, tab, onTabChange, onPopOut,
  emptyText = 'Select an item from the list',
}: DetailPaneProps) {
  const { data: revisionFiles } = useRevisionFiles(sel.revisionId || 0);
  const part = parts?.find((p) => p.id === sel.partId);

  if (!part) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-slate-500" data-testid="detail-empty">
        {emptyText}
      </div>
    );
  }

  const article = articleOf(structure, part.id);
  const selectedRevision = sel.partRevisions?.find((r) => r.id === sel.revisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const revName = revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index);
  const hasLinks = !!article && (article.related.length > 0 || !!article.mirror_of || article.mirrored_by.length > 0);

  return (
    <div data-testid="detail-pane" className="h-full min-h-0 flex flex-col bg-slate-900" onClick={(e) => e.stopPropagation()}>
      <DetailHeader projectId={projectId} part={part} article={article} sel={sel} onPopOut={onPopOut} />

      <div role="tablist" aria-label="Detail sections" className="flex-shrink-0 flex gap-1 px-3 border-b border-slate-700 bg-slate-800/60">
        {DETAIL_TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            data-testid={`detail-tab-${t.key}`}
            aria-selected={tab === t.key}
            onClick={() => onTabChange(t.key)}
            className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px ${
              tab === t.key ? 'border-sky-400 text-sky-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" data-testid="detail-scroll" className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {tab === 'documents' && (
          <DocumentsTab projectId={projectId} project={project} parts={parts} structure={structure} sel={sel} part={part} />
        )}

        {tab === 'links' && (
          <>
            {hasLinks && (
              <div className="flex flex-wrap gap-1">
                {article!.related.map((r) => (
                  <button key={`${r.relation_type}-${r.part_id}`} data-testid={`relation-chip-${r.part_id}`}
                    onClick={() => sel.openPart(r.part_id)}
                    className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-xs text-slate-200">
                    <span className="text-slate-400">{r.label}</span> {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, project.code)}
                  </button>
                ))}
                {article!.mirrored_by.map((m) => (
                  <button key={m.part_id} onClick={() => sel.openPart(m.part_id)}
                    className="px-2 py-0.5 rounded border border-red-700 text-xs text-red-300">
                    ⇄ mirrored by {m.part_number}
                  </button>
                ))}
              </div>
            )}
            <PartRelationsSection
              partId={part.id}
              itemCategory={part.item_category}
              projectParts={parts ?? []}
              onSelectPart={sel.selectPart}
            />
          </>
        )}

        {tab === 'bom' && (
          sel.revisionId ? (
            <>
              <BomTreeSection partId={part.id} revisionId={sel.revisionId} revisionName={revName} onOpenPart={sel.openPart} />
              {part.part_type !== 'purchased' && (
                <PartBOMSection
                  partId={part.id}
                  revisionId={sel.revisionId}
                  revisionName={revName}
                  locked={revisionLocked}
                  projectParts={parts ?? []}
                />
              )}
            </>
          ) : (
            <p className="text-slate-500 text-sm">No revision yet, so no BOM.</p>
          )
        )}

        {tab === 'workflow' && (
          <>
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
              <h3 className="text-sm font-semibold text-slate-200 mb-3">Revisions</h3>
              {!sel.partRevisions || sel.partRevisions.length === 0 ? (
                <p className="text-slate-500 text-sm">No revisions yet</p>
              ) : (
                <div className="space-y-2">
                  {sel.partRevisions.map((rev) => (
                    <div
                      key={rev.id}
                      onClick={() => sel.selectRevision(rev.id)}
                      className={`p-3 rounded border cursor-pointer transition ${
                        rev.id === sel.revisionId
                          ? 'bg-blue-900/30 border-blue-600'
                          : 'bg-slate-700/50 border-slate-600 hover:bg-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono font-semibold text-slate-100 text-sm">{revisionLabel(rev.revision_name, rev.customer_index)}</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${phaseColor(rev.phase)}`}>
                          {rev.phase}{rev.part_phase_at_receipt ? ` · ${rev.part_phase_at_receipt}` : ''}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className={statusColor(rev.status)}>{rev.status.replace(/_/g, ' ')}</span>
                        <span className="text-slate-500">{new Date(rev.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {sel.revisionId && <RevisionWorkflowSection revisionId={sel.revisionId} revisionName={revName} />}
            {part.item_category !== 'article' && (
              <ProcessFlowSection partId={part.id} onSelectPart={sel.selectPart} />
            )}
            {sel.revisionId && part.item_category === 'article' && (
              <PPAPSection
                revisionId={sel.revisionId}
                revisionName={revName}
                revisionFiles={(revisionFiles ?? []).map((f) => ({ id: f.id, filename: f.filename }))}
              />
            )}
          </>
        )}

        {tab === 'changelog' && <ChangelogList partId={part.id} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Wire the page**

In `ProjectDetailPage.tsx`:
1. Add `import type { DetailTab } from '../components/project/detailTabs';` and, with the other `useState`s above the early returns, `const [detailTab, setDetailTab] = useState<DetailTab>('documents');`.
2. Replace the `right={...}` element of the `SplitPane` with:

```tsx
          right={
            <div data-testid="detail-column" className="h-full min-h-0" onClick={() => selectPart(null)}>
              <DetailPane
                projectId={id}
                project={project}
                parts={parts}
                structure={structure}
                sel={sel}
                tab={detailTab}
                onTabChange={setDetailTab}
              />
            </div>
          }
```

The context menu's "View Changelog" keeps using `setChangelogPartId` and the modal.

- [ ] **Step 9: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/pages && npx tsc --noEmit`
Expected: all pass. Watch the article tests: mirror banner, `Open` on the drawing, `+ Proposal`, and the race-guard test all run in the default Documents tab.

- [ ] **Step 10: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/project/detailTabs.ts frontend/src/components/project/DetailHeader.tsx \
  frontend/src/components/project/DocumentsTab.tsx frontend/src/components/project/DetailPane.tsx \
  frontend/src/components/project/ChangelogModal.tsx frontend/src/pages/ProjectDetailPage.tsx \
  frontend/src/pages/ProjectDetailPage.article.test.tsx frontend/src/pages/ProjectDetailPage.layout.test.tsx
git commit -F - <<'MSG'
feat(project-page): detail as tabs under a pinned header, tab kept across items

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 11: Keyboard navigation in the items list

**Files:**
- Modify: `frontend/src/components/project/itemGroups.ts` (add `findNode`)
- Modify: `frontend/src/components/project/itemGroups.test.ts` (append)
- Modify: `frontend/src/components/project/ItemsPane.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.layout.test.tsx` (append)

**Interfaces:**
- Consumes: `visibleOrder` (Task 8), `articleOf`.
- Produces: `export function findNode(nodes: TreeNode[], partId: number): TreeNode | undefined` in `itemGroups.ts`. The list scroll container (`items-scroll`) becomes focusable (`tabIndex=0`, `aria-label="Items"`) and handles ArrowUp / ArrowDown / ArrowRight / ArrowLeft.

Rules: Up/Down walk `visibleOrder` (open groups, expanded children). With nothing selected, or with the selection not visible (collapsed group, filtered out), Down goes to the first row and Up to the last. Right expands and Left collapses the selected row when it is expandable. Keys from `input`, `select` or `textarea` elements are ignored. The newly selected row is scrolled into view.

- [ ] **Step 1: Write the failing tests**

Append to `itemGroups.test.ts` (add `findNode` to its import):

```ts
describe('findNode', () => {
  it('finds nested nodes and returns undefined for unknown ids', () => {
    const child = node(part(11))
    const tree = [node(part(1)), node(part(10), [child])]
    expect(findNode(tree, 11)).toBe(child)
    expect(findNode(tree, 99)).toBeUndefined()
  })
})
```

Append to `ProjectDetailPage.layout.test.tsx`:

```tsx
describe('keyboard in the items list', () => {
  const current = () => screen.getAllByTestId(/^item-row-/).find((el) => el.getAttribute('aria-current') === 'true')?.getAttribute('data-row-id')

  it('moves the selection with up and down and the detail follows', async () => {
    mount()
    await screen.findByTestId('item-row-5')
    const list = screen.getByTestId('items-scroll')
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle LH'))
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle RH'))
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    expect(current()).toBe('30')
    fireEvent.keyDown(list, { key: 'ArrowUp' })
    expect(current()).toBe('6')
  })

  it('expands and collapses the selected row with right and left', async () => {
    mount()
    await within(await screen.findByTestId('item-row-5')).findByTestId('row-rev-5')
    fireEvent.click(screen.getByTestId('item-row-5'))
    const list = screen.getByTestId('items-scroll')
    fireEvent.keyDown(list, { key: 'ArrowRight' })
    expect(await screen.findByTestId('tree-rev-10')).toBeTruthy()
    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    expect(screen.queryByTestId('tree-rev-10')).toBeNull()
  })

  it('ignores arrows typed in the search box', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    fireEvent.keyDown(screen.getByLabelText('Search items'), { key: 'ArrowDown' })
    expect(current()).toBe('5')
  })

  it('jumps to the first visible row when the selection sits in a collapsed group', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('item-row-30'))
    fireEvent.click(screen.getByTestId('group-toggle-tool'))
    fireEvent.keyDown(screen.getByTestId('items-scroll'), { key: 'ArrowDown' })
    expect(current()).toBe('5')
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project/itemGroups.test.ts src/pages/ProjectDetailPage.layout.test.tsx -t "findNode|keyboard"`
Expected: FAIL: `findNode` is not exported; the arrow keys do nothing.

- [ ] **Step 3: Add `findNode` to `itemGroups.ts`**

```ts
/** The node for a part id anywhere in the tree, or undefined. */
export function findNode(nodes: TreeNode[], partId: number): TreeNode | undefined {
  for (const n of nodes) {
    if (n.part.id === partId) return n;
    const hit = findNode(n.children, partId);
    if (hit) return hit;
  }
  return undefined;
}
```

- [ ] **Step 4: Handle the keys in `ItemsPane.tsx`**

1. Change the imports:

```tsx
import { useMemo, useRef, useState } from 'react';
```

```tsx
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
```

```tsx
import { findNode, groupNodes, matchesSearch, visibleOrder, type GroupKey } from './itemGroups';
```

2. After the `toggleGroup` declaration add:

```tsx
  const listRef = useRef<HTMLDivElement>(null);
  const order = visibleOrder(groups, collapsedGroups, isExpanded);
  const rowExpandable = (n: TreeNode) => {
    const a = articleOf(structure, n.part.id);
    return n.children.length > 0 || (!!a && (a.revisions.length > 0 || a.related.length > 0));
  };

  const onListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('input, select, textarea')) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (order.length === 0) return;
      const at = selectedPartId === null ? -1 : order.indexOf(selectedPartId);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      const next = at === -1
        ? (step === 1 ? 0 : order.length - 1)
        : Math.min(order.length - 1, Math.max(0, at + step));
      const nextId = order[next];
      onSelect(nextId);
      listRef.current?.querySelector<HTMLElement>(`[data-row-id="${nextId}"]`)?.scrollIntoView?.({ block: 'nearest' });
      return;
    }
    if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && selectedPartId !== null) {
      const n = findNode(visibleNodes, selectedPartId);
      if (!n || !rowExpandable(n)) return;
      e.preventDefault();
      setExpanded(selectedPartId, e.key === 'ArrowRight');
    }
  };
```

3. Give the scroll container the ref, focus and handler:

```tsx
      <div
        ref={listRef}
        data-testid="items-scroll"
        tabIndex={0}
        aria-label="Items"
        onKeyDown={onListKeyDown}
        className="flex-1 min-h-0 overflow-y-auto px-2 py-2 focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-600"
      >
```

- [ ] **Step 5: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/project/itemGroups.ts frontend/src/components/project/itemGroups.test.ts \
  frontend/src/components/project/ItemsPane.tsx frontend/src/pages/ProjectDetailPage.layout.test.tsx
git commit -F - <<'MSG'
feat(project-page): arrow keys move the selection and expand rows in the items list

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 12: The project selection channel

**Files:**
- Create: `frontend/src/testing/fakeBroadcastChannel.ts`
- Create: `frontend/src/hooks/useSelectionChannel.ts`
- Create: `frontend/src/hooks/useSelectionChannel.test.ts`

**Interfaces:**
- Produces:

```ts
// hooks/useSelectionChannel.ts
export type SelectionMessage =
  | { type: 'select'; partId: number | null; revisionId: number | null }
  | { type: 'ping' }    // main window asks whether a pop-out is open
  | { type: 'hello' }   // pop-out announces itself (on load and in answer to ping)
  | { type: 'bye' };    // pop-out is closing
export function selectionChannelSupported(): boolean
export function selectionChannelName(projectId: number): string   // `plm2-project-${projectId}`
export function useSelectionChannel(
  projectId: number,
  onMessage: (message: SelectionMessage) => void,
  farewell?: SelectionMessage,   // posted on unmount and on window 'pagehide'
): (message: SelectionMessage) => void   // stable; a no-op without BroadcastChannel
// testing/fakeBroadcastChannel.ts
export class FakeBroadcastChannel { static reset(): void; name: string; onmessage: ((e: { data: unknown }) => void) | null; postMessage(data: unknown): void; close(): void }
```

The fake delivers synchronously to the other open channels of the same name (a real channel is asynchronous; tests wrap posts from outside React in `act`).

- [ ] **Step 1: Write the test double and the failing test**

`frontend/src/testing/fakeBroadcastChannel.ts`:

```ts
/**
 * In-memory BroadcastChannel for tests. Delivers synchronously to every other
 * open channel with the same name, never to the sender, like the real one.
 */
type Listener = (event: { data: unknown }) => void;

export class FakeBroadcastChannel {
  static open: FakeBroadcastChannel[] = [];

  static reset(): void {
    FakeBroadcastChannel.open = [];
  }

  readonly name: string;
  onmessage: Listener | null = null;

  constructor(name: string) {
    this.name = name;
    FakeBroadcastChannel.open.push(this);
  }

  postMessage(data: unknown): void {
    for (const channel of [...FakeBroadcastChannel.open]) {
      if (channel !== this && channel.name === this.name) channel.onmessage?.({ data });
    }
  }

  close(): void {
    FakeBroadcastChannel.open = FakeBroadcastChannel.open.filter((c) => c !== this);
  }
}
```

`frontend/src/hooks/useSelectionChannel.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { FakeBroadcastChannel } from '../testing/fakeBroadcastChannel'
import { selectionChannelName, selectionChannelSupported, useSelectionChannel, type SelectionMessage } from './useSelectionChannel'

function peer(name = 'plm2-project-2') {
  const got: unknown[] = []
  const channel = new FakeBroadcastChannel(name)
  channel.onmessage = (e) => { got.push(e.data) }
  return { channel, got }
}

describe('useSelectionChannel', () => {
  beforeEach(() => {
    FakeBroadcastChannel.reset()
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('names the channel after the project', () => {
    expect(selectionChannelName(2)).toBe('plm2-project-2')
  })

  it('delivers messages of its own project only', () => {
    const got: SelectionMessage[] = []
    renderHook(() => useSelectionChannel(2, (m) => { got.push(m) }))
    peer('plm2-project-2').channel.postMessage({ type: 'hello' })
    peer('plm2-project-3').channel.postMessage({ type: 'bye' })
    expect(got).toEqual([{ type: 'hello' }])
  })

  it('posts to the other windows of the project', () => {
    const p = peer()
    const { result } = renderHook(() => useSelectionChannel(2, () => {}))
    result.current({ type: 'select', partId: 5, revisionId: 9 })
    expect(p.got).toEqual([{ type: 'select', partId: 5, revisionId: 9 }])
  })

  it('always calls the latest handler', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = renderHook(({ h }) => useSelectionChannel(2, h), { initialProps: { h: first } })
    rerender({ h: second })
    peer().channel.postMessage({ type: 'ping' })
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith({ type: 'ping' })
  })

  it('says goodbye on pagehide and on unmount', () => {
    const p = peer()
    const { unmount } = renderHook(() => useSelectionChannel(2, () => {}, { type: 'bye' }))
    window.dispatchEvent(new Event('pagehide'))
    unmount()
    expect(p.got).toEqual([{ type: 'bye' }, { type: 'bye' }])
  })

  it('is a harmless no-op without BroadcastChannel', () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    expect(selectionChannelSupported()).toBe(false)
    const { result } = renderHook(() => useSelectionChannel(2, () => {}))
    expect(() => result.current({ type: 'ping' })).not.toThrow()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/hooks/useSelectionChannel.test.ts`
Expected: FAIL, "Failed to resolve import './useSelectionChannel'".

- [ ] **Step 3: Create `frontend/src/hooks/useSelectionChannel.ts`**

```ts
/**
 * The line between a project window and its pop-out detail window: one
 * BroadcastChannel per project, `plm2-project-<id>`. The main window posts
 * the selected part and revision; the pop-out announces itself with hello
 * and leaves with bye.
 */
import { useCallback, useEffect, useRef } from 'react';

export type SelectionMessage =
  | { type: 'select'; partId: number | null; revisionId: number | null }
  | { type: 'ping' }
  | { type: 'hello' }
  | { type: 'bye' };

export function selectionChannelSupported(): boolean {
  return typeof BroadcastChannel !== 'undefined';
}

export function selectionChannelName(projectId: number): string {
  return `plm2-project-${projectId}`;
}

export function useSelectionChannel(
  projectId: number,
  onMessage: (message: SelectionMessage) => void,
  farewell?: SelectionMessage,
): (message: SelectionMessage) => void {
  const channelRef = useRef<BroadcastChannel | null>(null);
  const handlerRef = useRef(onMessage);
  const farewellRef = useRef(farewell);
  useEffect(() => {
    handlerRef.current = onMessage;
    farewellRef.current = farewell;
  });

  useEffect(() => {
    if (!projectId || !selectionChannelSupported()) return;
    const channel = new BroadcastChannel(selectionChannelName(projectId));
    channel.onmessage = (event: MessageEvent) => handlerRef.current(event.data as SelectionMessage);
    channelRef.current = channel;
    const sayGoodbye = () => {
      if (farewellRef.current) channel.postMessage(farewellRef.current);
    };
    // A closing window does not unmount React; pagehide is the last word it gets.
    window.addEventListener('pagehide', sayGoodbye);
    return () => {
      window.removeEventListener('pagehide', sayGoodbye);
      sayGoodbye();
      channel.close();
      if (channelRef.current === channel) channelRef.current = null;
    };
  }, [projectId]);

  return useCallback((message: SelectionMessage) => {
    channelRef.current?.postMessage(message);
  }, []);
}
```

- [ ] **Step 4: Run the test**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/hooks/useSelectionChannel.test.ts && npx tsc --noEmit`
Expected: PASS (6 tests), tsc clean.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/testing/fakeBroadcastChannel.ts frontend/src/hooks/useSelectionChannel.ts \
  frontend/src/hooks/useSelectionChannel.test.ts
git commit -F - <<'MSG'
feat(project-page): selection channel between the project window and its pop-out

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 13: Pop-out detail route and page

**Files:**
- Create: `frontend/src/pages/ProjectDetailPopout.tsx`
- Create: `frontend/src/pages/ProjectDetailPopout.test.tsx`
- Modify: `frontend/src/App.tsx` (route + `ProtectedRoute bare`)

**Interfaces:**
- Consumes: `useProject`, `useProjectParts`, `useProjectStructure`, `useArticleSelection`, `useSelectionChannel`, `DetailPane` (Task 10 props), `DetailTab`.
- Produces: route `/projects/:projectId/detail?part=<id>&rev=<id>` rendering `ProjectDetailPopout` without the sidebar. The page posts `hello` on load and in answer to `ping`, posts `bye` when it goes away, and follows `select` messages. A `select` for a part it does not have triggers a refetch of `['parts', id]`.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/ProjectDetailPopout.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPopout from './ProjectDetailPopout'
import { FakeBroadcastChannel } from '../testing/fakeBroadcastChannel'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/workflows/RevisionWorkflowSection', () => stub('workflow-section'))
vi.mock('../components/PartBOMSection', () => stub('bom-section'))
vi.mock('../components/PartRelationsSection', () => stub('relations-section'))
vi.mock('../components/ProcessFlowSection', () => stub('process-flow-section'))
vi.mock('../components/PPAPSection', () => stub('ppap-section'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

const LH = { id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null }
const NEW = { id: 77, part_number: '20-1994-077-0', name: 'New bracket', part_type: 'internal_mfg', active_revision_id: null, item_category: 'article', parent_part_id: null }
const revs5 = [
  { id: 9, part_id: 5, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, created_at: '2026-05-28' },
  { id: 10, part_id: 5, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review', parent_revision_id: 9, created_at: '2026-05-28' },
]
const revs6 = [{ id: 19, part_id: 6, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, created_at: '2026-05-28' }]
let partsData: unknown[] = [LH, RH]

function mount(path = '/projects/2/detail?part=5') {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/projects/:projectId/detail" element={<ProjectDetailPopout />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

function mainWindow() {
  const got: unknown[] = []
  const channel = new FakeBroadcastChannel('plm2-project-2')
  channel.onmessage = (e) => { got.push(e.data) }
  return { channel, got }
}

describe('ProjectDetailPopout', () => {
  beforeEach(() => {
    partsData = [LH, RH]
    FakeBroadcastChannel.reset()
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active' }] })
      if (url === '/v1/parts/project/2') return Promise.resolve({ data: partsData })
      if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: revs5 })
      if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: revs6 })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows only the detail of the part in the URL and says hello', async () => {
    const main = mainWindow()
    mount()
    expect((await screen.findByTestId('detail-header')).textContent).toContain('Handle LH')
    expect(screen.queryByTestId('items-pane')).toBeNull()
    expect(screen.queryByLabelText('Open detail in new window')).toBeNull()
    expect(main.got).toContainEqual({ type: 'hello' })
  })

  it('opens on the revision named in the URL', async () => {
    mount('/projects/2/detail?part=5&rev=10')
    expect((await screen.findByTestId('rev-tab-10')).getAttribute('aria-selected')).toBe('true')
  })

  it('follows a selection posted by the main window', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    act(() => main.channel.postMessage({ type: 'select', partId: 6, revisionId: 19 }))
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle RH'))
    act(() => main.channel.postMessage({ type: 'select', partId: 5, revisionId: 10 }))
    expect((await screen.findByTestId('rev-tab-10')).getAttribute('aria-selected')).toBe('true')
  })

  it('answers a ping from the main window', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    main.got.length = 0
    act(() => main.channel.postMessage({ type: 'ping' }))
    expect(main.got).toEqual([{ type: 'hello' }])
  })

  it('says bye when it goes away', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    cleanup()
    expect(main.got).toContainEqual({ type: 'bye' })
  })

  it('waits for a part it does not know yet and shows it after refetching the parts', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    partsData = [LH, RH, NEW] // created in the main window after the pop-out loaded
    act(() => main.channel.postMessage({ type: 'select', partId: 77, revisionId: null }))
    expect(screen.getByText('Select an item in the main window')).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('New bracket'))
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ProjectDetailPopout.test.tsx`
Expected: FAIL, "Failed to resolve import './ProjectDetailPopout'".

- [ ] **Step 3: Create `frontend/src/pages/ProjectDetailPopout.tsx`**

```tsx
/**
 * ProjectDetailPopout - the detail pane alone, in its own browser window.
 * It follows the selection the project window posts on the project channel
 * and tells that window when it opens and closes.
 */
import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import DetailPane from '../components/project/DetailPane';
import type { DetailTab } from '../components/project/detailTabs';
import { useProject, useProjectParts } from '../hooks/queries/useProjectDetail';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useArticleSelection } from '../hooks/useArticleSelection';
import { useSelectionChannel } from '../hooks/useSelectionChannel';

function toId(value: string | null): number | null {
  const n = value ? parseInt(value, 10) : NaN;
  return Number.isFinite(n) ? n : null;
}

export default function ProjectDetailPopout() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const [searchParams] = useSearchParams();
  const initialPart = toId(searchParams.get('part'));
  const initialRev = toId(searchParams.get('rev'));
  const queryClient = useQueryClient();

  const { data: project } = useProject(id);
  const { data: parts } = useProjectParts(id);
  const { data: structure } = useProjectStructure(id);
  const sel = useArticleSelection(parts, initialPart);
  const { partId, openPart, pickRevision, selectRevision } = sel;
  const [tab, setTab] = useState<DetailTab>('documents');

  useEffect(() => {
    if (initialPart !== null && initialRev !== null) pickRevision(initialPart, initialRev);
  }, [initialPart, initialRev, pickRevision]);

  const post = useSelectionChannel(id, (message) => {
    if (message.type === 'ping') {
      post({ type: 'hello' });
      return;
    }
    if (message.type !== 'select') return;
    if (message.partId === null) {
      openPart(null);
      return;
    }
    // A part created in the main window after this one loaded: fetch the list again.
    if (!parts?.some((p) => p.id === message.partId)) {
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
    }
    if (message.revisionId === null) openPart(message.partId);
    else if (message.partId === partId) selectRevision(message.revisionId);
    else pickRevision(message.partId, message.revisionId);
  }, { type: 'bye' });

  useEffect(() => {
    post({ type: 'hello' });
  }, [post]);

  useEffect(() => {
    if (project) document.title = `${project.code} ${project.name} detail`;
  }, [project]);

  if (!project) {
    return <div className="h-screen bg-slate-900 p-6 text-slate-400">Loading project...</div>;
  }

  return (
    <div data-testid="popout-page" className="h-screen flex flex-col bg-slate-900">
      <div className="flex-shrink-0 px-4 py-1.5 border-b border-slate-800 text-xs text-slate-500">
        <span className="font-mono text-slate-400">{project.code}</span> {project.name} · follows the project window
      </div>
      <div className="flex-1 min-h-0">
        <DetailPane
          projectId={id}
          project={project}
          parts={parts}
          structure={structure}
          sel={sel}
          tab={tab}
          onTabChange={setTab}
          emptyText="Select an item in the main window"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Register the route in `frontend/src/App.tsx`**

Add the import next to the other pages:

```tsx
import ProjectDetailPopout from './pages/ProjectDetailPopout';
```

Change `ProtectedRoute` so a route can skip the sidebar layout:

```tsx
function ProtectedRoute({ children, bare = false }: { children: React.ReactNode; bare?: boolean }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return null; // or a spinner
  if (!isAuthenticated) {
    window.location.href = '/';
    return null;
  }
  return bare ? <>{children}</> : <AppLayout>{children}</AppLayout>;
}
```

Add the route right after the `/projects/:projectId` route:

```tsx
      {/* Pop-out detail window: the detail pane alone, no sidebar. */}
      <Route
        path="/projects/:projectId/detail"
        element={
          <ProtectedRoute bare>
            <ProjectDetailPopout />
          </ProtectedRoute>
        }
      />
```

- [ ] **Step 5: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/pages/ProjectDetailPopout.test.tsx src/pages/ProjectDetailPage && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/pages/ProjectDetailPopout.tsx frontend/src/pages/ProjectDetailPopout.test.tsx frontend/src/App.tsx
git commit -F - <<'MSG'
feat(project-page): pop-out detail window that follows the project selection

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 14: Main window: ⧉ opens the pop-out, the list becomes a table while it is open

**Files:**
- Modify: `frontend/src/components/project/projectTypes.ts` (`Part.tool_cavities`)
- Modify: `frontend/src/components/project/itemGroups.ts`, `itemGroups.test.ts` (table row helpers)
- Modify: `frontend/src/components/project/ItemsPane.tsx` (`mode` prop, table)
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (full replacement below)
- Modify: `frontend/src/pages/ProjectDetailPage.layout.test.tsx` (append; add `act` to the testing-library import and two imports at the top)

**Interfaces:**
- Consumes: `useSelectionChannel`, `selectionChannelSupported` (Task 12), `SplitPane.rightHidden` (Task 9), `DetailPane.onPopOut` (Task 10), `shortName` (Task 8).
- Produces:

```ts
// projectTypes.ts, Part
tool_cavities?: number | null;   // present once the tool fields from feature/tool-dfm-archive are on the API
// itemGroups.ts
export interface TableRow { id: number; customerNumber: string; tier1: string; name: string; phase: string; revision: string; tools: string; cavities: string }
export function tableRow(part: Part, parts: Part[], structure: ProjectStructure | undefined, projectCode: string): TableRow
export function hasToolFields(parts: Part[]): boolean
// ItemsPane: new optional prop
mode?: 'list' | 'table';   // default 'list'
```
- Window name `plm2-detail-<projectId>`; URL `<router href of /projects/<id>/detail>?part=<id>&rev=<id>`. DOM: `items-table`, rows `table-row-<id>` (`aria-selected`), `th` headers `Customer no.`, `Tier 1`, `Name`, `Phase`, `Revision`, `Tool`, and `Cavities` only when `hasToolFields`.

Presence rules in the main window: `popoutOpen` turns true when ⧉ opened a window or a `hello` arrives; it turns false on `bye`, or when the window handle this page opened reports `closed` (checked every second, because a window killed by the OS or a crash never says bye). On load the page posts `ping`, so a pop-out that is already open answers `hello`. While `popoutOpen`, every selection change is posted as `select`.

- [ ] **Step 1: Write the failing tests**

Append to `itemGroups.test.ts` (add `hasToolFields, tableRow` to its import):

```ts
describe('tableRow', () => {
  const structure = { articles: [{
    part_id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', name: '206.882.251 Handle LH',
    lifecycle_phase: 'nominated', active_revision_id: 9,
    revisions: [{ id: 9, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review' as const, parent_revision_id: null, is_active: true }],
    related: [{ relation_type: 'produces', direction: 'incoming' as const, label: 'produced by', part_id: 30, part_number: '199401', name: 'TOOL Handle', item_category: 'tool' }],
    mirror_of: null, mirrored_by: [],
  }] }
  const lh = part(5, { part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: '206.882.251 Handle LH' })
  const tool = part(30, { part_number: '199401', name: '1994 TOOL Handle', item_category: 'tool', lifecycle_phase: 'rfq', tool_cavities: 2 })

  it('fills the table cells from the part, its structure and its tools', () => {
    expect(tableRow(lh, [lh, tool], structure, '1994')).toEqual({
      id: 5, customerNumber: '206.882.251', tier1: 'S00H4X-110', name: 'Handle LH', phase: 'nominated',
      revision: 'E1 · 003', tools: '199401', cavities: '2',
    })
  })

  it('uses the internal number when there is no customer number, and a tool shows its own cavities', () => {
    expect(tableRow(tool, [lh, tool], structure, '1994')).toMatchObject({ customerNumber: '199401', name: 'TOOL Handle', phase: 'rfq', cavities: '2', tools: '' })
  })

  it('knows whether the API sends tool fields at all', () => {
    expect(hasToolFields([lh])).toBe(false)
    expect(hasToolFields([lh, part(31, { item_category: 'tool', tool_cavities: null })])).toBe(true)
  })
})
```

At the top of `ProjectDetailPage.layout.test.tsx` add (and add `act` to the testing-library import):

```tsx
import { FakeBroadcastChannel } from '../testing/fakeBroadcastChannel'
import type { SelectionMessage } from '../hooks/useSelectionChannel'
```

Append:

```tsx
describe('pop-out detail window from the project page', () => {
  beforeEach(() => {
    FakeBroadcastChannel.reset()
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
  })

  const popout = () => {
    const got: SelectionMessage[] = []
    const channel = new FakeBroadcastChannel('plm2-project-2')
    channel.onmessage = (e) => { got.push(e.data as SelectionMessage) }
    return { channel, got }
  }

  it('opens the detail in a named window and shows the list as a table', async () => {
    const open = vi.fn(() => ({ closed: false }) as unknown as Window)
    window.open = open
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByLabelText('Open detail in new window'))
    expect(open).toHaveBeenCalledWith('/projects/2/detail?part=5&rev=9', 'plm2-detail-2', expect.any(String))
    expect(await screen.findByTestId('items-table')).toBeTruthy()
    expect(screen.queryByTestId('detail-pane')).toBeNull()
    expect(screen.queryByRole('separator')).toBeNull()
  })

  it('answers a hello with the selection and posts every change', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage({ type: 'hello' }))
    expect(await screen.findByTestId('items-table')).toBeTruthy()
    expect(p.got).toContainEqual({ type: 'select', partId: null, revisionId: null })
    fireEvent.click(screen.getByTestId('table-row-6'))
    await waitFor(() => expect(p.got).toContainEqual({ type: 'select', partId: 6, revisionId: 19 }))
    expect(screen.getByTestId('table-row-6').getAttribute('aria-selected')).toBe('true')
  })

  it('asks on load whether a pop-out is already open', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    expect(p.got).toContainEqual({ type: 'ping' })
  })

  it('brings the detail back when the pop-out says bye', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage({ type: 'hello' }))
    await screen.findByTestId('items-table')
    act(() => p.channel.postMessage({ type: 'bye' }))
    expect(screen.queryByTestId('items-table')).toBeNull()
    expect(screen.getByRole('separator')).toBeTruthy()
  })

  it('notices a pop-out that was closed without saying bye', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const win = { closed: false }
      window.open = vi.fn(() => win as unknown as Window)
      mount()
      fireEvent.click(await screen.findByTestId('item-row-5'))
      fireEvent.click(await screen.findByLabelText('Open detail in new window'))
      await screen.findByTestId('items-table')
      win.closed = true
      act(() => { vi.advanceTimersByTime(1000) })
      expect(screen.queryByTestId('items-table')).toBeNull()
      expect(screen.getByTestId('detail-pane')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows the table columns, with cavities once the tool fields exist', async () => {
    partsData = [LH, RH, { ...TOOL, tool_cavities: 2 }]
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage({ type: 'hello' }))
    const table = await screen.findByTestId('items-table')
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent))
      .toEqual(['Customer no.', 'Tier 1', 'Name', 'Phase', 'Revision', 'Tool', 'Cavities'])
    await waitFor(() => expect(within(within(table).getByTestId('table-row-5')).getAllByRole('cell').map((td) => td.textContent))
      .toEqual(['206.882.251', 'S00H4X-110', 'Handle LH', 'nominated', 'E1 · 003', '199401', '2']))
  })

  it('leaves the cavities column out before the tool fields exist', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage({ type: 'hello' }))
    const table = await screen.findByTestId('items-table')
    expect(within(table).queryByText('Cavities')).toBeNull()
  })

  it('offers no pop-out when the browser has no BroadcastChannel', async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    await screen.findByTestId('detail-header')
    expect(screen.queryByLabelText('Open detail in new window')).toBeNull()
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project/itemGroups.test.ts src/pages/ProjectDetailPage.layout.test.tsx -t "tableRow|pop-out detail window"`
Expected: FAIL: `tableRow` / `hasToolFields` not exported; no ⧉ button, no `items-table`.

- [ ] **Step 3: Types and table helpers**

In `projectTypes.ts`, `interface Part`, after `lifecycle_phase?: string;` add:

```ts
  tool_cavities?: number | null;
```

Append to `itemGroups.ts` (and add the two imports at its top):

```ts
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { revisionLabel } from '../parts/RevisionBadge';
import { shortName } from '../../lib/partDisplay';
```

```ts
export interface TableRow {
  id: number;
  customerNumber: string;
  tier1: string;
  name: string;
  phase: string;
  revision: string;
  tools: string;
  cavities: string;
}

/** The API sends tool_cavities (even as null) once the tool fields exist; before that the key is missing. */
export function hasToolFields(parts: Part[]): boolean {
  return parts.some((p) => p.tool_cavities !== undefined);
}

/** Cells of one row of the items table shown while the detail is popped out. */
export function tableRow(part: Part, parts: Part[], structure: ProjectStructure | undefined, projectCode: string): TableRow {
  const article = articleOf(structure, part.id);
  const customer = part.customer_part_number ?? article?.customer_part_number ?? null;
  const active = article?.revisions.find((r) => r.is_active);
  const toolLinks = (article?.related ?? []).filter((r) => r.item_category === 'tool');
  const linkedCavities = toolLinks
    .map((r) => parts.find((p) => p.id === r.part_id)?.tool_cavities)
    .filter((c): c is number => c !== null && c !== undefined);
  const ownCavities = part.item_category === 'tool' && part.tool_cavities != null ? [part.tool_cavities] : [];
  return {
    id: part.id,
    customerNumber: customer ?? part.part_number,
    tier1: part.tier1_part_number ?? '',
    name: shortName(part.name, projectCode, customer),
    phase: article?.lifecycle_phase ?? part.lifecycle_phase ?? '',
    revision: active ? revisionLabel(active.revision_name, active.customer_index) : '',
    tools: toolLinks.map((r) => r.part_number).join(', '),
    cavities: [...ownCavities, ...linkedCavities].join(', '),
  };
}
```

- [ ] **Step 4: Table mode in `ItemsPane.tsx`**

1. Imports: add `comparePartNumbers` from `'../../lib/partDisplay'`, and extend the `./itemGroups` import to `findNode, groupNodes, hasToolFields, matchesSearch, tableRow, visibleOrder, type GroupKey`.
2. Add to `ItemsPaneProps`:

```ts
  /** 'table' while the detail is popped out: one flat row per item with the key columns. */
  mode?: 'list' | 'table';
```

and add `mode = 'list'` to the destructured props.

3. After `const groups = ...` add:

```tsx
  const tableParts = useMemo(() => (parts ?? [])
    .filter((p) => matchesSearch(p, query))
    .filter((p) => categoryFilter === 'all'
      || (categoryFilter === 'assemblies' ? p.part_type === 'sub_assembly'
        : categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter))
    .sort((a, b) => comparePartNumbers(a.part_number, b.part_number)), [parts, query, categoryFilter, paintedIds]);
  const showCavities = hasToolFields(parts ?? []);
  const isTable = mode === 'table';
```

4. Replace `const order = visibleOrder(groups, collapsedGroups, isExpanded);` with:

```tsx
  const order = isTable ? tableParts.map((p) => p.id) : visibleOrder(groups, collapsedGroups, isExpanded);
```

and at the start of the `ArrowRight` / `ArrowLeft` branch in `onListKeyDown` add `if (isTable) return;` (table rows do not expand).

5. The count in the heading follows the mode:

```tsx
          <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
            Items ({isTable ? tableParts.length : visibleNodes.length}{filtered ? ` of ${parts?.length ?? 0}` : ''})
          </h2>
```

and the search box stays enabled in table mode: `disabled={categoryFilter === 'assemblies' && !isTable}`.

6. Inside the `items-scroll` container, put the table in front of the existing chain (`isTable ? table : categoryFilter === 'assemblies' ? ...`):

```tsx
        {isTable ? (
          <table data-testid="items-table" className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-400">
              <tr>
                {['Customer no.', 'Tier 1', 'Name', 'Phase', 'Revision', 'Tool', ...(showCavities ? ['Cavities'] : [])].map((h) => (
                  <th key={h} className="px-2 py-1 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableParts.map((p) => {
                const row = tableRow(p, parts ?? [], structure, projectCode);
                const selected = selectedPartId === p.id;
                return (
                  <tr
                    key={p.id}
                    data-testid={`table-row-${p.id}`}
                    data-row-id={p.id}
                    aria-selected={selected}
                    onClick={() => onSelect(p.id)}
                    onContextMenu={(e) => onContextMenu(e, p.id)}
                    className={`cursor-pointer border-t border-slate-800 ${selected ? 'bg-blue-900/40' : 'hover:bg-slate-800'}`}
                  >
                    <td className="px-2 py-1 font-mono text-slate-200">{row.customerNumber}</td>
                    <td className="px-2 py-1 font-mono text-slate-400">{row.tier1}</td>
                    <td className="px-2 py-1 text-slate-100">{row.name}</td>
                    <td className="px-2 py-1 text-slate-400">{row.phase}</td>
                    <td className="px-2 py-1 font-mono text-slate-300">{row.revision}</td>
                    <td className="px-2 py-1 font-mono text-slate-300">{row.tools}</td>
                    {showCavities && <td className="px-2 py-1 text-slate-300">{row.cavities}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : categoryFilter === 'assemblies' ? (
```

(the rest of the chain is unchanged).

- [ ] **Step 5: Replace `frontend/src/pages/ProjectDetailPage.tsx`**

```tsx
/**
 * ProjectDetailPage - the project work surface. A one-line header, the items
 * list on the left and the selected item's detail on the right; the page
 * fills the viewport and each pane scrolls on its own. The detail can pop out
 * into its own window, which follows the selection over the project channel
 * while the list here turns into a table.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useHref, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import StartChangeModal from '../components/changes/StartChangeModal';
import { projectPaintOverview } from '../api/paints';
import type { PartPaintLayer } from '../types/paint';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useProject, useProjectParts } from '../hooks/queries/useProjectDetail';
import { useArticleSelection } from '../hooks/useArticleSelection';
import { selectionChannelSupported, useSelectionChannel } from '../hooks/useSelectionChannel';
import ProjectHeaderBar from '../components/project/ProjectHeaderBar';
import StatusSlideOver, { type StatusSection } from '../components/project/StatusSlideOver';
import ItemsPane from '../components/project/ItemsPane';
import DetailPane from '../components/project/DetailPane';
import SplitPane from '../components/project/SplitPane';
import ProjectContextMenu from '../components/project/ProjectContextMenu';
import ChangelogModal from '../components/project/ChangelogModal';
import AddPartModal from '../components/project/AddPartModal';
import type { DetailTab } from '../components/project/detailTabs';
import type { ContextMenuState } from '../components/project/projectTypes';

const SPLIT_KEY = 'plm2.project.splitLeft';
const POPOUT_POLL_MS = 1000;

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const navigate = useNavigate();

  const [searchParams] = useSearchParams();
  const initialPartId = searchParams.get('part');

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: structure } = useProjectStructure(id);
  const sel = useArticleSelection(parts, initialPartId ? parseInt(initialPartId, 10) : null);
  const { selectPart, openPart, pickRevision } = sel;

  // Follow ?part= deep links from global search while already on the page
  useEffect(() => {
    if (initialPartId) selectPart(parseInt(initialPartId, 10));
  }, [initialPartId, selectPart]);

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showStartChange, setShowStartChange] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);
  const [openSection, setOpenSection] = useState<StatusSection | null>(null);
  const closeSection = useCallback(() => setOpenSection(null), []);
  const [detailTab, setDetailTab] = useState<DetailTab>('documents');

  const { data: paintOverview } = useQuery({
    queryKey: ['project-paint-overview', id],
    queryFn: () => projectPaintOverview(id),
    enabled: !!id,
  });
  // Top layer (layer_order 1) per painted part, for the swatch on the item row.
  const paintByPartId = useMemo(() => {
    const map = new Map<number, PartPaintLayer>();
    for (const part of paintOverview ?? []) {
      const top = part.layers.find((l) => l.layer_order === 1) ?? part.layers[0];
      if (top) map.set(part.part_id, top);
    }
    return map;
  }, [paintOverview]);
  // Every part that requires paint, layer or not: the Painted chip counts
  // these, so the filter must select the same set (a part marked required
  // with no layer yet was counted but filtered out, 2026-09-21).
  const paintedIds = useMemo(
    () => new Set((paintOverview ?? []).map((part) => part.part_id)),
    [paintOverview],
  );

  // Pop-out detail window
  const [popoutOpen, setPopoutOpen] = useState(false);
  const popoutRef = useRef<Window | null>(null);
  const popoutHref = useHref(`/projects/${id}/detail`);

  const post = useSelectionChannel(id, (message) => {
    if (message.type === 'hello') {
      setPopoutOpen(true);
      post({ type: 'select', partId: sel.partId, revisionId: sel.revisionId });
    } else if (message.type === 'bye') {
      popoutRef.current = null;
      setPopoutOpen(false);
    }
  });

  // On load, ask whether a pop-out of this project is already open; it answers hello.
  useEffect(() => {
    post({ type: 'ping' });
  }, [post]);

  useEffect(() => {
    if (popoutOpen) post({ type: 'select', partId: sel.partId, revisionId: sel.revisionId });
  }, [popoutOpen, sel.partId, sel.revisionId, post]);

  // A window closed by the OS or a crash never says bye: watch the handle we opened.
  useEffect(() => {
    if (!popoutOpen) return;
    const timer = window.setInterval(() => {
      if (popoutRef.current?.closed) {
        popoutRef.current = null;
        setPopoutOpen(false);
      }
    }, POPOUT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [popoutOpen]);

  const openPopout = useCallback(() => {
    const query = sel.partId !== null
      ? `?part=${sel.partId}${sel.revisionId !== null ? `&rev=${sel.revisionId}` : ''}`
      : '';
    // A fixed name per project: a second click reuses the same window.
    const win = window.open(`${popoutHref}${query}`, `plm2-detail-${id}`, 'popup,width=1100,height=900');
    if (!win) {
      toast.error('The browser blocked the new window');
      return;
    }
    popoutRef.current = win;
    setPopoutOpen(true);
  }, [sel.partId, sel.revisionId, popoutHref, id]);

  if (projectLoading) {
    return <div className="p-6 text-slate-400">Loading project...</div>;
  }

  if (!project) {
    return (
      <div className="p-6 text-center">
        <p className="text-red-400 mb-4">Project not found</p>
        <button onClick={() => navigate('/projects')} className="text-blue-400 hover:text-blue-300">
          Back to projects
        </button>
      </div>
    );
  }

  const handleContextMenu = (e: React.MouseEvent, partId: number) => {
    e.preventDefault();
    setContextMenu({ partId, x: e.clientX, y: e.clientY });
  };

  return (
    <div data-testid="project-page" className="h-full flex flex-col overflow-hidden bg-slate-900">
      <ProjectHeaderBar
        project={project}
        onOpenSection={setOpenSection}
        onStartChange={() => setShowStartChange(true)}
        onAddPart={() => setShowAddModal(true)}
      />
      <StatusSlideOver section={openSection} projectId={id} onClose={closeSection} />

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <div className="flex-1 min-h-0">
        <SplitPane
          storageKey={SPLIT_KEY}
          rightHidden={popoutOpen}
          left={
            <ItemsPane
              projectId={id}
              projectCode={project.code}
              parts={parts}
              partsLoading={partsLoading}
              structure={structure}
              paintByPartId={paintByPartId}
              paintedIds={paintedIds}
              paintedCount={paintOverview?.length ?? 0}
              selectedPartId={sel.partId}
              onSelect={selectPart}
              onOpenPart={openPart}
              onPickRevision={pickRevision}
              onContextMenu={handleContextMenu}
              mode={popoutOpen ? 'table' : 'list'}
            />
          }
          right={
            <div data-testid="detail-column" className="h-full min-h-0" onClick={() => selectPart(null)}>
              <DetailPane
                projectId={id}
                project={project}
                parts={parts}
                structure={structure}
                sel={sel}
                tab={detailTab}
                onTabChange={setDetailTab}
                onPopOut={selectionChannelSupported() ? openPopout : undefined}
              />
            </div>
          }
        />
      </div>

      <ProjectContextMenu
        menu={contextMenu}
        onClose={() => setContextMenu(null)}
        onOpenDetails={(partId) => navigate(`/parts/${partId}`)}
        onViewChangelog={(partId) => setChangelogPartId(partId)}
      />

      {changelogPartId && <ChangelogModal partId={changelogPartId} onClose={() => setChangelogPartId(null)} />}

      <AddPartModal projectId={id} parts={parts} isOpen={showAddModal} onClose={() => setShowAddModal(false)} />
    </div>
  );
}
```

`ItemsPane` keeps its position as the `left` child of `SplitPane`, so switching between list and table does not remount it: search, filter and expanded rows survive the pop-out opening and closing.

- [ ] **Step 6: Run the tests**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run src/components/project src/hooks src/pages && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/project/projectTypes.ts frontend/src/components/project/itemGroups.ts \
  frontend/src/components/project/itemGroups.test.ts frontend/src/components/project/ItemsPane.tsx \
  frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.layout.test.tsx
git commit -F - <<'MSG'
feat(project-page): pop the detail out into its own window; list becomes a table meanwhile

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 15: Verification

**Files:**
- Modify (only if the checks below find something): `frontend/src/components/project/AddPartModal.tsx` and any file this plan touched.

- [ ] **Step 1: Remove em dashes from comments and copy in the files this plan touched**

Run: `cd /home/nitrolinux/claude/plm2/frontend && grep -rn "—" src/components/project src/hooks/useArticleSelection.ts src/hooks/useSelectionChannel.ts src/hooks/queries/useProjectDetail.ts src/hooks/queries/useProjectStatus.ts src/lib/safeStorage.ts src/lib/partDisplay.ts src/pages/ProjectDetailPage.tsx src/pages/ProjectDetailPopout.tsx src/components/layout/Sidebar.tsx src/testing`

Expected hit: `AddPartModal.tsx` `<option value="">— No supplier —</option>` (moved verbatim in Task 2). Change it to:

```tsx
                <option value="">No supplier</option>
```

Rewrite any other hit in a comment with a comma, colon or full stop. Re-run the grep: no output.

- [ ] **Step 2: Full frontend test run and type check**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx vitest run && npx tsc --noEmit`
Expected: every test file passes; tsc prints nothing. The four original `ProjectDetailPage.*.test.tsx` files (now three, plus the moved `components/project/CustomerNamingSelect.test.tsx` and `RevisionFileRow.test.tsx`) are all green.

- [ ] **Step 3: Lint the touched files with zero warnings**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npx eslint src/components/project src/hooks src/lib/safeStorage.ts src/lib/partDisplay.ts src/pages/ProjectDetailPage.tsx src/pages/ProjectDetailPopout.tsx src/components/layout src/testing src/App.tsx --max-warnings 0`
Expected: no problems. (Baseline `ProjectDetailPage.tsx` had 5; the extraction removed them. Any `react-refresh/only-export-components` warning means a helper or non-primitive constant sits in a `.tsx` file: move it to a `.ts` file.)

- [ ] **Step 4: Production build**

Run: `cd /home/nitrolinux/claude/plm2/frontend && npm run build`
Expected: `tsc && vite build` succeed.

- [ ] **Step 5: Check it in the browser**

Use the `run` skill (or `npm run dev` and a browser via the `playwright-cli` skill) against the dev backend, log in, open project 1994 (`/plm2/projects/<id>`), and confirm by eye:
1. Sidebar is a 48 px rail; ▶ expands it; reload keeps the choice; `/plm2/dashboard` still opens expanded.
2. Header is one row: code, name, customer, three chips; the lessons chip is amber when no review is recorded; each chip opens its section from the right; Escape and a click on the dimmed area close it; ⋯ holds Start change request, + Add Part, customer file naming and the timing gates with + Gate.
3. No paint block on the page; the Painted chip filters.
4. Items grouped Articles / Tools / Equipment / Gauges / Assemblies with counts; rows show VW number and short name, then internal number, `E1 · 003`, phase and icons; search finds by any number; drag a part onto a ★ sub-assembly still moves it.
5. The page never scrolls as a whole; the list scrolls alone; the detail header and tab bar stay put while a long file list scrolls; the splitter drags, stops at the minimum, and keeps its width after reload.
6. Tabs Documents / Links / BOM / Workflow / Changelog; switching items keeps the tab.
7. Up / Down in the list move the selection and the detail follows; Right / Left expand and collapse.
8. ⧉ opens a second window with only the detail; selecting in the main window updates it; the main list becomes a table with customer no., Tier 1, name, phase, revision, tool (and cavities once the tool fields have landed); a second ⧉ click reuses the window; closing the pop-out brings the detail back within about a second.

- [ ] **Step 6: Commit the verification fixes (if any)**

```bash
cd /home/nitrolinux/claude/plm2
git add -A frontend/src
git commit -F - <<'MSG'
chore(project-page): verification fixes after the redesign

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

Skip this step when Steps 1-5 changed nothing.

---

## Self-review notes

- Spec coverage: 1 rail (Task 5), 2 header, chips, slide-over, ⋯ menu (Task 6), 3 paint removed (Task 7), 4 grouped slim rows, search, filter, expand, drag (Task 8), 5 fixed height, independent scrolling, splitter with remembered width and minimums (Tasks 9, 10), 6 tabs and remembered tab (Task 10), 7 pop-out route, named window, channel, hello, table mode, no ⧉ without BroadcastChannel (Tasks 12-14), 8 keyboard (Task 11). Structure section: every listed file exists (`ProjectHeaderBar`, `StatusSlideOver`, `ItemsPane`, `ItemRow`, `DetailPane`, `SplitPane`, `ProjectDetailPopout`, `useSelectionChannel`). Existing behaviour that moves with its code: revision race guard (`useArticleSelection`, Task 4), mirror banner and customer package (`DocumentsTab`, Task 10), drag-to-restructure and context menu (`ItemsPane`, `ProjectContextMenu`).
- Header "customer": projects have no customer field in the API (`_project_dict` returns id, name, code, description, status, plant_id, customer_naming). The header shows the customer naming label (`VW group`, `Scout`) as the customer. A real customer field is a backend change outside this spec.
- "+ Gate" is the existing `MilestoneStrip` control; the ⋯ menu hosts the strip so the milestones and the + Gate button stay reachable.
- Tools get the same tabs until the tool page from `feature/tool-dfm-archive` lands (spec section 6); nothing in this plan branches on `item_category === 'tool'` in `DetailPane`.
- Existing tests changed on purpose, each named in its task: add-part tests open the ⋯ menu (Task 6), the Tool chip is clicked by exact label (Task 8), relation chips are checked after opening the Links tab (Task 10), the RevisionFileRow and naming tests moved next to their components (Task 2).
