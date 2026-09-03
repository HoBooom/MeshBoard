"""
MeshBoard — FastAPI Application

메인 애플리케이션 인스턴스 및 라우터 등록.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.notices import router as notices_router
from app.api.v1.marketplace import router as marketplace_router
from app.api.v1.agents import router as agents_router
from app.api.v1.citylearn import router as citylearn_router
from app.api.v1.mesh_chesca import router as mesh_chesca_router
from app.api.v1.messages import router as messages_router
from app.api.v1.workspaces import router as workspaces_router
from app.api.v1.trust import router as trust_router
from app.api.v1.operations import router as operations_router
from app.api.v1.sandbox import router as sandbox_router
from app.core.config import settings

app = FastAPI(
    title="MeshBoard API",
    description="AI Agent Mesh Management Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS Middleware ───────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")
app.include_router(notices_router, prefix="/api/v1")
app.include_router(marketplace_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(citylearn_router, prefix="/api/v1")
app.include_router(mesh_chesca_router, prefix="/api/v1")
app.include_router(messages_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(trust_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(sandbox_router, prefix="/api/v1")


# ── Health Check ──────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """서비스 상태 확인."""
    return {
        "status": "healthy",
        "service": "MeshBoard API",
        "version": app.version,
        "environment": settings.ENVIRONMENT,
    }
