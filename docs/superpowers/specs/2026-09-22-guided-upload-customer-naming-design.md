# Guided upload with customer file naming

Date: 2026-09-22. Status: approved design, awaiting plan.

## Problem

Uploading customer data to a part today is a bare drop zone on the project
page: one file at a time, the type is inferred from the extension, nothing is
read from the filename, and nothing tells the user what the file is (PCA vs
DMU) or which customer index it carries. Receiving customer data is a second,
separate dialog that takes no files. The filename parser only understands a
single trailing letter (`3CR807425B`), not the VW group numeric index
(`__003__`) that Brose and VW deliver.

## Ruling (user, 2026-09-22)

- `E1, E2, …` and `1, 2, …` are **our filing order**. The customer index is
  informational, shown next to it (`E1 · 003`), optional, and never decides
  anything. Detection prefills, the user chooses.
- On every upload the user chooses the level: attach to the current
  revision, next customer major (`E1 → E2`, or `1` once official), or next
  proposal (`E1 → E1.1`, feasibility). Proposals need no customer index.
- Naming convention: project default, overridable per upload, because
  customers are not consistent. Always show current index, detected index,
  and an editable override.

## Design

### 1. Project setting: customer file naming

`projects.customer_naming` (String(20), nullable, default `NULL` = none).
Values: `vw` (VW group / Brose / Audi), `scout`, `null`. Scout is registered
now so the dropdown carries it; until a Scout filename is seen it parses like
`vw`. New values are added to one registry (below), not scattered.

- Migration 075 adds the column.
- `PATCH /api/v1/plants/projects/{project_id}` accepts `{customer_naming}`
  (plus the existing `ProjectUpdateRequest` fields, which today have no
  endpoint). Admin/engineer roles as for project create.
- Project list and project detail responses include `customer_naming`.
- UI: a small select in the project header on the project page, label
  "Customer file naming", options None / VW group / Scout. Saves on change.

### 2. Filename parsing registry

`backend/app/services/customer_naming.py`:

```
@dataclass
class ParsedName:
    customer_part_number: str | None   # "206.881.479"
    variant: str | None                # "B" from 206_881_971_B
    kind: str | None                   # PCA, DMU, DRW, G02, …
    kind_label: str | None             # "PCA engineering master …"
    model_type: str | None             # TM, TZ
    customer_index: str | None         # "003"
    release: str | None                # "B-RELEASE", "CP3"
    dated: date | None                 # 20260528

CONVENTIONS: dict[str, Convention]   # "vw", "scout"
def parse_filename(filename, convention, customer_part_number=None) -> ParsedName
```

- `vw`: regex on the stem, `^(\d{3})_(\d{3})_(\d{3})(?:_([A-Z]))?_+([A-Z0-9]{3})_([A-Z]{2})__(\d{3})`,
  then release stage and date tokens from the tail. Kind labels come from one
  table shared with the file note (PCA, DMU, DRW, and `G\d\d` = assembly
  position). Unknown kinds are passed through with no label.
- `None` convention: falls back to today's `index_from_filename` (trailing
  letter after the dotted number) so existing behaviour is unchanged.
- The package preview keeps using `index_from_filename` and additionally
  tries the project convention, project index wins over letter index when the
  convention is set. Existing package tests stay green.
- `GET /api/v1/parts/{part_id}/files/parse?filenames=a&filenames=b&convention=vw`
  returns `ParsedName` per filename. Pure function behind it, unit tested
  with the real Brose names (PCA/DMU/DRW, latch cover 004, ISOFIX 001, G02
  positions, `_B` variant, the `_2026-05-28` date form, and a non-matching
  name).

### 3. Upload endpoint

`POST /api/v1/parts/{part_id}/revisions/{revision_id}/files` gains optional
form fields next to the existing `file_type`:

- `note` (str, ≤ 500): stored in `cad_data.note` for CAD, in a new
  `revision_files.note` column (String(500), nullable, migration 075) for
  every type so drawings and documents carry it too.
- `kind` (str, ≤ 10): stored in `cad_data.kind` for CAD (`PCA`, `DMU`).

`RevisionFileResponse` exposes `note` and `kind`. The file row in the
project page shows a kind chip (`PCA`, `DMU`, `DRW`) and the note under the
name.

### 4. Upload dialog

`components/parts/UploadDialog.tsx` replaces the bare `CADUploader` on the
project page part panel (`CADUploader` stays for the legacy part-level path
and the part page until those are migrated, out of scope here).

Opens on drop or click. Layout, top to bottom:

1. **Files.** Multi-select drop zone. One row per file: name, size, type
   select (CAD / drawing / picture / document, prefilled from the extension),
   kind chip with its label, detected index chip. Remove per row. Rows come
   from the parse endpoint, re-fetched when the convention changes.
2. **Naming convention.** Select, prefilled from the project, options None /
   VW group / Scout. A one-line hint under it: "used to read the customer
   index and data kind from the filenames".
3. **Level.** Three radios:
   - *Attach to `E1 · 003`* (current revision name and index). Default when
     the detected index equals the current one or nothing was detected.
   - *Next customer data → `E2`* (or `2`, from `nextMajor`). Default when a
     detected index differs from the current one. Reveals: statement
     review/official (official-only rule as in `CustomerDataDialog`),
     received date (prefilled from the parsed date, else today), customer
     index field with "current 003 · detected 004" beside it and the
     detected value prefilled, editable, optional; summary optional.
   - *Next proposal → `E1.1`*. Reveals summary only.
   If the files carry two different detected indexes the dialog shows a
   warning and does not prefill the index.
4. **Save.** Creates the revision if a new level was chosen (existing
   `customer-data` / `proposals` endpoints), then uploads every file to the
   target revision with `file_type`, `kind`, `note` (the kind label). One
   progress line "3 of 4 uploaded". A failed file stops the loop and reports
   which files landed; the created revision stays (it is valid without
   files). Invalidates `part`, `revision-files`, `revisions`.

`CustomerDataDialog` stays for "+ Customer data" without files.

### 5. Out of scope

- Scout-specific grammar (none seen yet).
- Migrating the part page and legacy part-level upload to the new dialog.
- Batch receive across many parts (that is the assembly package flow).
- Editing kind/note on an existing file.

## Testing

- Backend: parser unit tests (registry, VW names above, None fallback), PATCH
  project field, upload with `note`/`kind`, parse endpoint, package preview
  with convention set.
- Frontend: `UploadDialog` tests for default level selection (same index →
  attach, different → next major, none → attach), convention change
  re-parses, index override reaches the request, proposal hides index,
  mixed-index warning, sequential upload with a failure mid-way. Project
  header select saves. File row shows kind chip and note.
