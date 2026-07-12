# CLAUDE.md — classification-app

## Commands
- Backend: `python backend/run.py` (uvicorn hot-reload on :8001)
- Tests: `pytest backend/tests/ -v` (uses SQLite/StaticPool)
- Tests single: `pytest backend/tests/test_normalize.py -v`
- Frontend: `cd frontend && npm run dev` (Vite on :5173)
- Build FE: `cd frontend && npm run build`
- Typecheck: `cd frontend && npx tsc --noEmit`
- Lint FE: `cd frontend && npm run lint`

## Code Style
- Python: snake_case, type hints everywhere, explicit SQL via `text()` in repositories
- TS/React: PascalCase components, camelCase fns, strict types, no `any`
- CSS: Tailwind utility classes + `@layer components` for design system
- No dead code — remove orphaned files when restructuring

## Architecture (backend/app/)
- `core/` — infrastructure (config, db, auth, storage)
- `pipeline/` — data processing (normalize, excel, fuzzy, LLM, orchestrator)
- `routers/` — API endpoints (auth, projects, studios)
- `models.py` — SQLAlchemy models (single file)
- `repositories.py` — data access (explicit SQL)
- `serializers.py` — dead code (stale schema refs)
- `utils/text.py` — dead code (dup of `pipeline/normalize.py`)

## Auth
- Supabase Auth via JWKS (ES256/RS256)
- Token in localStorage key `verbatix:token`
- User profile in localStorage key `verbatix:user`
- Frontend: `AuthGuard` wrapper + `useVerbatixStore` for auth state
- 401 clears token + redirects to `/login`
- Pages: `/login` (SignInPage), `/signup` (SignUpPage)

## Key Rules
- No new dependencies without checking if existing stack covers it
- Tests use SQLite in-memory (StaticPool) or FakeSession — never hit real DB
- Text normalization source of truth: `app/pipeline/normalize.py`
- DB schema source of truth: `backend/db/migrations/001_schema_v5.sql`
