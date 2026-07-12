# classification-app

Stack:
- Backend: FastAPI + PostgreSQL (Supabase) + SQLAlchemy + Polars + rapidfuzz
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS + Zustand + Framer Motion
- Auth: Supabase Auth (JWT, ES256/RS256)
- LLM: Ollama (local) for verbatim classification

## Directory Structure

```
backend/
├── app/
│   ├── core/              # Infrastructure
│   │   ├── config.py      # Settings (pydantic-settings)
│   │   ├── database.py    # SQLAlchemy engine + session
│   │   ├── auth.py        # JWT verification (Supabase JWKS)
│   │   └── storage.py     # Supabase Storage REST client
│   ├── pipeline/          # Data processing pipeline
│   │   ├── normalize.py   # Text normalization (canonical)
│   │   ├── normalize_polars.py  # Polars normalization pipeline
│   │   ├── excel.py       # Excel parser
│   │   ├── fuzzy/         # Fuzzy matching (rapidfuzz WRatio)
│   │   ├── ollama_client.py # Ollama API client
│   │   ├── classify_llm.py  # LLM classification engine
│   │   └── orchestrator.py  # classify_file_to_csv flow
│   ├── routers/           # API endpoints
│   │   ├── auth.py        # /api/auth (login, signup, me)
│   │   ├── projects.py    # /api/v1/projects
│   │   └── studios.py     # /api/v1 (rounds, studios)
│   ├── models.py          # SQLAlchemy models
│   ├── repositories.py    # Data access layer (explicit SQL)
│   └── main.py            # FastAPI app
├── tests/
│   ├── test_normalize.py
│   ├── test_fuzzy.py
│   ├── test_import_flow.py
│   └── test_classification.py
├── db/migrations/
├── requirements.txt
├── Dockerfile
└── run.py

frontend/
├── src/
│   ├── api/
│   │   ├── client.ts      # API client (includes auth token)
│   │   └── types.ts       # TypeScript interfaces
│   ├── components/
│   │   ├── AuthGuard.tsx          # Protected route wrapper
│   │   ├── SignInPage.tsx         # Login page
│   │   ├── SignUpPage.tsx         # Sign up page
│   │   ├── AppShell.tsx           # Layout + sidebar + user menu
│   │   ├── ProjectDashboard.tsx   # Project grid
│   │   ├── ProjectDetail.tsx      # Project detail view
│   │   ├── CreationWizard.tsx     # Multi-step project creator
│   │   ├── VerbatimsTable.tsx     # Verbatim viewer
│   │   ├── CommandPalette.tsx     # Cmd+K palette
│   │   ├── ToastStack.tsx         # Toast notifications
│   │   ├── Breadcrumb.tsx         # Breadcrumb nav
│   │   └── Loader.tsx             # Loading spinner
│   ├── store/
│   │   └── useVerbatixStore.ts    # Zustand (auth + toasts + nav)
│   ├── hooks/
│   │   └── useKeyboardShortcuts.ts
│   ├── lib/
│   │   ├── cn.ts
│   │   └── sound.ts
│   ├── index.css          # Design system (Verbatix Light)
│   ├── App.tsx            # Auth routes + protected shell
│   └── main.tsx
├── tailwind.config.js     # Custom theme tokens
├── package.json
├── Dockerfile
├── Dockerfile.dev
└── nginx.conf
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/auth/signup | No | Create account (Supabase Auth) |
| POST | /api/auth/login | No | Login, returns JWT |
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

1. User signup/login → Supabase Auth
2. Backend proxies to Supabase Auth REST API
3. Returned JWT stored in localStorage (`verbatix:token`)
4. All API calls include `Authorization: Bearer <token>`
5. Backend validates JWT via Supabase JWKS endpoint
6. 401 response clears token → redirect to /login

## Conventions

- Python: snake_case, type hints, explicit SQL (text()) in repositories
- TypeScript: PascalCase components, camelCase functions, strict types
- CSS: Tailwind utility classes + `@layer components` custom styles
- State: Zustand store for global state
- Token storage: localStorage (keys prefixed `verbatix:`)
