param(
  [Parameter(Position=0)]$Command,
  [string]$AppEnv = "dev"
)
$env:APP_ENV = $AppEnv

<#
.DESCRIPTION
  Docker Compose helper — drop-in for Makefile on Windows.
  Usage: .\docker.ps1 `<command> [-AppEnv dev|prod]
  Commands: help, env, build, up, down, restart, rebuild, logs,
            logs-backend, logs-frontend,
            shell-backend, shell-frontend,
            install, run-backend, run-frontend,
            test, lint, typecheck,
            db-reset, db-shell, clean
#>

$ErrorActionPreference = "Stop"

function ComposeCmd {
  if ($AppEnv -eq "prod") {
    "docker compose -f docker-compose.yml -f docker-compose.prod.yml"
  } else {
    "docker compose -f docker-compose.yml -f docker-compose.override.yml"
  }
}

function Invoke-Compose {
  param([string]$ComposeArgs)
  $cmd = "$(ComposeCmd) $ComposeArgs"
  Write-Host "> $cmd" -ForegroundColor Cyan
  Invoke-Expression $cmd
  if ($LASTEXITCODE -ne 0) { throw "Command failed" }
}

function ShowHelp {
  Write-Host @"

Usage: .\docker.ps1 `<command> [-AppEnv dev|prod]

Commands:
  help              Show this help
  env               Show current env config
  build             Build all containers
  up                Start all services (detached)
  down              Stop all services
  restart           Restart all services
  rebuild           Force rebuild and start
  logs              Tail all logs
  logs-backend      Tail backend logs
  logs-frontend     Tail frontend logs
  shell-backend     Open shell in backend container
  shell-frontend    Open shell in frontend container
  install           Install backend deps in local venv
  run-backend       Run backend locally
  run-frontend      Run frontend locally
  test              Run backend tests
  lint              Lint backend with ruff
  typecheck         Type-check backend with mypy
  db-reset          Drop the Postgres volume
  db-shell          Open a psql shell on the DB
  clean             Remove containers, images, and DB

"@ -ForegroundColor Green
}

function ShowEnv {
  $compose = ComposeCmd
  Write-Host "APP_ENV=$AppEnv"
  Write-Host "COMPOSE=$compose"
}

function Build { Invoke-Compose "build" }
function Up { Invoke-Compose "up -d" }
function Down { Invoke-Compose "down" }
function Restart { Invoke-Compose "restart" }
function Rebuild { Invoke-Compose "up -d --build" }
function Logs { Invoke-Compose "logs -f" }
function LogsBackend { Invoke-Compose "logs -f backend" }
function LogsFrontend { Invoke-Compose "logs -f frontend" }
function ShellBackend { Invoke-Compose "exec backend bash" }
function ShellFrontend { Invoke-Compose "exec frontend sh" }

function Install {
  Write-Host "> python -m venv .venv" -ForegroundColor Cyan
  python -m venv .venv
  Write-Host "> .venv\Scripts\pip install --upgrade pip" -ForegroundColor Cyan
  & ".venv\Scripts\pip" install --upgrade pip
  Write-Host "> .venv\Scripts\pip install -r backend\requirements.txt" -ForegroundColor Cyan
  & ".venv\Scripts\pip" install -r backend\requirements.txt
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

function RunBackend {
  $host = if ($env:KLASS_HOST) { $env:KLASS_HOST } else { "127.0.0.1" }
  $port = if ($env:KLASS_PORT) { $env:KLASS_PORT } else { "8001" }
  $cmd = "uvicorn app.main:app --reload --host $host --port $port"
  Write-Host "> cd backend && $cmd" -ForegroundColor Cyan
  Push-Location backend
  try { Invoke-Expression $cmd } finally { Pop-Location }
}

function RunFrontend {
  Write-Host "> cd frontend && bun run dev" -ForegroundColor Cyan
  Push-Location frontend
  try { bun run dev } finally { Pop-Location }
}

function Test {
  Write-Host "> cd backend && python -m pytest -v" -ForegroundColor Cyan
  Push-Location backend
  try { python -m pytest -v } finally { Pop-Location }
}

function Lint {
  Write-Host "> cd backend && python -m ruff check ." -ForegroundColor Cyan
  Push-Location backend
  try { python -m ruff check . } finally { Pop-Location }
}

function Typecheck {
  Write-Host "> cd backend && python -m mypy --ignore-missing-imports app/" -ForegroundColor Cyan
  Push-Location backend
  try { python -m mypy --ignore-missing-imports app/ } finally { Pop-Location }
}

function DbReset {
  Invoke-Compose "down -v db"
  Write-Host "DB volume deleted. Run '.\docker.ps1 up' to recreate." -ForegroundColor Yellow
}

function DbShell {
  $user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "verbatix" }
  $db = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "verbatix" }
  Invoke-Compose "exec db psql -U $user -d $db"
}

function Clean {
  Invoke-Compose "down -v --rmi local"
  if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
  Get-ChildItem -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
}

# ── Dispatch ───────────────────────────────────────────────────────────
$cmd = $Command
if (-not $cmd) { $cmd = "help" }

switch -Wildcard ($cmd) {
  "help"            { ShowHelp }
  "env"             { ShowEnv }
  "build"           { Build }
  "up"              { Up }
  "down"            { Down }
  "restart"         { Restart }
  "rebuild"         { Rebuild }
  "logs"            { Logs }
  "logs-backend"    { LogsBackend }
  "logs-frontend"   { LogsFrontend }
  "shell-backend"   { ShellBackend }
  "shell-frontend"  { ShellFrontend }
  "install"         { Install }
  "run-backend"     { RunBackend }
  "run-frontend"    { RunFrontend }
  "test"            { Test }
  "lint"            { Lint }
  "typecheck"       { Typecheck }
  "db-reset"        { DbReset }
  "db-shell"        { DbShell }
  "clean"           { Clean }
  default           { Write-Host "Unknown command: $cmd" -ForegroundColor Red; ShowHelp }
}
