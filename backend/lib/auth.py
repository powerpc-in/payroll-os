"""Authentication primitives: password hashing, JWT session cookies, request context.

Sessions are httpOnly cookies — never tokens in JSON bodies. Every tenant-scoped
request resolves to a Context (user + org_id + role) via the dependencies here.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from lib.db import db
from lib.rbac import has_permission

pwd_context = CryptContext(schemes=["pbkdf2_sha256"])
COOKIE_NAME = "session"
SESSION_TTL_HOURS = 24 * 14


def app_env() -> str:
    return (os.environ.get("APP_ENV") or "development").strip().lower()


def is_production() -> bool:
    return app_env() in ("production", "prod")


DEV_FALLBACK_SECRET = "dev-only-insecure-secret"


def _secret() -> str:
    """Never silently fall back to a dev secret in production.

    In production a missing/short/known-default SESSION_SECRET is a hard failure (checked at
    startup by lib.security.assert_production_config and again here) rather than an
    invisible downgrade to a guessable signing key.
    """
    secret = os.environ.get("SESSION_SECRET")
    if is_production():
        if not secret or secret == DEV_FALLBACK_SECRET or len(secret) < 32:
            raise HTTPException(
                status_code=500,
                detail="Server misconfigured: SESSION_SECRET is missing or insecure. "
                       "Refusing to sign sessions with a development fallback.",
            )
        return secret
    return secret or DEV_FALLBACK_SECRET


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def new_id() -> str:
    return str(uuid.uuid4())


def create_session_token(user_id: str, org_id: str) -> str:
    payload = {
        "sub": user_id,
        "org": org_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def set_session_cookie(response: Response, token: str) -> None:
    # Secure is required in production (HTTPS-only); dev keeps it off for http://localhost.
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_TTL_HOURS * 3600,
        httponly=True, samesite="lax", secure=is_production(), path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


class Context:
    """Resolved request context: the user plus their active tenant membership."""

    def __init__(self, user: dict, org_id: str, role: str):
        self.user = user
        self.org_id = org_id
        self.role = role

    @property
    def user_id(self) -> str:
        return self.user["id"]

    def can(self, perm: str) -> bool:
        return has_permission(self.role, perm)


async def _resolve(token: str) -> Context:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired — sign in again")
    user = await db.users.find_one({"id": payload.get("sub")})
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    org_id = payload.get("org")
    membership = next((m for m in user.get("memberships", []) if m["org_id"] == org_id), None)
    if not membership:
        raise HTTPException(status_code=403, detail="No organisation membership")
    return Context(user=user, org_id=org_id, role=membership["role"])


async def get_ctx(request: Request) -> Context:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    return await _resolve(token)


def require_perm(perm: str):
    async def dep(ctx: Context = Depends(get_ctx)) -> Context:
        if not ctx.can(perm):
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
        return ctx
    return dep


class SessionUser(BaseModel):
    id: str
    name: str
    email: str
