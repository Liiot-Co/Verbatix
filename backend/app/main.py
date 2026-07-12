from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import SessionLocal, init_db
from app.routers import files, projects, rounds, studies
from app.seed import seed_demo_project


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_demo_project(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Verbatix — API de codificación de verbatims",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(projects.router)
app.include_router(studies.router)
app.include_router(rounds.router)
app.include_router(files.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"error": detail}
    else:
        body = {"error": {"code": "ERROR", "message": str(detail), "details": {}}}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/health")
async def health():
    return {"status": "ok"}
