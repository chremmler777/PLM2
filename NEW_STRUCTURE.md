# New PLM Structure: Dashboard First

## 🎯 Landing Page: Dashboard

The new landing page shows the organizational hierarchy:

```
Dashboard
  ├── Plants (left column)
  │   └── Select a manufacturing facility
  ├── Projects (middle column)
  │   └── Select a project in the plant
  └── Parts (right column)
      └── View parts (BOM) in the project
```

## 📊 Navigation Flow

```
Login → Dashboard (Plant → Project → Parts) → Project Details → Part Details
```

## 🔄 Data Model Hierarchy

```
Organization (tenant)
  └── Plant (facility)
       └── Project (e.g., "Dashboard Assembly")
            └── Part (e.g., "PA-001 Main Housing")
                 └── PartRevision (RFQ1, ENG1, ENG1.1, IND1, ECR1.1, IND2)
                      └── RevisionFile (CAD, pictures, documents)
```

## 📝 Article System → Part System

### Old System (Deprecated)
- Articles (generic, not project-specific)
- Global article creation
- No clear business process

### New System (Current) ✅
- Parts (engineering parts in specific projects)
- Part creation within projects
- Clear RFQ→ENG→FREEZE→ECR workflow
- BOM (Bill of Materials) support

---

## 🚀 Features by Page

### Dashboard Page
- **Plants Column:** List all manufacturing facilities
- **Projects Column:** List all projects in selected plant
- **Parts Column:** List all parts in selected project
- **Summary:** Overview of current selections

### Project Details Page (Next)
- BOM table showing all parts
- Part creation button
- Part filtering/searching

### Part Details Page (Next)
- Revision tree (RFQ1 → ENG1 → ENG1.1/ENG1.2 → ENG2 → IND1 → ECR1.1 → IND2)
- File manager (upload CAD, pictures)
- Changelog timeline
- Revision actions (create proposal, approve, reject, freeze)
- 3D viewer for CAD files

---

## 🔗 API Endpoints

### Plants
- `GET /api/v1/plants` - List all plants for org
- `GET /api/v1/plants/{plant_id}/projects` - List projects in plant

### Projects
- `GET /api/v1/projects` - List all projects
- `POST /api/v1/projects` - Create project

### Parts
- `POST /api/v1/parts` - Create part in project
- `GET /api/v1/parts/{id}` - Get part details
- `GET /api/v1/parts/project/{project_id}` - List project parts

### Revisions
- `POST /api/v1/parts/{id}/revisions/rfq` - Create RFQ
- `POST /api/v1/parts/revisions/{id}/to-engineering` - Transition to ENG
- `POST /api/v1/parts/revisions/{id}/propose-engineering` - Create proposal
- `POST /api/v1/parts/revisions/{id}/approve` - Approve proposal
- `POST /api/v1/parts/revisions/{id}/freeze` - Create design freeze
- `POST /api/v1/parts/revisions/{id}/propose-ecr` - Create ECR proposal
- `POST /api/v1/parts/revisions/{id}/approve-ecr` - Approve ECR

---

## 💡 Test Data Creation

To test the new system, you need:

1. **Organization** (already created: "Test Organization")
2. **Plant** (already created: in Test Organization)
3. **Projects** (create in UI - dashboard will show them)
4. **Parts** (create in projects - dashboard will list them)
5. **Revisions** (create from part detail - RFQ → ENG → ECR workflow)

### Create Test Plant (if needed)
```sql
INSERT INTO plants (organization_id, name, code, location, is_active, created_at)
VALUES (1, 'Main Factory', 'MAIN', 'Germany', true, NOW());
```

### Create Test Project (if needed)
```sql
INSERT INTO projects (plant_id, name, code, description, status, created_at, updated_at)
VALUES (1, 'Dashboard Assembly', 'DA-001', 'Automotive dashboard project', 'active', NOW(), NOW());
```

---

## 🔐 Multi-Tenancy

- Users belong to **Organizations**
- Plants belong to **Organizations**
- Projects belong to **Plants**
- Parts belong to **Projects**
- All queries automatically scoped to user's organization

---

## 📱 UI Components Used

### Dashboard
- Three-column layout (plants, projects, parts)
- Responsive button grid
- LoadingSkeleton for async data
- Toast notifications
- Summary cards at bottom

### Future Components
- RevisionTree (sidebar tree view)
- RevisionTable (list view with status badges)
- ChangelogTimeline (visual timeline)
- FileUploadPanel (drag-and-drop CAD upload)
- RevisionActions (buttons for state transitions)

---

## ✅ Testing Checklist

- [ ] Login with test@example.com / password
- [ ] See Dashboard with Plants
- [ ] Click Plant to see Projects
- [ ] Click Project to see Parts
- [ ] See Summary section with counts
- [ ] (Later) Create parts and revisions

---

## 📚 Related Documentation

- `PHASE_1_REDESIGN_FINAL.md` - Complete business model specification
- `PHASE_1_REDESIGN_PROGRESS.md` - Implementation details and API docs
