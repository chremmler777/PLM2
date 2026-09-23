# Project page redesign: slim overview, two panes, pop-out detail

Date: 2026-09-23. Status: design approved in chat ("looks good to me"),
spec for review, plan follows.

## Problem

The project page (`frontend/src/pages/ProjectDetailPage.tsx`, 1837 lines)
is the main work surface and it is cluttered:

- Four full-width blocks sit above the items (SEP Q-gates, Changes, Paint,
  Lessons). The items list only starts halfway down the first screen.
- Item rows repeat the internal number, the VW number, the full name and a
  type badge ("internal mfg"), so names are cut off.
- The whole page scrolls as one. The article detail on the right scrolls
  away together with the list, and the detail itself is a long stack of
  sections (document pane, files, process flow, relations, revision
  workflow, PPAP, BOM tree, part BOM).
- The left navigation bar is wide and takes space from the work area.

## Rulings (user, 2026-09-23)

- The items list is the main driver of the page.
- The right side is the active view of the chosen item; scrolling must be
  clean.
- The navigation bar takes too much space.
- Paint does not belong on the project page.
- Detaching details or items into their own window is wanted.
- Design delegated: "make a sleek slim but functional overview". The
  eight points below were presented and approved.

## Design

### 1. Navigation bar becomes an icon rail on project pages

`Sidebar.tsx` already has a collapsed state. On `/projects/:id` it starts
collapsed: a 48 px rail with icons and hover labels (the notification bell
and acts-as switch already have collapsed variants). A click expands it;
the choice is remembered per browser (`localStorage`, wrapped in
try/catch, default collapsed on project pages, unchanged elsewhere).

### 2. One-line project header

One row, fixed at the top of the page:

`1994 Brose Seat Trim · Brose-Sitech   [K0/RG1 0%] [0 changes] [lessons]   ⋯`

- Code, name, customer.
- Three status chips: current SEP gate with progress, open change count,
  lessons state (e.g. the "no lessons review recorded yet" warning becomes
  an amber chip). Each chip opens its full section in a slide-over panel
  from the right (the existing `ProjectSepSection`, `ProjectChangesSection`,
  `ProjectLessonsSection` components, unchanged inside). Escape or a click
  outside closes it.
- The ⋯ menu holds Start change request, + Add Part, customer file naming
  and + Gate.

### 3. Paint leaves the project page

`ProjectPaintSection` is no longer mounted on the project page. Paint
stays on the part page and in the Paints catalog. The "Painted" filter
chip in the items list stays.

### 4. Slim, grouped item rows

The items list groups by category: Articles, Tools, Equipment, Gauges,
Assemblies. Each group header is collapsible and shows its count; empty
groups are hidden. A search box and the existing category filter sit
above the groups.

A row has two short lines:

- Line 1: the customer number (VW) in mono, then the short name (the
  customer number and the project code stripped from the name).
- Line 2, small and muted: internal number, active revision label
  (`E1 · 003`), lifecycle phase, and icons for mirror, painted, proposal.

Items without a customer number (tools, gauges) show their internal
number on line 1. The part-type badge ("internal mfg") moves to the
detail header. The expand chevron keeps its content (numbers, revisions,
linked tools). Drag-to-restructure onto sub-assemblies keeps working.

### 5. Fixed-height app, independent scrolling

The project page fills the viewport and never scrolls as a whole:

- The header row is fixed.
- The items list scrolls on its own.
- The detail pane has a pinned header (numbers, phase, active revision,
  actions) and a tab bar; only the tab content below them scrolls.
- A vertical splitter between list and detail can be dragged; its width
  is remembered per browser (same storage rule as the rail). Minimum
  widths keep both panes usable.

### 6. Detail as tabs

The current stack of sections becomes tabs. The selected tab is
remembered when switching items.

| Tab | Content (existing components) |
|---|---|
| Documents | revision strip, document pane (drawing / 3D), grouped files |
| Links | part relations (tools, mirrors, gauges) |
| BOM | BOM tree and part BOM |
| Workflow | revision workflow, process flow, PPAP |
| Changelog | changelog (today a modal, becomes a tab) |

Tools get their own tab set once the tool page from the DFM work
(`2026-09-23-tool-dfm-archive-design.md`) has landed; until then a tool
shows the same tabs.

### 7. Pop-out detail window

A ⧉ button in the detail header opens `/projects/:id/detail` in a new
browser window (`window.open`, named so a second click reuses it). That
window renders only the detail pane and follows the selection: the main
window posts the selected part and revision on a `BroadcastChannel`
(`plm2-project-<id>`); the pop-out listens and also answers a "hello" so
the main window knows it is open.

While the pop-out is open, the main window hides its detail pane and the
items list takes the full width as a table: customer number, Tier 1
number, name, phase, active revision, tool, cavities (when the tool
fields exist). Closing the pop-out brings the pane back.

Browsers without `BroadcastChannel` do not show the ⧉ button.

### 8. Keyboard

Up and down arrows move the selection in the items list when it has
focus; the detail follows. Right and left expand and collapse a row.

## Structure of the change

`ProjectDetailPage.tsx` is too large to reshape safely in place. The
redesign splits it along the new layout:

- `pages/ProjectDetailPage.tsx`: data hooks, selection state, layout shell.
- `components/project/ProjectHeaderBar.tsx`: header row, chips, ⋯ menu.
- `components/project/StatusSlideOver.tsx`: slide-over host for the
  three sections.
- `components/project/ItemsPane.tsx`: search, filters, grouped list,
  keyboard; table mode.
- `components/project/ItemRow.tsx`: the two-line row and its expand block
  (moved from `TreeNodeComponent`).
- `components/project/DetailPane.tsx`: pinned header, tab bar, tab bodies.
- `components/project/SplitPane.tsx`: splitter with remembered width.
- `pages/ProjectDetailPopout.tsx` + `hooks/useSelectionChannel.ts`:
  pop-out route and the channel.

Behaviour that exists today (revision selection race guards, mirror
banner, customer package, drag-to-restructure, context menu) moves with
its code; existing tests move with it and must stay green.

## Testing

- Header: chips show gate, change count, lessons state; each opens its
  slide-over; ⋯ menu actions still reach their dialogs.
- Paint section not rendered on the project page.
- Items: grouping and counts, row lines (customer number, short name,
  revision label), search and filters, keyboard up/down and expand.
- Layout: detail header and tab bar stay rendered while tab content
  changes; splitter width persists (storage mocked, and works when
  storage throws).
- Tabs: each tab renders its existing section; selected tab survives an
  item switch.
- Pop-out: selection posts on the channel; the pop-out page follows a
  posted selection; table mode appears while the pop-out is open and
  disappears when it closes.
- All existing ProjectDetailPage tests pass after the split.

## Out of scope

Mobile layout, a separate project dashboard page, Chromium-only
always-on-top windows, drag-and-drop of panes inside the page, and any
change to the sections' own content.
