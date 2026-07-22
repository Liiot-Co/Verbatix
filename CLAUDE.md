# CLAUDE.md — classification-app

## Commands

**Run everything through the running Docker containers — the host machine has neither `bun` nor a `pytest`-equipped Python on PATH.** `docker compose up -d` starts `verbatix-backend-1`/`verbatix-frontend-1`/`verbatix-db-1`; then:
- Backend tests: `docker compose exec -T backend python -m pytest tests/ -v` (single file: `... tests/test_normalize.py -v`)
- Backend shell/scripts: `docker compose exec -T backend python -c "..."`
- Frontend typecheck: `docker compose exec -T frontend bunx tsc --noEmit`
- Frontend build/lint: `docker compose exec -T frontend bun run build` / `bun run lint`
- Rebuild after a dependency change (e.g. `requirements.txt`): `docker compose build backend` (or `frontend`), then `docker compose up -d <service>`
- `-T` disables the pseudo-TTY — needed for non-interactive/agent use; drop it for an interactive shell.

Frontend package manager is **bun**, not npm — use `bun`/`bunx`, not `npm`/`npx`, everywhere (local, CI, Docker). `frontend/Dockerfile` (prod) already builds with `oven/bun:1`; `frontend/Dockerfile.dev` still installs with `node:20-slim` + `npm install` — treat that as the one place still owing a bun migration, not a second convention to follow.

Outside Docker (rare — e.g. a fresh host setup): `python backend/run.py` (uvicorn hot-reload on :8001), `cd frontend && bun run dev` (Vite on :5173).

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

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## engram

Persistent memory across sessions. Use MCP tools via `mcp__engram__mem_*`.
- Core: `mem_save`, `mem_search`, `mem_context`, `mem_session_summary`, `mem_get_observation`, `mem_save_prompt`, `mem_current_project`
- Save after every decision, bug fix, discovery, or convention
- Resolve conflicts via `mem_judge` when `judgment_required` is true

## headroom

Context optimization — compresses large tool outputs (port 8787).
- Proxy: `headroom proxy` then route via `ANTHROPIC_BASE_URL=http://127.0.0.1:8787 claude`
- MCP tools: `mcp__headroom__headroom_retrieve`, `mcp__headroom__headroom_compress`, `mcp__headroom__headroom_stats`
