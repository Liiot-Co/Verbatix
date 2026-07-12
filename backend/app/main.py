from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import CurrentUser, current_user
from app.config import settings
from app.database import check_db, get_db
from app.routers import auth, classify, projects, studios
from app.routers.auth import get_me


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_db()
    yield


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
app.include_router(projects.router)
app.include_router(studios.router)
app.include_router(classify.router)


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
