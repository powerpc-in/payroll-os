"""Event bus: one emit → audit log + in-app notifications + outbound webhooks.

Webhooks are delivered by a background task with retries and a full delivery
log. A failed webhook never fails the business action that triggered it.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from lib.db import db

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def emit(
    org_id: str,
    event: str,
    *,
    actor: dict | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    old: dict | None = None,
    new: dict | None = None,
    summary: str | None = None,
    notify_user_ids: list[str] | None = None,
    data: dict | None = None,
) -> None:
    """Record audit + notifications, then fan out webhooks (fire-and-forget)."""
    await db.audit_logs.insert_one({
        "id": os.urandom(16).hex(),
        "org_id": org_id,
        "user_id": (actor or {}).get("id"),
        "user_email": (actor or {}).get("email"),
        "action": event,
        "entity": entity,
        "entity_id": entity_id,
        "old": old,
        "new": new,
        "summary": summary,
        "created_at": _now(),
    })

    if notify_user_ids:
        docs = [{
            "id": os.urandom(16).hex(),
            "org_id": org_id,
            "user_id": uid,
            "event": event,
            "title": summary or event,
            "read": False,
            "created_at": _now(),
        } for uid in notify_user_ids]
        if docs:
            await db.notifications.insert_many(docs)

    hooks = await db.webhooks.find({"org_id": org_id, "active": True, "events": event}).to_list(50)
    if hooks:
        payload = {
            "event": event,
            "org_id": org_id,
            "timestamp": _now().isoformat(),
            "data": data or {},
        }
        asyncio.get_event_loop().create_task(_deliver(hooks, payload))


async def _deliver(hooks: list[dict], payload: dict) -> None:
    body = json.dumps(payload, default=str).encode()
    async with httpx.AsyncClient(timeout=6) as http:
        for hook in hooks:
            sig = hmac.new(hook.get("secret", "").encode(), body, hashlib.sha256).hexdigest()
            headers = {"Content-Type": "application/json", "X-Webhook-Signature": sig}
            attempts, last_error, last_status = 0, None, None
            for attempt in range(3):
                attempts += 1
                try:
                    res = await http.post(hook["url"], content=body, headers=headers)
                    last_status = res.status_code
                    last_error = None if res.status_code < 400 else f"HTTP {res.status_code}"
                    if res.status_code < 400:
                        break
                except Exception as exc:
                    last_error = str(exc)[:300]
                if attempt < 2:
                    await asyncio.sleep(2)
            await db.webhook_deliveries.insert_one({
                "id": os.urandom(16).hex(),
                "org_id": hook.get("org_id"),
                "webhook_id": hook["id"],
                "event": payload["event"],
                "url": hook["url"],
                "success": last_error is None,
                "status_code": last_status,
                "attempts": attempts,
                "error": last_error,
                "created_at": _now(),
            })
            if last_error:
                logger.warning("webhook %s delivery failed after %d attempts: %s", hook["id"], attempts, last_error)
