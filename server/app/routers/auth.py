"""Authentication — email/password + Google OAuth (PRD 7.7)."""

import logging

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas import (
    GoogleLoginRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
    UserUpdate,
)
from app.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id), {"email": user.email}),
        user=UserOut.model_validate(user),
    )


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(payload: SignupRequest, db: DbSession):
    email = payload.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    language = payload.preferred_language
    if language not in settings.supported_languages:
        language = "en"

    user = User(
        email=email,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        preferred_language=language,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession):
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    return _token_response(user)


@router.post("/google", response_model=TokenResponse)
async def google_login(payload: GoogleLoginRequest, db: DbSession):
    """Verify a Google ID token from the client and issue our own JWT."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                GOOGLE_TOKENINFO, params={"id_token": payload.id_token}
            )
            resp.raise_for_status()
            info = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Google token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Google token") from exc

    if settings.google_client_id and info.get("aud") != settings.google_client_id:
        raise HTTPException(status_code=401, detail="Google token audience mismatch")
    if info.get("email_verified") not in ("true", True):
        raise HTTPException(status_code=401, detail="Google email is not verified")

    email = (info.get("email") or "").lower()
    sub = info.get("sub")
    if not email or not sub:
        raise HTTPException(status_code=401, detail="Google token is missing claims")

    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            name=info.get("name") or email.split("@")[0],
            google_sub=sub,
        )
        db.add(user)
        await db.flush()
    elif not user.google_sub:
        user.google_sub = sub

    await db.refresh(user)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession):
    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.preferred_language is not None:
        if payload.preferred_language not in settings.supported_languages:
            raise HTTPException(
                status_code=400,
                detail=f"Supported languages: {settings.supported_languages}",
            )
        user.preferred_language = payload.preferred_language
    if payload.pomodoro_minutes is not None:
        user.pomodoro_minutes = payload.pomodoro_minutes
    await db.flush()
    await db.refresh(user)
    return user
