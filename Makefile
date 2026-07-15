.DEFAULT_GOAL := help

# ── Load .env ────────────────────────────────────────────────────────
-include .env
export

# ── APP_ENV: set via cmdline (APP_ENV=prod make up) or defaults to dev
APP_ENV ?= dev

# COMPOSE resolved at runtime
define COMPOSE_CMD
$(if $(filter prod,$(APP_ENV)),\
  docker compose -f docker-compose.yml -f docker-compose.prod.yml,\
  docker compose -f docker-compose.yml -f docker-compose.override.yml)
endef

.PHONY: help build up down ps restart rebuild logs logs-backend logs-frontend \
       shell-backend shell-frontend install run-backend run-frontend test lint \
       typecheck db-reset db-shell clean env

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

env: ## Show current env config
	@echo "APP_ENV=$(APP_ENV)"
	@echo "COMPOSE=$(COMPOSE_CMD)"
	@echo "KLASS_PORT=$(KLASS_PORT)"
	@echo "BACKEND_PORT=$(BACKEND_PORT)"
	@echo "FRONTEND_PORT=$(FRONTEND_PORT)"

# ── Docker ──────────────────────────────────────────────────────────

build: ## Build all containers
	$(COMPOSE_CMD) build

up: ## Start all services (detached)
	$(COMPOSE_CMD) up -d

down: ## Stop all services
	$(COMPOSE_CMD) down

restart: ## Restart all services
	$(COMPOSE_CMD) restart

ps: ## List running containers
	$(COMPOSE_CMD) ps

rebuild: ## Force rebuild and start
	$(COMPOSE_CMD) up -d --build

logs: ## Tail all logs
	$(COMPOSE_CMD) logs -f

logs-backend: ## Tail backend logs
	$(COMPOSE_CMD) logs -f backend

logs-frontend: ## Tail frontend logs
	$(COMPOSE_CMD) logs -f frontend

# ── Shell ───────────────────────────────────────────────────────────

shell-backend: ## Open shell in backend container
	$(COMPOSE_CMD) exec backend bash

shell-frontend: ## Open shell in frontend container
	$(COMPOSE_CMD) exec frontend sh

# ── Local (no Docker) ──────────────────────────────────────────────

install: ## Install backend deps in local venv
	python3 -m venv .venv && \
	.venv/bin/pip install --upgrade pip && \
	.venv/bin/pip install -r backend/requirements.txt

run-backend: ## Run backend locally
	cd backend && uvicorn app.main:app --reload --host $(KLASS_HOST) --port $(KLASS_PORT)

run-frontend: ## Run frontend locally
	cd frontend && bun run dev

# ── Lint / test ─────────────────────────────────────────────────────

test: ## Run backend tests
	cd backend && python3 -m pytest -v

lint: ## Lint backend with ruff
	cd backend && python3 -m ruff check .

typecheck: ## Type-check backend with mypy
	cd backend && python3 -m mypy --ignore-missing-imports app/

# ── Database ────────────────────────────────────────────────────────

db-reset: ## Drop the Postgres volume and re-seed on next startup
	$(COMPOSE_CMD) down -v db
	@echo "DB volume deleted. Run 'make up' to recreate."

db-shell: ## Open a psql shell on the DB
	$(COMPOSE_CMD) exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# ── Cleanup ─────────────────────────────────────────────────────────

clean: ## Remove containers, images, and DB
	$(COMPOSE_CMD) down -v --rmi local
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
