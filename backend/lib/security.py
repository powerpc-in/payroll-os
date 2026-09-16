"""Deployment-safety guards: explicit, fail-safe production configuration.

Development stays frictionless (tokens in responses, permissive CORS, dev signing key), but
those conveniences are gated on APP_ENV. In production the app refuses to start rather than
run with a guessable session secret, a wildcard CORS origin alongside credentials, or a
password-reset endpoint that hands back usable tokens.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from lib.auth import DEV_FALLBACK_SECRET, app_env, is_production
from lib.db import db

logger = logging.getLogger(__name__)

# Brute-force throttling (in-DB so it survives reloads and works across workers).
MAX_FAILED_LOGINS = 8
LOCKOUT_MINUTES = 15
FAILED_WINDOW_MINUTES = 15


class InsecureConfiguration(RuntimeError):
    pass


def config_report() -> dict:
    secret = os.environ.get("SESSION_SECRET")
    origins = [o.strip() for o in (os.environ.get("CORS_ORIGINS") or "").split(",") if o.strip()]
    return {
        "app_env": app_env(),
        "production": is_production(),
        "session_secret_present": bool(secret),
        "session_secret_is_dev_default": secret == DEV_FALLBACK_SECRET,
        "session_secret_length_ok": bool(secret and len(secret) >= 32),
        "cors_origins": origins or ["*"],
        "cors_wildcard": (not origins) or "*" in origins,
        "cookie_secure": is_production(),
        "reset_tokens_returned_in_response": not is_production(),
    }


def assert_production_config() -> None:
    """Called at startup. Raises in production when a required secret is missing/insecure."""
    report = config_report()
    if not report["production"]:
        logger.warning(
            "APP_ENV=%s — development conveniences are ACTIVE (dev session secret allowed, "
            "password-reset tokens returned in API responses, permissive CORS, non-Secure "
            "cookie). Set APP_ENV=production with a strong SESSION_SECRET and explicit "
            "CORS_ORIGINS before any real deployment.", report["app_env"],
        )
        return
    problems: list[str] = []
    if not report["session_secret_present"]:
        problems.append("SESSION_SECRET is not set")
    elif report["session_secret_is_dev_default"]:
        problems.append("SESSION_SECRET is still the development default")
    elif not report["session_secret_length_ok"]:
        problems.append("SESSION_SECRET must be at least 32 characters")
    if report["cors_wildcard"]:
        problems.append("CORS_ORIGINS must list explicit origins in production "
                        "(a wildcard cannot be combined with credentialed requests)")
    if problems:
        raise InsecureConfiguration(
            "Refusing to start in production with an insecure configuration: "
            + "; ".join(problems))
    logger.info("Production security configuration validated.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def check_login_allowed(email: str) -> None:
    """Raises 429 when an account has too many recent failures (brute-force throttle)."""
    from fastapi import HTTPException

    doc = await db.login_attempts.find_one({"email": email})
    if not doc:
        return
    locked_until = doc.get("locked_until")
    if locked_until and locked_until.replace(tzinfo=timezone.utc) > _now():
        wait = int((locked_until.replace(tzinfo=timezone.utc) - _now()).total_seconds() // 60) + 1
        raise HTTPException(status_code=429,
                            detail=f"Too many failed sign-in attempts. Try again in {wait} minute(s).")


async def record_login_failure(email: str) -> None:
    doc = await db.login_attempts.find_one({"email": email})
    window_start = _now() - timedelta(minutes=FAILED_WINDOW_MINUTES)
    count = 1
    if doc and doc.get("last_failure_at") and doc["last_failure_at"].replace(tzinfo=timezone.utc) > window_start:
        count = int(doc.get("count", 0)) + 1
    updates: dict = {"email": email, "count": count, "last_failure_at": _now()}
    if count >= MAX_FAILED_LOGINS:
        updates["locked_until"] = _now() + timedelta(minutes=LOCKOUT_MINUTES)
        updates["count"] = 0
        logger.warning("Account %s temporarily locked after repeated failed sign-ins", email)
    await db.login_attempts.update_one({"email": email}, {"$set": updates}, upsert=True)


async def clear_login_failures(email: str) -> None:
    await db.login_attempts.delete_one({"email": email})


def is_production_reset_policy() -> bool:
    """True when password-reset tokens must NOT be returned in API responses."""
    return is_production()
