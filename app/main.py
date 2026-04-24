"""Entrypoint FastAPI — bi_conta_azul MVP multi-tenant."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import close_pool, get_pool
from .routers import auth, bi, clientes, sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="bi_conta_azul - PED Intelligence",
    description="ETL multi-tenant ContaAzul -> Postgres -> BI",
    version="0.3.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(clientes.router)
app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(bi.router)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def _startup():
    get_pool()


@app.on_event("shutdown")
def _shutdown():
    close_pool()


@app.get("/", tags=["meta"])
def root():
    dashboard = STATIC_DIR / "dashboard.html"
    if dashboard.exists():
        return FileResponse(str(dashboard))
    return {"app": "bi_conta_azul", "docs": "/docs", "dashboard": "static/dashboard.html nao encontrado"}


@app.get("/health", tags=["meta"])
def health():
    try:
        pool = get_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": f"erro: {e}"}
