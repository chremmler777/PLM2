# Tool view: tool fields and DFM archive

Date: 2026-09-23. Status: design approved in chat ("go with approach"),
plan follows.

## Problem

Tools are parts with `item_category = tool`, so the part page treats them
like articles: a 3D pane, a revision strip, a file list. None of that fits a
tool. What a tool needs is on no page at all: the cavity count sits as free
text in a relation note ("2 cavities"), the toolmaker is not recorded, and
the DFM studies that go back and forth between the toolmaker, KTX and the
Tier 1 live in mailboxes. Brose is pushing on DFM timing for 1994 (see
memory `1994-brose-volume-sheet-2026-09-23`), and the answers have to be
findable later: who sent what, when, and what the reply was.

## Rulings (user, 2026-09-23)

- No 3D view on tools. A tool shows the E or index number of the article(s)
  it produces, nothing more from the article side.
- Each tool gets a folder-like archive for DFMs. Files are tagged, never
  overwritten, and keep upload time and uploader.
- A DFM exchange can start on either side: a request from KTX to the
  toolmaker, or a DFM from the toolmaker to KTX.
- Three parties, three columns: **Toolmaker | KTX | Tier 1**. Entries zig-zag
  down in time between the columns, in any direction, and can run in
  parallel.
- A side can update its own entry ("out update"); the update is a new entry,
  the old one stays.
- A thread ends in a "finished confirmed" state.
- Unit of closure: a **topic per tool** (several topics per tool, each with
  its own three-column ledger and status). Recommended and accepted.
- The tool tab carries **cavities, toolmaker, machine tonnage class, target
  cycle time**. Accepted on proposal, because the DFM answers rest on the
  sold state and that belongs on the same page.

## Design

### 1. Tool fields on `parts`

Four nullable columns, meaningful only for `item_category = tool`, migration
`077`:

| column | type | meaning |
|---|---|---|
| `tool_cavities` | integer | cavities in the tool (total across produced articles) |
| `toolmaker_id` | FK `suppliers.id` | the toolmaker building the tool; a supplier record |
| `tool_tonnage_class` | integer | machine clamping force class in tonnes (e.g. 650) |
| `tool_cycle_time_s` | numeric(6,1) | target cycle time in seconds |

Schema: the four fields join `PartBase`/`PartUpdate`/`PartResponse` with the
same "only when the key is in the body" update rule the customer and Tier 1
numbers use. The API rejects them on non-tools with 400.

Cavities become the source of truth. The `produces` relation note is left
untouched; wherever the UI shows cavities it prefers `tool_cavities` when
set and falls back to the note.

A one-off script `backend/scripts/set_1994_tool_fields.py` (dry run by
default, runs in the backend container) fills the ten 1994 tools from the
nominated RFQ 26 loop 37 on prod (`tooling_variant_items.cavities`,
`cycle_time_s`; tonnage from the tooling inquiry sheet where present) and
sets the toolmaker once known. It logs one changelog entry per tool.

### 2. DFM archive model

Three tables, all append-only from the user's point of view.

**`dfm_topics`**
- `id`, `tool_part_id` (FK parts, index), `title` (255)
- `status`: `open` | `finished_confirmed`
- `opened_by`, `opened_at`, `closed_by`, `closed_at` (nullable)

**`dfm_entries`**
- `id`, `topic_id` (FK, index)
- `party`: `toolmaker` | `ktx` | `tier1` (the column the entry sits in)
- `addressed_to`: JSON list of parties, one or two of the other two
- `note`: text, nullable
- `supersedes_id`: FK `dfm_entries.id`, nullable. Set on an update; the
  superseded entry stays and is shown as history under the newest one.
- `recorded_by` (FK users: the KTX user who put it in), `recorded_at`
- `sent_at`: date, nullable, when the entry actually went out or came in, if
  different from the recording time (mail dates)

**`dfm_entry_files`**
- `id`, `entry_id` (FK, index), `original_filename`, `saved_filename`,
  `file_size`, `content_type`, `uploaded_by`, `uploaded_at`

Files go under `upload_dir/dfm/<tool_part_id>/<entry_id>/` with the
existing unique-name pattern. No delete endpoint for entries or files. A
topic can be reopened; nothing else is reversible.

Changelog: opening or closing a topic and recording an entry write a
`metadata_updated`-style changelog entry on the tool part, so the tool's
history shows DFM activity next to field edits.

### 3. API

All under `/api/v1/parts/{part_id}/dfm`, `part_id` must be a tool (400
otherwise), same auth as editing a part.

- `GET /topics` → list with status, entry count, last activity
- `POST /topics` `{title}` → topic (status open)
- `POST /topics/{id}/close`, `POST /topics/{id}/reopen`
- `GET /topics/{id}` → topic with entries (newest supersedes chain
  collapsed: each entry carries `history: [...]` of what it superseded)
- `POST /topics/{id}/entries` multipart: `party`, `addressed_to` (JSON),
  `note`, `sent_at`, `supersedes_id` (optional), `files[]` → entry.
  Rejected with 409 when the topic is closed.
- `GET /dfm-files/{file_id}/download`, `GET /dfm-files/{file_id}/inline`
  (PDF for the document pane)

### 4. Tool page

`PartDetail` branches on `item_category === 'tool'`:

- Header: tool number, name, Tier 1 / customer numbers hidden (tools have
  none), then the produced articles as chips: `206.887.233 Isofix cover ·
  E1 · 003` from each article's active revision, linking to the article.
- No 3D pane, no revision strip, no revision file list, no customer data
  actions.
- **Tool tab**: the four fields as inline edits (toolmaker as a supplier
  picker, reusing the supplier options hook the create form uses).
- **DFM archive**: topic list (title, status pill, entries, last activity,
  "+ topic"). Selecting a topic opens the ledger:

```
Toolmaker                 KTX                        Tier 1
────────────────────────  ─────────────────────────  ────────────────────────
                          09-24 → Toolmaker, Tier 1
                          DFM request rev A
                          dfm_request_A.pdf  ↑CD
09-26 → KTX
DFM study rev 1
ISOFIX_DFM_r1.pdf  ↑CD
                          09-27 → Toolmaker   (updated)
                          answer, 2 points open
                          answer_r1.pdf ↑KH
                          ▸ 1 earlier version
                                                     09-30 → KTX
                                                     Brose ok on gate
                                                     mail.pdf ↑CD
                          10-01 → Toolmaker, Tier 1
                          ● Finish confirmed
```

  One row per entry, chronological, in its author's column. The arrow line
  names the addressed parties. `↑CD` is the recording user. An updated entry
  shows "(updated)" and a collapsed "earlier version" line. Each column head
  has a drop zone / "+ entry" that opens a small form: addressed to
  (checkboxes for the other two parties), note, sent date, files. "Update
  this entry" on an own-column entry opens the same form with
  `supersedes_id` set. A closed topic shows the ledger read-only with a
  "Reopen" button; an open one has "Finish confirmed".

- PDFs open in the existing document pane; other files download.

### 5. Errors

- Non-tool part on any DFM route or tool field: 400 with a plain message.
- Entry on a closed topic: 409 "Topic is finished, reopen it first".
- Supersede across topics or of an entry in another column: 400.
- Upload storage failure: 500, nothing recorded (files first, row second,
  in one transaction).

## Testing

Backend (pytest, SQLite fixtures as today):
- tool fields round-trip on a tool, 400 on an article
- topic open → entry with two files → close → entry rejected 409 → reopen →
  entry accepted
- update entry: supersedes set, old entry still returned in `history`,
  topic list shows the newest only
- cross-topic supersede rejected
- download returns the stored bytes; changelog entries written on the tool

Frontend (vitest):
- tool page hides the 3D pane and revision strip, shows produced articles
  with their revision label
- tool fields save with the right payload
- ledger puts entries in the right column in time order, shows the
  addressed-to line and the "(updated)" collapse
- entry form posts multipart with party, addressed_to, files
- closed topic renders read-only with Reopen

## Out of scope

Email to toolmaker or Tier 1 from the archive; notifications; inline
preview beyond PDF; a DFM view on the article side; migrating old DFM mails.
