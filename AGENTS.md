# classification-app

**Stack:**
- Backend: FastAPI + PostgreSQL (Supabase) + SQLAlchemy + Polars + rapidfuzz
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS + Zustand + Framer Motion
- Auth: Supabase Auth (JWT, ES256/RS256 via JWKS)
- LLM: Ollama (local) for verbatim classification

## Directory Structure

```
project root/
├── backend/
│   ├── app/
│   │   ├── core/              # Infrastructure
│   │   │   ├── config.py      # Settings (pydantic-settings)
│   │   │   ├── database.py    # SQLAlchemy engine + session
│   │   │   ├── auth.py        # JWT verification (Supabase JWKS)
│   │   │   └── storage.py     # Supabase Storage REST client
│   │   ├── pipeline/          # Data processing pipeline
│   │   │   ├── normalize.py   # Text normalization (canonical)
│   │   │   ├── normalize_polars.py  # Polars normalization pipeline
│   │   │   ├── excel.py       # Excel parser
│   │   │   ├── fuzzy/         # Fuzzy matching (rapidfuzz WRatio)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── models.py
│   │   │   │   ├── matcher.py
│   │   │   │   └── service.py
│   │   │   ├── ollama_client.py # Ollama API client
│   │   │   ├── classify_llm.py  # LLM classification engine
│   │   │   └── orchestrator.py  # classify_file_to_csv flow
│   │   ├── routers/           # API endpoints
│   │   │   ├── auth.py        # /api/auth (signup, login, me)
│   │   │   ├── projects.py    # /api/v1/projects
│   │   │   └── studios.py     # /api/v1 (rounds, studios)
│   │   ├── models.py          # SQLAlchemy models (single file)
│   │   ├── repositories.py    # Data access layer (explicit SQL)
│   │   ├── main.py            # FastAPI app
│   │   ├── serializers.py     # ⚠️ Dead code (stale refs to old schema)
│   │   └── utils/text.py      # ⚠️ Dead code (dup of pipeline/normalize.py)
│   ├── tests/
│   │   ├── test_normalize.py
│   │   ├── test_fuzzy.py
│   │   ├── test_import_flow.py
│   │   └── test_classification.py
│   ├── db/migrations/
│   │   └── 001_schema_v5.sql
│   ├── scripts/
│   │   └── classify_file.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── run.py
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts      # API client (injects Bearer token)
│   │   │   └── types.ts       # TypeScript interfaces
│   │   ├── components/
│   │   │   ├── AuthGuard.tsx          # Protected route wrapper
│   │   │   ├── SignInPage.tsx         # Login page
│   │   │   ├── SignUpPage.tsx         # Sign up page
│   │   │   ├── AppShell.tsx           # Layout + sidebar + user menu
│   │   │   ├── ProjectDashboard.tsx   # Project grid
│   │   │   ├── ProjectDetail.tsx      # Project detail view
│   │   │   ├── CreationWizard.tsx     # Multi-step project creator
│   │   │   ├── VerbatimsTable.tsx     # Verbatim viewer
│   │   │   ├── CommandPalette.tsx     # Cmd+K palette
│   │   │   ├── ToastStack.tsx         # Toast notifications
│   │   │   ├── Breadcrumb.tsx         # Breadcrumb nav
│   │   │   └── Loader.tsx             # Loading spinner
│   │   ├── store/
│   │   │   └── useVerbatixStore.ts    # Zustand (auth + toasts + nav)
│   │   ├── hooks/
│   │   │   └── useKeyboardShortcuts.ts
│   │   ├── lib/
│   │   │   ├── cn.ts
│   │   │   └── sound.ts
│   │   ├── index.css          # Design system (Verbatix Light)
│   │   ├── App.tsx            # Auth routes + protected shell
│   │   └── main.tsx
│   ├── tailwind.config.js     # Custom theme tokens
│   ├── package.json
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   └── nginx.conf
│
├── data/                     # Sample data + uploads
│   ├── sample*.xlsx
│   ├── catalog.sqlite
│   └── uploads/
├── db/                       # Docker volume mount (Postgres data)
├── docker-compose*.yml       # Dev / prod / override
├── .env                      # Environment variables
├── Makefile
└── AGENTS.md / CLAUDE.md     # Agent instructions
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/auth/signup | No | Create account (Supabase Auth) |
| POST | /api/auth/login | No | Login, returns JWT + user |
| GET | /api/auth/me | Yes | Get/sync user profile |
| POST | /api/v1/projects | Yes | Create project |
| GET | /api/v1/projects | Yes | List projects |
| POST | /api/v1/projects/{id}/rounds | Yes | Create round |
| POST | /api/v1/rounds/{id}/studios | Yes | Create studio with codebook |
| GET | /api/v1/studios/{id} | Yes | Get studio with counters |
| GET | /api/v1/studios/{id}/mention-groups | Yes | List mention groups |
| GET | /api/v1/studios/{id}/verbatims | Yes | List verbatims (paginated) |
| GET | /health | No | Health check |
| GET | /health/db | No | Database health check |

## Auth Flow

1. User signup/login → backend proxies to Supabase Auth REST
2. JWT stored in localStorage (`verbatix:token`)
3. All API calls include `Authorization: Bearer <token>`
4. Backend validates JWT via Supabase JWKS endpoint (ES256/RS256)
5. 401 response clears token → redirect to `/login`

## Conventions

- Python: snake_case, type hints, explicit SQL with `text()` in repositories
- TypeScript: PascalCase components, camelCase functions, strict types, no `any`
- CSS: Tailwind utility classes + `@layer components` design system
- State: Zustand store for global state
- Frontend package manager is **bun**, not npm/npx — `bun install`, `bun run <script>`, `bunx <tool>`. Applies everywhere, including inside Docker containers (`docker compose exec frontend bun run dev`). `frontend/Dockerfile` (prod) already builds on `oven/bun:1`; `frontend/Dockerfile.dev` (the dev/hot-reload container) still uses `node:20-slim` + `npm install` and needs migrating to match — don't copy its `npm` usage into new instructions.

## Activated Tools

### graphify
- Knowledge graph at `graphify-out/` with god nodes, community structure, and cross-file relationships.
- For codebase questions, run `graphify query "<question>"` when `graphify-out/graph.json` exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts.
- Read `graphify-out/GRAPH_REPORT.md` for architecture overview.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

### engram
- Persistent memory across sessions — saves decisions, bugs, conventions, discoveries.
- Core tools: `mem_save`, `mem_search`, `mem_context`, `mem_session_summary`, `mem_get_observation`, `mem_save_prompt`, `mem_current_project`.
- Proactive save rule: call `mem_save` immediately after ANY decision, bug fix, discovery, or convention.
- Conflict resolution: check `judgment_required` in `mem_save` responses and resolve via `mem_judge`.

### headroom
- Context optimization layer — compresses large tool outputs, saves tokens.
- Proxy: `headroom proxy` (port 8787). Route Claude through it: `ANTHROPIC_BASE_URL=http://127.0.0.1:8787 claude`.
- MCP tools: `headroom_retrieve`, `headroom_compress`, `headroom_stats`.

## Dead Code (Don't Touch — Needs Cleanup)

- `backend/app/serializers.py` — stale, references old schema
- `backend/app/utils/text.py` — duplicate of `pipeline/normalize.py`
