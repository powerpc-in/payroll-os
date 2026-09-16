"""In-app notifications."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lib.auth import Context, get_ctx
from lib.db import db

router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])


@router.get("")
async def my_notifications(ctx: Context = Depends(get_ctx)):
    docs = await db.notifications.find({"org_id": ctx.org_id, "user_id": ctx.user_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(100)
    unread = await db.notifications.count_documents(
        {"org_id": ctx.org_id, "user_id": ctx.user_id, "read": False})
    return {"items": docs, "unread": unread}


class ReadIn(BaseModel):
    all: bool = False


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, ctx: Context = Depends(get_ctx)):
    await db.notifications.update_one(
        {"id": notification_id, "org_id": ctx.org_id, "user_id": ctx.user_id},
        {"$set": {"read": True}})
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(ctx: Context = Depends(get_ctx)):
    await db.notifications.update_many(
        {"org_id": ctx.org_id, "user_id": ctx.user_id, "read": False},
        {"$set": {"read": True}})
    return {"ok": True}
