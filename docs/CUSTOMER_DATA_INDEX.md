# Customer data index and BOM

How PLM names revisions, what the part lifecycle phase means, and how the
bill of materials follows a revision. Written for the people who record
customer data and maintain assemblies. Design background:
`docs/superpowers/specs/2026-09-17-customer-data-index-design.md`.

## One rule

**The major number is always a customer-stated data state. The minor number
is always our internal iteration on it.**

| Name | Meaning | Who creates it |
|---|---|---|
| `E1`, `E2`, … | Customer sent data and said it is **review** data. Nothing is binding. | You, via **+ Customer data** |
| `E1.1`, `E1.2`, … | Our own proposal on top of E1 | You, via **+ Proposal**, or the change engine |
| `1`, `2`, … | Customer sent data and said it is **official**. Released, binding for tooling, PPAP, cost. | You, via **+ Customer data** |
| `1.1`, `1.2`, … | Our own proposal on top of 1, usually an ECR | You, via **+ Proposal**, or the change engine |

- The customer decides what is review and what is official. PLM only records
  that statement, with the customer's own index letter and the date received.
- The E counter and the numeric counter are independent and **never reset**.
  Quote data E1, E2 and nominated data E3 stay E1, E2, E3.
- Once a part has official data, new review data is refused. The customer
  cannot un-release data.
- A promoted proposal is a customer-adopted state, so promoting asks for the
  same statement, index and date as new customer data.

## Part lifecycle phase

Separate from the revision counter. Set by an admin on the part page with
**Mark nominated** and **Mark series**.

| Phase | Meaning |
|---|---|
| `rfq` | Quoting. Default for a new part. |
| `nominated` | Awarded. Sets the nomination date. |
| `series` | Running production. Sets the SOP date. |

Every revision remembers the phase the part was in when it arrived, so a
list reads `E2 · rfq`, `E3 · nominated`, `1 · nominated`.

## Recording customer data

On the part page, or on the project page with the part selected:

1. **+ Customer data**.
2. Pick **review** or **official**, exactly as the customer stated it.
3. Enter the received date and, if there is one, the customer index letter
   (the `.B` in `3CR.807.425.B`). Summary is optional. Optionally type the
   revision number if the customer's numbering is ahead of ours (a part may
   start at E2). It must be above every existing revision of that kind.
4. Save. The new major becomes the part's active revision.

The new major **copies the BOM** from the previous major, so an E2 never
starts with an empty bill of materials.

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

## Proposals

**+ Proposal** on any major creates the next minor (`E1.1`, `1.1`) as a draft
with a copy of the major's BOM. Edit files and lines there. When the customer
adopts it, use **Customer adopted** on the proposal: this creates the next
major from it, marks the proposal approved and rejects its siblings.

## Receiving a package

A delivery is usually the assembly file plus one file per part, and not
every part changed. On the assembly, **+ Customer package**:

1. Pick review or official, the received date, and (optionally) the index
   the whole package carries. Drop all files.
2. **Check package.** Every file is matched to a part by the customer part
   number (or our number) in the filename — the customer part number is set
   and edited on the part itself. The index is read from the filename
   (`3CR807425B_…` → `B`), else the package index applies.
3. Per file the table says what will happen:
   - **new major**: the index differs from the part's active revision → the
     part gets its next major with this file.
   - **unchanged**: same index as the active revision → nothing is stored,
     the E stays. *If the data did not change, the E does not change.*
   - **unmatched**: pick the part yourself, or leave it and the file is
     skipped. A file the system cannot match to any part is skipped no
     matter its type.
   Part, index, action and revision number can be corrected per row.
4. **Store package.** Children first, then the assembly, whose new major
   copies its BOM forward so lines point at the children's active
   revisions. Any row error (unsupported file, revision number not above
   the existing one, review after official) stops the whole package;
   nothing is stored until every row is fixed.

Revision names show the customer index everywhere as `E2 · B`.

## Bill of materials

A BOM lives on a revision and its lines point at real parts, so the BOM of an
assembly is a tree by construction: each child has its own active revision
with its own lines.

### Where to see it

- **Project page → Assemblies** chip: top-level assemblies of the project.
  A top-level assembly is an article we make ourselves that sits on nobody
  else's BOM, whether or not it has lines yet (`no BOM yet`). Expand an entry
  to walk its tree in place. Click any node to open that part on the right.
- **Project page → selected part**: the **Bill of materials** card shows the
  tree for the revision chosen in the dropdown, with **Used in** chips that
  lead to every parent up to the top assemblies.
- **Part page**: same tree and used-in strip.

Quantities multiply through the tree. A bolt used three times in a
sub-assembly that appears twice reads as `3 pcs`, total `Σ 6`. Children show
their active revision badge; purchased parts are marked.

### Where to edit it

Project page, right column, the **BOM — E1** card under the tree.
**+ Add Item** takes a project part, a catalog part or free text, with
quantity, unit and a note. Positions number themselves 10, 20, 30. Quantities
edit inline. Editing is locked on frozen, cancelled and archived revisions.

Lines resolve to the child's **active** revision. Pinning a specific child
revision per line is a planned extension for released BOMs.

## Legacy data

Migration 072 renamed everything that existed before this scheme, per part
in creation order, ids unchanged:

| Before | After |
|---|---|
| `RFQ1`, `RFQ2`, `ENG1` | `E1`, `E2`, `E3` (review) |
| `IND1`, `IND2` | `1`, `2` (official) |
| `ECR1.1` | `1.1` under official 1, or `E1.1` if the part never had official data |
| `WC-IMP` (WinCarat import baseline) | `1` (official, source `import`), part set to `series` |

WinCarat was a one-time bulk source and is read-only. New projects start in
PLM.

## Customer file names (VW group convention, used by Brose)

A VW-world delivery looks like this:

    206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.CATPart
    206_881_479____DRW_TZ__001_____INNER_SIDE_COVER___B-RELEASE___20260528.pdf

| Piece | Meaning | Where it lands in PLM |
|---|---|---|
| `206_881_479` | VW part number: model code, main group (881 = seat), item. A trailing letter (`206_881_971_B`) is a variant of the same part. | `customer_part_number`, dotted (`206.881.479`) |
| `PCA`, `DMU`, `DRW` | Data type, see below | file type and file note |
| `TM`, `TZ` | `TM` Teilemodell (part model), `TZ` Teilezeichnung (part drawing) | file note |
| `003` | **Customer data index** of that file. The 3D index is the state of the part; the drawing carries its own. | 3D index → customer index on the major (`E1 · 003`) |
| `INNER_SIDE_COVER` | Part name | part name stays ours |
| `B-RELEASE`, `CP3` | Release stage the customer declared | customer statement (review or official) and summary |
| `20260528` | Date of the data state | received date |

Assembly children use a position token instead of the data type
(`206_881_971____G02_TM__004_003_MAP_POCKET`): `G02` is position 2 of
assembly 206.881.971, `004` the assembly index, `003` the position's own index.

### Data types

| Token | What it is | How we treat it |
|---|---|---|
| `PCA` | Full construction model: parametric CATIA part with RPS, reference points and lines, annotations, history. 2 to 7 times the size of the DMU. | **Engineering master.** The file to open in CATIA; RPS and datums drive tool, gauge and measurement design. STEP for toolshops and the viewer is exported from this one. |
| `DMU` | Digital mock-up: reduced solid of the same state, no RPS, no references. | Convenience file for packaging and quick opens. Archived as received, not worked from. |
| `DRW` | Customer drawing, delivered as PDF. | Stored as drawing on the same major. Mirrored parts (LH/RH, 40/60) are **not** copied: the mirror part carries a `mirror_of` relation to the part that holds the data, and only files delivered under the mirror's own number are attached to it. |
| `OUT` | Name of the delivery folder that holds the DMU and PCA pair. | Not a file, ignored. |

Rule: **keep every customer file as received on the revision it belongs to**, both
PCA and DMU. The B release is the design record for PPAP and any later dispute.
STEP, glb and anything else we derive never replaces it.

## API

| Call | Purpose |
|---|---|
| `POST /api/v1/parts/{id}/revisions/customer-data` | Next major from a customer statement (accepts `major` to pin the revision number) |
| `POST /api/v1/parts/{id}/revisions/customer-package/preview` | Match files to parts, decide new/unchanged |
| `POST /api/v1/parts/{id}/revisions/customer-package` | Store the confirmed package |
| `POST /api/v1/parts/{id}/revisions/proposals` | Next minor under a major |
| `POST /api/v1/parts/{id}/revisions/{rev}/promote` | Customer adopted a proposal |
| `POST /api/v1/parts/{id}/lifecycle-phase` | `rfq → nominated → series`, admin only |
| `GET /api/v1/parts/{id}/bom-tree?revision_id=` | Multi-level explosion, quantities multiplied |
| `GET /api/v1/parts/{id}/where-used` | Parents up to the top assemblies |
| `GET /api/v1/parts/project/{id}/assemblies` | Top-level assemblies of a project |

Review data after official data returns `409`.
