"""Health and readiness — the pre-demo check from PRD 10.1, as an endpoint."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.services import llm, sandbox, voice

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}


@router.get("/health/full")
async def full_health():
    """Checks the database, both LLM providers, the sandbox and voice.

    Run this ~60 seconds before a demo.
    """

    async def db_check():
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                has_vector = await conn.scalar(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
            return {"ok": True, "pgvector": bool(has_vector)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)[:200]}

    database, providers, sandbox_status, voice_status = await asyncio.gather(
        db_check(), llm.health_check(), sandbox.status(), voice.status()
    )

    ready = database["ok"] and not providers["degraded"]
    return {
        "status": "ok" if ready else "degraded",
        "database": database,
        "llm": providers,
        "sandbox": sandbox_status,
        "voice": voice_status,
    }
