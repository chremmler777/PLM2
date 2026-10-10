# Customer data revision / intake: PLM research (2026-10-10)

Scope: how established PLM/PDM systems and automotive practice separate file updates from formal revisions, receive external deliveries, and let one revision carry documents at different indexes. Evidence quality: web search only; vendor docs where found, otherwise community posts (flagged). Not verified: Propel, OpenBOM, Fusion Manage, Windchill Package/Receive, Teamcenter supplier-collaboration specifics, VDA 4961 text. These were not found in search and are NOT claimed below.

## 1. How the systems model it

**PTC Windchill.** A version is letter plus number: the letter is the revision, the number is the iteration. Every check-in creates a new iteration (A.1 -> A.2); only the explicit Revise action creates a new revision (A.x -> B.1). The lifecycle state matters: while "In Work" you keep adding iterations; once released, the revision is locked and further changes require Revise. Sources: [Windchill Help: revisions, iterations, versions](https://support.ptc.com/help/wnc/r12.0.0.0/en/Windchill_Help_Center/folders/OverviewFolderRevisIterVers.html), [PTC community thread](https://community.ptc.com/windchill-10/windchill-10-2-revise-on-checkin-40578).

**Siemens Teamcenter.** Parts are Item -> Item Revision; files live in Datasets attached to an Item Revision. What is copied or referenced on Revise is controlled by Deep Copy Rules (e.g. "CopyAsReference" instead of copying, to avoid duplicate PDF datasets). Which revision a user sees depends on a configurable Revision Rule (default "Latest Working"). Take-away: files hang under the revision as sub-objects; revising does not force every file to be duplicated. Sources: [Siemens KB, duplicate PDF datasets](https://support.sw.siemens.com/en-US/okba/PL8785514/Duplicate-PDF-datasets-created-under-Item-Revision-in-Teamcenter-Rapid-Start/index.html), [Solid Edge API doc on revision rule](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFramework~SolidEdgeTCE~ReviseToTeamCenter.html).

**Dassault 3DEXPERIENCE / ENOVIA.** Maturity states In Work -> Frozen -> Released; Released is read-only and final. "New Revision" on a released object moves to the next primary revision (letter or number) with a secondary minor component reset, back in In Work. Optional minor-revision mode exists. Note: sources are community/reseller pages, not Dassault docs. Sources: [3DS community: minor/major revisions](https://3dswym.3dexperience.3ds.com/post/catia-user-community/how-to-handle-minor-and-major-revisions-3dx_1vy4UZR_Q7axYYNrMbjSxQ), [GoEngineer: maturity graph](https://www.goengineer.com/en-us/blog/changing-3dexperience-maturity-graph-engineering-definition).

**Autodesk Vault.** Version = each saved iteration of a file; revision = a labelled group of versions, created by Revise or automatically by a lifecycle state change. Cheap, state-driven. Sources: [Vault help](https://help.autodesk.com/cloudhelp/Help/ENU/Vault/files/GUID-1FAD3749-175C-485F-A09E-41EA5D41E5CA.htm), [Autodesk blog](https://www.autodesk.com/blogs/design-and-manufacturing/why-file-versioning-alone-isnt-enough-for-engineering-teams/).

**Aras Innovator.** Two independent counters: Major_Rev (formal) and Generation (auto-incremented on every edit-unlock). Minor_rev exists but is reserved/unused. Opening an item shows latest revision and generation. Source (forum quoting docs, partly old): [Aras community](https://www.aras.com/community/f/archive/2590/developers-forum---minor-revision-generation-as-0-1-0-2-0-3).

**SAP DMS (document info record).** Document key = number + type + part + version. Revision levels only exist when a change master (change number) is used; a revision is assigned automatically when a version is first released against a change number; one revision level per version. The document therefore has its OWN version/revision, independent of the material. Sources: [SAP help: ECM in DMS](https://help.sap.com/saphelp_46C/helpdata/EN/c1/1c2aaf43c711d1893e0000e8323c4f/content.htm), [SAP help: changing a revision level](https://help.sap.com/saphelp_46C/helpdata/EN/c1/1c2b1743c711d1893e0000e8323c4f/content.htm).

**Arena PLM.** Only user reviews found: a change order is the only way an item goes to the next effective revision; the revision is checked at change-order creation, so parallel change orders can produce conflicting revisions (a cautionary example of ECO-heavy design). A "working revision" for uploads exists (inferred from tooling, not a doc). Sources: [Capterra reviews](https://capterra.com/p/6101/Arena-PLM/reviews/), [AWS Marketplace reviews](https://aws.amazon.com/marketplace/reviews/reviews-list/prodview-qq5ec4eo77jvq?page=18).

**Automotive practice (not a PLM).** VDA 4953-1 (simplified drawing) moves master data into a separate Master Data Sheet whose version can advance for non-geometric changes while the drawing/geometry stays unchanged, i.e. documents carry independent change states. VDA 4953-2 describes drawing-free documentation: 3D (JT), STEP AP242 metadata and a PDF/A in one container, so the model is the master. Sources: [Hella/Forvia VDA 4953 supplier presentation](https://WWW.HELLA.COM/forvia-com/assets/documents/Simplified_Drawing_Supplier.pdf), [VDA 4953-2](https://webshop.vda.de/VDA/en/vda-4953-112014en). Data exchange: ENGDAT over OFTP2 is the OEM transport; tools such as PROSTEP OpenDXM GlobalX generate/interpret ENGDAT packages and push them into PDM/SAP, i.e. the delivery arrives as one package with metadata, and is matched on import. Sources: [PROSTEP newsletter](https://newsletter.prostep.com/en/newsletter/prostep-newsletter-12018/prostep-newsletter-12018-4), [Stabilus/GlobalX](https://newsletter.prostep.com/en/newsletter/prostep-newsletter-42025/stabilus-uses-opendxm-globalx-for-tisax-compliant-data-exchange). VDA 4961 itself was not retrievable.

## 2. Patterns that matter for us

1. **Version/iteration vs revision is universal.** Windchill, Vault, Aras and 3DX all split "file saved again" (cheap, automatic, no approval) from "formal index step" (explicit act, state-gated). A formal revision is only created deliberately; a second file arriving is an iteration of what is already open.
2. **The open revision absorbs changes.** In Windchill/3DX an In Work revision keeps taking iterations; a new revision is only possible after release/freeze. This is exactly the fix for "second upload silently creates another major and archives the waiting one".
3. **State, not wording, drives behaviour.** Lock/unlock, and which revision series is used, follow lifecycle state (In Work / Released) set by an internal gate, not by labels the sender chose.
4. **Documents have their own revision.** SAP DMS (document version independent of the material), Teamcenter (datasets under a revision, deep-copy rules decide carry-over), VDA 4953-1 (master data sheet vs drawing). A part revision "points at" documents; each document keeps its own index.
5. **Inbox/receive matches on metadata.** ENGDAT packages carry the metadata; the receiver matches to parts. Where matching fails, a human assigns. No system silently attaches to "current".
6. **Do not gate everything with a change order.** Arena reviews show the pain of ECO-only revision control (conflicting parallel orders).

## 3. Recommended simplest model for PLM2

### 3.1 One flow: "Customer sent data"
Replace the four paths (customer-data button, upload "next customer data", package receive, "customer adopted" promote) with ONE entry point. Receive, upload, and the old buttons all open it.

1. **Drop files** (any number, any mix: CATPart, STEP, PDF, other).
2. **Auto-match per file**: part number (filename convention OR CATPart/STEP/PDF metadata OR title block OR manual pick), customer index, file date. If a file cannot be matched, it stays in the list with a visible "unassigned" state and an inline picker. Never default to "current index".
3. **Group by part** (one delivery = N parts x M files; CATPart+STEP+PDF of one part end up together).
4. **One decision per part**, with a sensible default:
   - "Add to open revision" (default when an unreleased/pending revision exists, or when the customer index equals the one we already hold),
   - "New customer index" (default when the detected index is higher than anything we hold),
   - plus "Not now / park in inbox".
   The user never picks "major" or "E vs numeric"; the system derives it (see 3.3).
5. **Result**: files attach as iterations of the chosen revision. Re-delivery of the same index just adds or replaces files (iteration), keeping history. Nothing is archived automatically; only a new index supersedes the previous revision.

"Customer adopted" (our proposal x.1 becomes official) stays a separate, rare explicit action, but it should create a record through the same engine so there is one code path for "new major".

### 3.2 "Old drawing, new data"
- **Every file keeps its own customer index** (and date). The revision is the container; the index is a property of the file, as in SAP DMS/VDA 4953-1.
- The revision's own customer index = the index of the **model** (CAD leads; VDA 4953-2 treats the model as master).
- When a new model index arrives and no new drawing comes with it, the new revision **carries the previous drawing by reference** (Teamcenter "CopyAsReference"), shown as: `Drawing: idx 002 (model: 004)`. No copying.
- Computed flag, not a workflow: **"Drawing older than model"** when drawing index < model index. Cleared automatically when a drawing at the model index (or an explicit "drawing unchanged, confirmed by customer" mark) is attached. This is a warning chip, not a blocker, except possibly at release/PPAP time (owner decision).
- Corollary: a delivery with only a PDF at an older index than the model is accepted as "drawing update", not as a new revision.

### 3.3 E vs numeric: project phase decides
- Store the **project phase** on the project (e.g. quoting/DFM, design freeze/tool start, serial, post-SOP). Revision label is derived: before design freeze = `E<n>`; from design freeze on = `<n>` official. The sender's words ("B-Release", "DRAFT_MOD", "004") are stored as the customer index/status text, shown, searchable, but never used to choose E vs numeric.
- The first numeric is created by the **phase change** itself ("design freeze reached: promote current E to 1"), a deliberate internal gate (analogous to Windchill/3DX release or Aras generation vs revision).
- x.1 proposals stay internal iterations-with-label on top of a major, as defined.

### 3.4 Where triage stays
Keep it, but shrink it:
- **Auto-pass** (no triage): same index re-delivered, or drawing-only update at lower-or-equal index, or any delivery while the project is pre-freeze (E-data, non-binding). These only attach.
- **Triage required**: a **higher customer index after design freeze** (official data may change tooling, cost, timing). Keep the existing four routes (administrative, engineering review, attach to ECR, full ECR) but trigger them once per index, not per upload. A pending index absorbs further files until triage is decided.
- Triage state lives on the revision (like a lifecycle state: Received -> Triaged -> Active), not as a separate intake object that competes with the revision.

### 3.5 What NOT to copy
- Windchill/Teamcenter/3DX-style multi-level numbering (A.1, secondary minor, generation counters) on top of E/numeric/x.1; we already have enough.
- Deep Copy Rule / Revision Rule configuration engines: use one fixed rule ("carry documents by reference unless replaced").
- Mandatory change order for every index (Arena pain): only post-freeze higher index goes through triage/ECR.
- Separate maturity graphs per object type; one small state set on the revision is enough.
- Heavy ENGDAT/OFTP infrastructure; irrelevant until a customer demands it. Metadata-based matching (part no, index, date) is the useful idea.
- Dual masters: do not model the drawing as a separate lifecycle object with its own approvals. A file with its own index is enough.

## 4. Open questions for the owner
1. Is the model always the leading index, or can a customer deliver a new drawing index with the model unchanged (VDA 4953-1 style master-data-only change)? Should that create a new revision at all?
2. Should "drawing older than model" block anything (release, sample, PPAP, tool start), or only warn?
3. What defines design freeze in the system: a manual phase switch per project, or a customer milestone date? Who may change it?
4. Which filename/metadata conventions per customer are reliable enough for part number and index auto-detection (Brose, VW, Scout, Daimler)? Are PDF title blocks readable?
5. After design freeze, which cases truly need triage (any higher index, or only geometry-relevant ones)? Who may mark "no change" quickly?
6. When a same-index file is re-sent with different content, replace silently, or keep both with a note?
7. Do we need to know "customer sent index X on date Y" even when we never activate it (audit trail)? Suggested: yes, keep the delivery record, cheap.
8. Should the "customer adopted" flow remain visible in the UI, or be hidden under the revision's menu since it is rare?
