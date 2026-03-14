"""Google OAuth flow and session helpers."""

import urllib.parse

import httpx
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_signer = URLSafeTimedSerializer(settings.secret_key, salt="session")


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def create_session_token(user_id: int) -> str:
    return _signer.dumps(user_id)


def decode_session_token(token: str) -> int | None:
    try:
        return _signer.loads(token, max_age=60 * 60 * 24 * 30)  # 30 days
    except (BadSignature, SignatureExpired):
        return None


def get_session_user_id(request: Request) -> int | None:
    token = request.cookies.get("session")
    if not token:
        return None
    return decode_session_token(token)


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------


def build_authorization_url() -> str:
    """Return the Google authorization URL to redirect the user to."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_code_for_user_info(code: str) -> dict:
    """Exchange the OAuth code for user info from Google."""
    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        # Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_resp.raise_for_status()
        return userinfo_resp.json()


# ---------------------------------------------------------------------------
# User upsert
# ---------------------------------------------------------------------------


async def get_or_create_user(db: AsyncSession, user_info: dict) -> User:
    """Find existing user by google_id (or email for pre-registered users), or create a new one."""
    google_id = user_info["sub"]
    email = user_info.get("email", "")

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user is None and email:
        # Check for a pre-registered account (admin-added, no google_id yet)
        result = await db.execute(select(User).where(User.email == email, User.google_id.is_(None)))
        user = result.scalar_one_or_none()

    if user is None:
        # First user to join becomes admin
        count_result = await db.execute(select(User))
        is_first = count_result.first() is None

        user = User(
            google_id=google_id,
            email=email,
            name=user_info.get("name", ""),
            avatar_url=user_info.get("picture"),
            is_admin=is_first,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        # Link google_id if this was a pre-registered account, keep name/avatar fresh
        user.google_id = google_id
        user.name = user_info.get("name", user.name)
        user.avatar_url = user_info.get("picture", user.avatar_url)
        await db.commit()

    return user


# ---------------------------------------------------------------------------
# Request dependency
# ---------------------------------------------------------------------------


async def get_current_user(request: Request, db: AsyncSession) -> User | None:
    user_id = get_session_user_id(request)
    if user_id is None:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
