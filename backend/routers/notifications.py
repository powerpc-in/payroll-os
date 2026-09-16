"""Notifications — in-app delivery plus the channel architecture that email, PWA web
push and Android/iOS push will plug into.

Every notification is produced by `lib.events.emit`, so one event feeds the audit trail,
the in-app inbox and outbound webhooks. Channels other than in-app are *registered*, not
faked: their per-notification state stays `queued` until a provider is configured.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lib.auth import Context, get_ctx, require_perm
from lib.db import db
from lib.events import EVENT_CATALOG, NOTIFICATION_CHANNELS

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


@router.get("/channels")
async def channels(ctx: Context = Depends(get_ctx)):
    """Registered delivery channels and which platform events can notify."""
    prefs = await db.notification_preferences.find_one({"org_id": ctx.org_id}, {"_id": 0}) or {}
    enabled = prefs.get("channels", {})
    return {
        "channels": [{**c, "enabled": enabled.get(c["key"], c["configured"])}
                     for c in NOTIFICATION_CHANNELS],
        "events": [e for e in EVENT_CATALOG if e["notify"]],
    }


class ChannelPrefsIn(BaseModel):
    channels: dict[str, bool]


@router.put("/channels")
async def update_channels(input: ChannelPrefsIn,
                          ctx: Context = Depends(require_perm("settings.manage"))):
    """Enabling an unconfigured channel only queues notifications for it — no provider
    call happens until credentials exist, and nothing is reported as sent."""
    known = {c["key"] for c in NOTIFICATION_CHANNELS}
    channels = {k: bool(v) for k, v in input.channels.items() if k in known}
    await db.notification_preferences.update_one(
        {"org_id": ctx.org_id},
        {"$set": {"org_id": ctx.org_id, "channels": channels,
                  "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    return await channels_state(ctx)


async def channels_state(ctx: Context) -> dict:
    prefs = await db.notification_preferences.find_one({"org_id": ctx.org_id}, {"_id": 0}) or {}
    enabled = prefs.get("channels", {})
    return {"channels": [{**c, "enabled": enabled.get(c["key"], c["configured"])}
                         for c in NOTIFICATION_CHANNELS],
            "events": [e for e in EVENT_CATALOG if e["notify"]]}
