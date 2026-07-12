# CLAUDE.md — classification-app

## Commands
- Backend: `python backend/run.py` (uvicorn hot-reload)
- Tests: `pytest backend/tests/ -v`
- Frontend: `npm run dev` (Vite)
- Build frontend: `npm run build`
- Typecheck: `npx tsc --noEmit`
- Lint: `npm run lint`

## Code Style
- Python: snake_case, type hints everywhere, explicit SQL via `text()` in repositories
- TS/React: PascalCase components, camelCase fns, strict types, no `any`
- CSS: Tailwind utility classes + `@layer components` for design system
- No dead code. Remove orphaned files when restructuring.

## Architecture
- `app/core/` — infrastructure (config, db, auth, storage)
- `app/pipeline/` — data processing (normalize, excel, fuzzy, LLM, orchestrator)
- `app/routers/` — API endpoints (auth, projects, studios)
- `app/models.py` — all SQLAlchemy models (single file)
- `app/repositories.py` — data access (explicit SQL queries)

## Auth
- Supabase Auth via JWKS (ES256/RS256)
- Token in localStorage key `verbatix:token`
- User profile in localStorage key `verbatix:user`
- Frontend: `AuthGuard` wrapper + `useVerbatixStore` for auth state
- 401 clears token + redirects to `/login`

## Key Rules
- No new dependencies without checking if existing stack covers it
- Tests use SQLite in-memory (StaticPool) or FakeSession
- Text normalization is in `app/pipeline/normalize.py` — single source of truth
- DB schema truth: `backend/db/migrations/001_schema_v5.sql`
