from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.auth import CurrentUser, current_user
from app.core.config import settings
from app.core.database import check_db, get_db
from app.core import scheduler
from app.routers import assignments, audit, auth, categories, projects, proyectos, report, resolution, studios
from app.routers.auth import get_me


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_db()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="verbatix — classification API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(proyectos.router)
app.include_router(projects.router)
app.include_router(categories.router)
app.include_router(assignments.router)
app.include_router(studios.router)
app.include_router(resolution.router)
app.include_router(audit.router)
app.include_router(report.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/db")
async def health_db():
    check_db()
    return {"status": "ok"}


@app.get("/me")
def me_alias(user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    return get_me(user=user, db=db)
