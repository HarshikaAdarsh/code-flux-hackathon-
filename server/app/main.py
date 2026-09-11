"""AI Smart Study Companion — FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.routers import (
    assessments,
    auth,
    health,
    pomodoro,
    reports,
    subjects,
    teach,
    topics,
    voice,
)
from app.services import storage

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.uploads_dir()
    storage.audio_dir()
    logger.info("%s starting (env=%s)", settings.app_name, settings.environment)
    if not settings.gemini_api_key and not settings.groq_api_key:
        logger.warning(
            "No LLM API key configured — AI features will return degraded "
            "responses. Set GEMINI_API_KEY and/or GROQ_API_KEY in server/.env"
        )
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Backend for the AI-Based Smart Study Companion: syllabus "
        "containerisation, topic-scoped teaching, adaptive assessment, "
        "multilingual voice and focus tracking."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end. Please try again."},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(subjects.router)
app.include_router(topics.router)
app.include_router(teach.router)
app.include_router(assessments.router)
app.include_router(reports.router)
app.include_router(voice.router)
app.include_router(pomodoro.router)

# uploaded syllabi and generated audio
app.mount(
    "/files/uploads", StaticFiles(directory=storage.uploads_dir()), name="uploads"
)
app.mount("/files/audio", StaticFiles(directory=storage.audio_dir()), name="audio")


@app.get("/", tags=["health"])
async def root():
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health/full",
    }
