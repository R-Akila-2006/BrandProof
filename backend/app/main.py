from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  (registers ORM models with Base)
from app.db import Base, engine
from app.routers import auth, governance, sources, submissions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Demo build: create tables on startup. Replace with Alembic migrations before a pilot.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="BrandProof", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth, sources, submissions, governance):
    app.include_router(r.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
