# CLAUDE.md — classification-app

## Commands
- Backend: `python backend/run.py` (uvicorn hot-reload on :8001)
- Tests: `pytest backend/tests/ -v` (uses SQLite/StaticPool)
- Tests single: `pytest backend/tests/test_normalize.py -v`
- Frontend: `cd frontend && bun run dev` (Vite on :5173)
- Build FE: `cd frontend && bun run build`
- Typecheck: `cd frontend && bunx tsc --noEmit`
- Lint FE: `cd frontend && bun run lint`

Frontend package manager is **bun**, not npm — use `bun`/`bunx`, not `npm`/`npx`, everywhere (local, CI, Docker). Inside a running container: `docker compose exec frontend bun run <script>` (e.g. `bun run build`, `bunx tsc --noEmit`). `frontend/Dockerfile` (prod) already builds with `oven/bun:1`; `frontend/Dockerfile.dev` still installs with `node:20-slim` + `npm install` — treat that as the one place still owing a bun migration, not a second convention to follow.

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
