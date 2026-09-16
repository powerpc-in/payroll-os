"""Authentication: signup, login, logout, session introspection, password reset."""

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from lib.auth import (Context, clear_session_cookie, create_session_token, get_ctx,
                      hash_password, new_id, set_session_cookie, verify_password)
from lib.security import (check_login_allowed, clear_login_failures, is_production_reset_policy,
                          record_login_failure)
from lib.db import db
from lib.events import emit
from lib.rbac import permissions_for_role

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class SignupIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    org_name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


async def session_payload(ctx: Context) -> dict:
    org = await db.organisations.find_one({"id": ctx.org_id}) or {}
    return {
        "user": {"id": ctx.user_id, "name": ctx.user["name"], "email": ctx.user["email"]},
        "org": {
            "id": org.get("id"), "name": org.get("name", ""),
            "jurisdiction": org.get("jurisdiction", "IN"),
            "onboarded": org.get("onboarded", False),
            "accept_unverified_statutory_values": (org.get("payroll_settings") or {}).get(
                "accept_unverified_statutory_values", False),
        },
        "role": ctx.role,
        "permissions": permissions_for_role(ctx.role),
        "employee_id": ctx.user.get("employee_id"),
    }


@router.post("/signup")
async def signup(input: SignupIn, response: Response):
    email = input.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    org_id = new_id()
    org = {
        "id": org_id, "name": input.org_name, "jurisdiction": "IN", "currency": "INR",
        "address": "", "city": "", "state": "", "onboarded": False,
        "payroll_settings": {"pay_frequency": "monthly", "pay_day": "last-day",
                             "accept_unverified_statutory_values": False},
        "created_at": now(),
    }
    user = {
        "id": new_id(), "name": input.name, "email": email,
        "password_hash": hash_password(input.password),
        "memberships": [{"org_id": org_id, "role": "COMPANY_ADMIN"}],
        "employee_id": None, "is_super_admin": False, "mfa_enabled": False,
        "created_at": now(),
    }
    await db.organisations.insert_one(org)
    await db.users.insert_one(user)
    token = create_session_token(user["id"], org_id)
    set_session_cookie(response, token)
    ctx = Context(user=user, org_id=org_id, role="COMPANY_ADMIN")
    await emit(org_id, "organisation.created", actor=user, entity="organisation", entity_id=org_id,
               summary=f"Organisation '{input.org_name}' created")
    return await session_payload(ctx)


@router.post("/login")
async def login(input: LoginIn, response: Response):
    email = input.email.lower()
    await check_login_allowed(email)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(input.password, user.get("password_hash", "")):
        # Generic message: never reveal whether the account exists.
        await record_login_failure(email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    memberships = user.get("memberships", [])
    if not memberships:
        raise HTTPException(status_code=403, detail="No organisation membership")
    await clear_login_failures(email)
    org_id = memberships[0]["org_id"]
    set_session_cookie(response, create_session_token(user["id"], org_id))
    return await session_payload(Context(user=user, org_id=org_id, role=memberships[0]["role"]))


@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(ctx: Context = Depends(get_ctx)):
    return await session_payload(ctx)


@router.post("/password-reset/request")
async def password_reset_request(input: ResetRequestIn):
    user = await db.users.find_one({"email": input.email.lower()})
    if not user:
        # Do not leak whether the account exists
        return {"ok": True, "reset_token": None}
    token = os.urandom(24).hex()
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"reset_token": hash_password(token),
                 "reset_token_expires": now() + timedelta(hours=1)},
    })
    if is_production_reset_policy():
        # Production: the token is never returned over the API. It must be delivered out of
        # band (email provider not configured in this MVP), so the flow stops here.
        return {
            "ok": True, "reset_token": None,
            "note": "If the account exists, a reset link will be sent. No email provider is "
                    "configured in this build, so an administrator must reset the password.",
        }
    return {
        "ok": True, "reset_token": token,
        "note": "DEVELOPMENT ONLY — the token is returned here for testing. With "
                "APP_ENV=production it is never included in the response.",
    }


@router.post("/password-reset/confirm")
async def password_reset_confirm(input: ResetConfirmIn):
    # Tokens are stored hashed, so candidates are matched by verifying the hash.
    candidates = await db.users.find({"reset_token": {"$ne": None},
                                      "reset_token_expires": {"$gte": now()}}).to_list(200)
    user = next((u for u in candidates if verify_password(input.token, u.get("reset_token") or "")), None)
    if not user:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"password_hash": hash_password(input.new_password)},
        "$unset": {"reset_token": "", "reset_token_expires": ""},
    })
    await clear_login_failures(user["email"])
    return {"ok": True}
