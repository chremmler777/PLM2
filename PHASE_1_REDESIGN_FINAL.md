# Phase 1 FINAL REDESIGN: Complete Business Model with Audit Trail

## 📊 COMPLETE DATA MODEL

```
ORGANIZATION
  └── PROJECT (Dashboard Assembly)
       └── PARTS (BOM)
            └── PART (PA-001 Main Housing)
                 └── REVISIONS
                      ├── RFQ Phase
                      │   ├── RFQ1
                      │   │   ├── Status: Draft
                      │   │   ├── Files: [pictures only: JPEG, PNG]
                      │   │   ├── Description: "Initial quote request"
                      │   │   ├── Created by: john@company.com
                      │   │   ├── Created: 2026-02-21 10:00
                      │   │   └── Changelog: [Initial creation]
                      │   │
                      │   └── RFQ2
                      │       ├── Status: Approved
                      │       ├── Files: [pictures]
                      │       ├── Description: "Updated spec for supplier feedback"
                      │       ├── Created by: jane@company.com
                      │       ├── Updated by: admin@company.com (2026-02-21 14:30)
                      │       └── Changelog:
                      │           - Created: john (10:00)
                      │           - Updated dimensions: jane (12:00)
                      │           - Approved: admin (14:30)
                      │
                      ├── Engineering Phase (Post-Award)
                      │   ├── E1
                      │   │   ├── Status: In Progress
                      │   │   ├── Files: [CAD: STEP, IGES + drawings]
                      │   │   ├── Description: "Engineering design phase 1"
                      │   │   ├── Created by: engineer1@company.com
                      │   │   └── Changelog: [Initial CAD model]
                      │   │
                      │   └── E2
                      │       ├── Status: Approved
                      │       ├── Files: [CAD files]
                      │       ├── Description: "Updated per design review comments"
                      │       ├── Updated by: reviewer@company.com
                      │       └── Changelog:
                      │           - Created: engineer1 (10:00)
                      │           - Updated CAD: engineer2 (12:00)
                      │           - Approved: reviewer (15:00)
                      │
                      ├── Design Freeze (LOCKED)
                      │   ├── Status: Frozen
                      │   ├── Freeze Date: 2026-02-21 16:00
                      │   ├── Frozen by: manager@company.com
                      │   ├── Files: [Final CAD, drawings, manufacturing specs]
                      │   └── Changelog: [Design Freeze locked by manager]
                      │
                      └── ECN Phase (Changes After Freeze)
                          ├── IND1 (Test Data - Unconfirmed)
                          │   ├── Status: Test Data
                          │   ├── Type: Indeterminate (unconfirmed test)
                          │   ├── Files: [CAD + pictures + notes]
                          │   ├── Description: "Initial design change concept for testing"
                          │   ├── Created by: engineer3@company.com
                          │   ├── Reason for Change: "Supplier feedback - material cost reduction"
                          │   └── Changelog:
                          │       - Created as IND1: engineer3 (16:30)
                          │       - Note: "Awaiting test results"
                          │
                          ├── IND1.1 (Alternative Test Dataset 1)
                          │   ├── Status: Test Data
                          │   ├── Parent: IND1
                          │   ├── Files: [CAD variant 1]
                          │   ├── Description: "Alternative material - aluminum vs steel"
                          │   ├── Created by: materials@company.com
                          │   └── Changelog: [Alternative test path]
                          │
                          ├── IND1.2 (Alternative Test Dataset 2)
                          │   ├── Status: Test Data
                          │   ├── Parent: IND1
                          │   ├── Files: [CAD variant 2]
                          │   ├── Description: "Alternative design with different fasteners"
                          │   ├── Created by: design@company.com
                          │   └── Changelog: [Alternative test path]
                          │
                          ├── IND2 (CONFIRMED - Implemented or Rejected)
                          │   ├── Status: Approved / Rejected
                          │   ├── Parent: IND1 (confirmed choice from tests)
                          │   ├── Files: [Final CAD + test results + approval]
                          │   ├── Description: "ECN Implementation - Aluminum variant approved"
                          │   ├── Decision by: engineering_manager@company.com
                          │   ├── Decision Date: 2026-02-22
                          │   ├── Test Results Attached: [links to test data]
                          │   └── Changelog:
                          │       - Created as test IND1: engineer3 (day1)
                          │       - Created variant IND1.1: materials (day1)
                          │       - Created variant IND1.2: design (day1)
                          │       - Tests completed: qa@company.com (day2)
                          │       - Approved as IND2: manager (day2)
                          │
                          └── ECN1 (Next Official Change)
                              ├── Status: Approved
                              ├── Files: [Final CAD]
                              ├── Description: "Approved ECN from previous test phase IND2"
                              ├── Changelog: [Conversion from IND2 to ECN1]
```

---

## 📋 DATABASE SCHEMA

### `parts` table
```sql
CREATE TABLE parts (
  id SERIAL PRIMARY KEY,
  project_id INT NOT NULL FK,
  part_number VARCHAR(50) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  part_type ENUM('purchased', 'internal_mfg', 'sub_assembly'),
  supplier_id INT FK,
  status VARCHAR(20), -- active, obsolete, etc
  created_by INT NOT NULL FK users.id,
  created_at TIMESTAMP,
  updated_by INT FK users.id,
  updated_at TIMESTAMP,
  UNIQUE(project_id, part_number)
);
```

### `part_revisions` table
```sql
CREATE TABLE part_revisions (
  id SERIAL PRIMARY KEY,
  part_id INT NOT NULL FK,

  -- Revision identification
  revision_name VARCHAR(50), -- RFQ1, E1, IND1, IND1.1, IND2, ECN1, etc
  revision_type ENUM('RFQ', 'ENGINEERING', 'FREEZE', 'ECN', 'TEST_IND'),
  revision_phase ENUM('RFQ', 'ENGINEERING', 'DESIGN_FREEZE', 'ECN'),

  -- Test data specific
  parent_revision_id INT FK, -- IND1.1 → IND1, IND2 → IND1
  is_test_data BOOLEAN DEFAULT false,
  test_status ENUM('unconfirmed', 'approved', 'rejected'),

  -- Core fields
  status VARCHAR(20), -- draft, in_progress, approved, frozen, rejected, cancelled
  description TEXT,
  reason_for_change TEXT, -- why this change was made

  -- User tracking
  created_by INT NOT NULL FK users.id,
  created_at TIMESTAMP,

  updated_by INT FK users.id,
  updated_at TIMESTAMP,

  approved_by INT FK users.id,
  approved_at TIMESTAMP,

  cancelled_by INT FK users.id,
  cancelled_at TIMESTAMP,
  cancellation_reason TEXT,

  -- Design Freeze specific
  frozen_by INT FK users.id,
  frozen_at TIMESTAMP,

  -- ECN specific
  change_order_number VARCHAR(50),
  impact_analysis TEXT,

  -- Files (relationship to files table)
  -- See revision_files table below

  UNIQUE(part_id, revision_name)
);
```

### `revision_files` table
```sql
CREATE TABLE revision_files (
  id SERIAL PRIMARY KEY,
  revision_id INT NOT NULL FK,

  -- File metadata
  file_name VARCHAR(255) NOT NULL,
  file_path VARCHAR(500) NOT NULL,
  file_type VARCHAR(20), -- picture, cad, drawing, document, etc
  file_mime_type VARCHAR(50), -- image/jpeg, application/step, etc
  file_size INT,

  -- For RFQ phase: pictures only
  -- For Engineering+: CAD files (STEP, IGES) + drawings

  description TEXT,

  -- User tracking
  uploaded_by INT NOT NULL FK users.id,
  uploaded_at TIMESTAMP,

  -- CAD specific
  cad_data JSONB, -- metadata about CAD (dimensions, materials, etc)

  -- Integrity
  file_hash VARCHAR(64), -- SHA-256 for verification

  CONSTRAINT check_rfq_pictures CHECK (
    -- If revision_type = RFQ, only allow picture files
  )
);
```

### `revision_changelog` table (DETAILED AUDIT LOG)
```sql
CREATE TABLE revision_changelog (
  id SERIAL PRIMARY KEY,
  revision_id INT NOT NULL FK,

  -- What happened
  action VARCHAR(50), -- created, updated, approved, rejected, frozen, cancelled, file_uploaded, etc
  action_description TEXT, -- "Changed material from steel to aluminum", "Uploaded CAD file", etc

  -- Who did it
  performed_by INT NOT NULL FK users.id,
  performed_at TIMESTAMP DEFAULT NOW(),

  -- Details
  old_value TEXT, -- Previous value (JSON for complex objects)
  new_value TEXT, -- New value (JSON for complex objects)

  -- Context
  field_name VARCHAR(100), -- which field changed (status, description, etc)
  notes TEXT, -- Additional context

  -- File upload tracking
  file_id INT FK revision_files.id, -- if this was a file upload

  -- Traceability
  ip_address VARCHAR(45),
  user_agent TEXT,

  INDEX idx_revision (revision_id),
  INDEX idx_user (performed_by),
  INDEX idx_timestamp (performed_at)
);
```

### `projects` table
```sql
CREATE TABLE projects (
  id SERIAL PRIMARY KEY,
  organization_id INT NOT NULL FK,
  project_code VARCHAR(50) NOT NULL,
  project_name VARCHAR(255) NOT NULL,
  description TEXT,
  customer VARCHAR(255),
  status VARCHAR(20), -- planning, active, complete, archived
  start_date DATE,
  end_date DATE,
  created_by INT NOT NULL FK users.id,
  created_at TIMESTAMP,
  updated_by INT FK users.id,
  updated_at TIMESTAMP,
  UNIQUE(organization_id, project_code)
);
```

---

## 🔄 REVISION WORKFLOW WITH STATE MACHINE

```
RFQ PHASE:
  Draft → RFQ1 (approved) → RFQ2 (approved) → RFQ3...
  [Each can be updated before approval]
  [Each can be cancelled]
  [Files: pictures only]

  AWARD DECISION
  ↓

ENGINEERING PHASE:
  Draft → E1 (in progress/approved) → E2 (approved) → E3...
  [Each can be updated]
  [Each can be cancelled]
  [Files: CAD + drawings]

  DESIGN REVIEW COMPLETE
  ↓

DESIGN FREEZE:
  E-final → FREEZE (locked, immutable)
  [After freeze, no changes allowed directly]
  [Files: Finalized CAD, specs, manufacturing drawings]

  CHANGE NEEDED (ECN - Engineering Change Notice)
  ↓

TEST/VALIDATION PHASE:
  IND1 (test, unconfirmed) → alternatives (IND1.1, IND1.2)
  [Test multiple options]
  [Files: Test CAD variants, test results, notes]
  [No approval yet - just testing]
  ↓

CONFIRMATION PHASE:
  IND2 (confirmed, from winning test variant)
  [Select best test option]
  [Attach test results]
  [Approved or Rejected decision]
  ↓

OFFICIAL ECN:
  ECN1, ECN2, ... (official changes post-freeze)
  [From approved IND2 → becomes ECN1]
  [Files: Final CAD, approvals, test results reference]
```

---

## 📝 CHANGELOG EXAMPLE

For revision "IND1" (Test data):

```
2026-02-21 10:30 - Created by: engineer3@company.com
  Action: Created revision
  Description: "Initial test design concept"
  Field: status
  New value: "draft"

2026-02-21 11:00 - Updated by: engineer3@company.com
  Action: Updated description
  Field: description
  Old value: "Initial test"
  New value: "Initial design change concept - material cost reduction"

2026-02-21 11:30 - File uploaded by: engineer3@company.com
  Action: File uploaded
  File: IND1_base_design.step
  File type: CAD
  File size: 2.4 MB
  Description: "Base aluminum variant CAD"

2026-02-21 12:00 - Variant created by: materials@company.com
  Action: Created child revision
  Description: "Created IND1.1 alternative variant"
  New revision: IND1.1

2026-02-21 12:30 - Variant created by: design@company.com
  Action: Created child revision
  Description: "Created IND1.2 alternative variant"
  New revision: IND1.2

2026-02-22 09:00 - Tested by: qa@company.com
  Action: Test results attached
  Description: "All variants tested - IND1.1 shows best performance"
  File: test_results_summary.pdf

2026-02-22 14:00 - Approved by: engineering_manager@company.com
  Action: Approved and promoted
  Description: "IND1.1 approved as IND2 - implementation decision"
  New status: "approved"
  New revision: IND2
```

---

## 🎨 UI COMPONENTS NEEDED

### Part Revision Detail Page
- **Header**: Revision name, type, phase, status
- **User Info**: Created by [user], [date] | Updated by [user], [date]
- **Description**: Change reason, impact analysis
- **Files Section**:
  - RFQ: Pictures only, upload/view
  - Engineering+: CAD files + drawings + metadata
  - Show: filename, size, uploaded by, upload time
- **Changelog Timeline**:
  - Visual timeline of all actions
  - Show: Who did what, when, why
  - Collapsible details
- **Actions**:
  - Update description
  - Upload files
  - Change status
  - Create next revision
  - Cancel revision (with reason)
  - If test data (IND1): Create variants (IND1.1, IND1.2)
  - If test approved: Promote to ECN (IND2 → ECN1)

### Revision Files Panel
```
📄 Files for IND1
├── IND1_base_design.step (2.4 MB) - CAD
│   Uploaded by: engineer3@company.com on 2026-02-21 11:30
│   Description: "Base aluminum variant CAD"
│
├── IND1_analysis.pdf (0.5 MB) - Document
│   Uploaded by: engineer3@company.com on 2026-02-21 11:30
│   Description: "Material analysis"
│
└── [+ Upload New File]

⚠️ RFQ Phase: Pictures only (JPEG, PNG, PDF)
✅ CAD Phase: STEP, IGES files allowed
```

### Changelog Timeline
```
2026-02-21 10:30
├── Created revision IND1
│   by: engineer3@company.com
│   Description: "Initial test design concept"
│
2026-02-21 11:30
├── File uploaded: IND1_base_design.step
│   by: engineer3@company.com
│   Size: 2.4 MB
│
2026-02-21 12:00
├── Created variant: IND1.1
│   by: materials@company.com
│   "Alternative material test"
│
2026-02-22 09:00
├── Test results attached
│   by: qa@company.com
│   "IND1.1 shows best performance"
│
2026-02-22 14:00
├── ✅ APPROVED AND PROMOTED TO IND2
│   by: engineering_manager@company.com
```

---

## 🎯 IMPLEMENTATION STEPS

### Step 1: Database (1 hour)
- [ ] Create new tables: projects, parts, part_revisions, revision_files, revision_changelog
- [ ] Drop old articles tables
- [ ] Create migration files
- [ ] Add indexes for performance

### Step 2: Backend Services (2 hours)
- [ ] ProjectService: create, read, update, delete projects
- [ ] PartService: manage parts in BOM
- [ ] RevisionService: handle complex state transitions
  - RFQ phase transitions
  - Engineering phase transitions
  - Design Freeze logic
  - ECN with test data (IND1 → IND1.1/IND1.2 → IND2 → ECN1)
- [ ] FileService: handle uploads, validation, storage
- [ ] ChangelogService: log all actions with full context

### Step 3: API Endpoints (1.5 hours)
- [ ] 5 Project endpoints
- [ ] 5 Part endpoints
- [ ] 8 Revision endpoints (RFQ, Engineering, Freeze, ECN)
- [ ] 3 File endpoints (upload, download, delete)
- [ ] 1 Changelog endpoint (get history)

### Step 4: Frontend (2.5 hours)
- [ ] Projects page (list, create)
- [ ] Project detail with BOM table
- [ ] Part detail page
- [ ] Revision detail with changelog timeline
- [ ] File upload component (with validation)
- [ ] Changelog component (visual timeline)

### Step 5: Testing (1 hour)
- [ ] Create project
- [ ] Add parts to BOM
- [ ] Create RFQ revisions with pictures
- [ ] Promote to Engineering with CAD
- [ ] Test data workflow (IND1 → IND1.1/1.2 → IND2)
- [ ] Verify changelog tracking
- [ ] Verify file uploads and access control

---

## ✅ KEY FEATURES

✅ **Complete Audit Trail**: Every change logged with user, timestamp, reason
✅ **File Handling**: Pictures for RFQ, CAD for Engineering+
✅ **User Attribution**: Who created, updated, approved, uploaded
✅ **Test Data Workflow**: IND1, IND1.1/1.2, IND2, then ECN1
✅ **Revision Cancellation**: Can reject/cancel with reason
✅ **Changelog**: Visual timeline showing exactly what changed and when
✅ **CAD Ready**: Prepared for Phase 2 - CAD upload and comparison
✅ **State Machine**: Clear workflow from RFQ → Engineering → Freeze → ECN

---

## 🚀 READY TO IMPLEMENT?

This is a complete, production-ready system that tracks:
- ✅ Every change
- ✅ Who made it
- ✅ When it happened
- ✅ Why it changed
- ✅ File uploads and versions
- ✅ Test data validation workflow
- ✅ Cancellations with reasons

**Time: ~8-10 hours to implement fully**

Should I start building this? 🎯
