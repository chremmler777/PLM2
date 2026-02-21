# GO KTX PLM v2 - Production-Ready Product Lifecycle Management System

A complete rewrite of the PLM prototype for production use with TISAX AL3 compliance, targeting automotive customer CAD/prototype data management for ~30 users on a local server.

## Project Status

**Phase 0: Project Scaffolding** ✅ COMPLETE

- Backend project structure with FastAPI + SQLAlchemy 2.0 + Alembic
- Frontend project structure with React 18 + TypeScript strict + Vite
- Docker Compose dev environment (PostgreSQL 16 + Redis 7)
- Database models (13 core tables + relationships)
- Initial Alembic migration (001_initial_schema)
- Basic FastAPI app with health endpoints
- Configuration management (Pydantic Settings)
- Authentication utilities (JWT, bcrypt)
- Schema layer (Pydantic models for API)

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Backend** | FastAPI | 0.109.0 |
| **Database** | PostgreSQL | 16 |
| **ORM** | SQLAlchemy | 2.0.25 |
| **Async** | asyncpg | 0.29.0 |
| **Migrations** | Alembic | 1.13.1 |
| **Cache** | Redis | 7 |
| **Frontend** | React | 18.2.0 |
| **Bundler** | Vite | 5.0.11 |
| **State** | React Query | 5.17.0 |
| **3D Graphics** | Three.js | 0.160.0 |

## Project Structure

```
plm2/
├── backend/
│   ├── app/
│   │   ├── api/v1/              # API endpoints
│   │   ├── core/                # Config, database, security
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── services/            # Business logic
│   │   ├── dependencies/        # DI & auth
│   │   ├── middleware/          # Middleware
│   │   ├── auth/                # Auth utils
│   │   └── utils/               # Helpers
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Test suite
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/                 # API client
│   │   ├── hooks/               # Custom hooks
│   │   ├── contexts/            # Context API
│   │   ├── components/          # React components
│   │   ├── pages/               # Page components
│   │   ├── types/               # TypeScript types
│   │   └── lib/                 # Utilities
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docker/
│   └── docker-compose.yml
├── storage/                     # CAD files & glTF
│   ├── uploads/
│   └── gltf/
└── .env                         # Development config

```

## Database Schema

### Core Entities
- **organizations** - Multi-tenant root
- **plants** - Manufacturing facilities
- **users** - Accounts with RBAC and MFA fields (nullable for Phase 7)
- **projects** - Project containers
- **cad_files** - Files with versioning, encryption refs, data classification

### Articles & Revisions
- **articles** - Product items with type and sourcing
- **article_revisions** - Revision hierarchy (!1, !2, 1, 1.1, etc.)
- **article_documents** - Links revisions to CAD files

### Workflows
- **workflow_templates** - Reusable templates
- **workflow_steps** - Steps with parallel group support
- **workflow_instances** - Running workflows
- **workflow_tasks** - Tasks with escalation tracking

### Other
- **user_workflow_roles** - Multi-role assignment (junction table)
- **audit_logs** - Hash-chained audit trail
- **login_history** - Auth event tracking
- **boms** - Bill of materials
- **bom_items** - BOM items with hierarchy

## Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local backend development)
- Node 20+ (for local frontend development)

### Running with Docker Compose

```bash
cd docker
docker-compose up --build
```

- **Backend**: http://localhost:8000 (API docs at /docs)
- **Frontend**: http://localhost:5173
- **Database**: localhost:5432 (plm/plm)
- **Redis**: localhost:6379

### Local Development (without Docker)

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Development Phases

| Phase | Tasks | Status |
|-------|-------|--------|
| 0 | Project scaffolding | ✅ Complete |
| 1 | Article/revision system | ⏳ Next |
| 2 | CAD viewer & files | ⏳ Next |
| 3 | Workflow engine | ⏳ Next |
| 4 | Dashboard & search | ⏳ Next |
| 5 | BOM system | ⏳ Next |
| 6 | Audit & compliance | ⏳ Next |
| 7 | Security hardening | ⏳ Next |
| 8 | Production deployment | ⏳ Next |

## Next Steps

### Phase 1: Article & Revision System
- [ ] Complete ArticleRevision lifecycle logic
- [ ] Article CRUD endpoints with org-scoping
- [ ] Revision tree API
- [ ] Status transition validation
- [ ] Frontend: ArticleDetail decomposition
- [ ] Frontend: RevisionTree sidebar component

### Migrations & Initialization
- [ ] Run `alembic upgrade head` to create schema
- [ ] Seed default workflow templates
- [ ] Seed test data (org, plant, users)

### Testing
- [ ] Set up pytest fixtures
- [ ] Auth endpoint tests
- [ ] Model validation tests
- [ ] Integration tests

## Key Design Decisions

1. **SQLAlchemy 2.0** with async (asyncpg) for performance
2. **Alembic** migrations from day 1 (not auto-create)
3. **Multi-tenancy** at organization level, always filtered
4. **Hash-chained audit logs** for TISAX compliance
5. **Envelope encryption** for CAD files (Phase 7)
6. **React Query** for state management (not Redux)
7. **TypeScript strict** mode throughout
8. **Sidebar navigation** for 3D viewer space efficiency
9. **Reusable components** (ConfirmModal, DataTable, etc.) to avoid code duplication
10. **API versioning** (/api/v1/) from the start

## Security Notes (TISAX AL3)

**Already in schema (not yet enforced):**
- MFA fields (secret, backup codes)
- Data classification labels
- Encrypted file references
- Audit log hash chaining
- Login history tracking

**To implement in Phase 7-8:**
- TOTP enforcement
- Password policy (14 chars, complexity, rotation)
- Session management (30 min idle, 8 hr absolute)
- Rate limiting
- AES-256-GCM file encryption
- pgcrypto for DB column encryption
- Token blacklist in Redis
- Security headers via Nginx

## Common Commands

### Database
```bash
# Create migration (auto-detect changes)
alembic revision --autogenerate -m "message"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Backend Tests
```bash
cd backend
pytest tests/ -v
pytest tests/test_auth.py::test_login -v
```

### Frontend Dev
```bash
npm run dev      # Start dev server
npm run build    # Production build
npm run lint     # ESLint check
```

## Documentation

- **Architecture**: See `TECHNICAL_PLAN.md` (full 8-phase plan)
- **Models**: SQL schema in `alembic/versions/001_initial_schema.py`
- **API**: Auto-generated at `/docs` (Swagger UI)
- **Components**: Frontend component docs in `frontend/src/components/README.md` (to create)

## Contributing

All changes should:
1. Follow the existing code patterns
2. Include tests
3. Update documentation
4. Pass linting (ESLint for frontend, black/mypy for backend)
5. Maintain TypeScript strict mode
6. Keep database backward-compatible with Alembic migrations

## License

© 2025 GO KTX - Confidential
