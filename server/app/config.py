"""Application settings, loaded from environment / .env."""

from functools import lru_cache
from typing import Annotated, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# NoDecode stops pydantic-settings from JSON-parsing these before our
# validator runs, so plain comma-separated values work in .env.
CsvList = Annotated[List[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_name: str = "AI Smart Study Companion API"
    environment: str = "development"
    debug: bool = True

    # --- Database ---
    database_url: str = (
        "postgresql+asyncpg://study:study@localhost:5433/study_companion"
    )

    # --- Auth ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    google_client_id: str = ""

    # --- CORS ---
    cors_origins: CsvList = ["http://localhost:5173", "http://localhost:3000"]

    # --- LLM providers (see PRD 10.1) ---
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # NOTE: the PRD named gemini-2.5-flash(-lite), llama-3.3-70b-versatile and
    # text-embedding-004. All three have since been retired for new accounts
    # (verified against both live APIs). These are the current equivalents.
    gemini_chat_model: str = "gemini-3.5-flash-lite"  # high-volume tutor turns
    gemini_json_model: str = "gemini-3.5-flash"  # structured output
    gemini_embed_model: str = "gemini-embedding-001"
    groq_fallback_model: str = "openai/gpt-oss-120b"
    groq_stt_model: str = "whisper-large-v3-turbo"
    # TTS fallback when the (unofficial) edge-tts endpoint is unavailable
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_tts_voice: str = "Kore"

    llm_timeout_seconds: float = 45.0

    # --- Free-tier throttling (PRD 11: user-facing vs background lanes) ---
    llm_interactive_rpm: int = 12
    llm_background_rpm: int = 4
    # Verification runs in its own lane so audits can never starve a live
    # tutor turn. Batching keeps the request count low (roughly one per four
    # sentences), so this can be generous without threatening the daily quota.
    llm_verify_rpm: int = 60

    # --- Accuracy verification / hallucination guardrails ---
    verification_enabled: bool = True
    # Content at or above this score is approved; below it is rewritten
    # (live chat) or regenerated (critical tasks).
    verification_threshold: int = 80
    # Total generation attempts for critical tasks: the original plus one
    # critique-guided retry. Never unbounded — free tiers are finite.
    verification_max_attempts: int = 2
    # Audit live tutor sentences before they reach text-to-speech.
    verify_live_chat: bool = True
    # Sentences shorter than this carry no checkable claim; skipping them
    # keeps quota for the statements that matter.
    verification_min_chars: int = 25
    # Empty falls back to the fast chat model (flash-lite).
    verifier_model: str = ""

    # --- Syllabus parsing ---
    max_topics_per_subject: int = 50  # PRD open question 5
    max_upload_mb: int = 15
    upload_dir: str = "storage/uploads"
    audio_dir: str = "storage/audio"

    # --- Assessment engine (PRD 7.3) ---
    assessment_default_length: int = 10
    level_up_streak: int = 2
    level_down_streak: int = 2
    mastery_decay_per_day: float = 1.5  # points/day, PRD open question 2

    # --- Code sandbox (PRD 7.4) ---
    sandbox_enabled: bool = True
    sandbox_image: str = "python:3.12-slim"
    # If Docker is unavailable, fall back to a restricted local subprocess.
    # Safe enough for a single-user demo; keep False for any shared deployment.
    sandbox_allow_local_fallback: bool = True
    # Wall-clock limit for the student's code, enforced inside the sandbox.
    sandbox_timeout_seconds: int = 8
    # Extra head-room for container startup, which can take several seconds
    # on Docker Desktop and must not count against the student's budget.
    sandbox_startup_allowance_seconds: int = 25
    sandbox_memory_mb: int = 256
    sandbox_cpus: str = "0.5"

    # --- Voice ---
    supported_languages: CsvList = ["en", "hi"]  # PRD open question 1

    @field_validator("cors_origins", "supported_languages", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
