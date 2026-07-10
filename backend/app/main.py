from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import OfficialBrand, MarketStudy
from app.routers import upload, classify, metrics, rounds, resolve, export, codes
from app.seed import seed_brands, seed_demo_study


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        if db.query(OfficialBrand).count() == 0:
            seed_brands(db)
        if db.query(MarketStudy).count() == 0:
            seed_demo_study(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="klass — classification API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(classify.router)
app.include_router(metrics.router)
app.include_router(rounds.router)
app.include_router(resolve.router)
app.include_router(export.router)
app.include_router(codes.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
