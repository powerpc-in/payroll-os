"""Event bus — one authoritative `emit()` behind every business action.

Fan-out per event:
  1. audit_logs            (who / what / old → new / when)
  2. notifications         (in-app now; email/web-push/APNs/FCM are registered channels
                            that stay queued until a provider is configured — never faked)
  3. webhook_deliveries    (signed outbound HTTP with attempt history + backoff retries)

Connectors (Salesforce, Zoho, …) consume the SAME catalog and the same delivery
pipeline — a provider adapter is just another subscriber, so nothing about the
integration layer reaches into payroll services.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from lib.db import db

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [2, 8]          # between attempt 1→2 and 2→3
RETRY_AFTER_MINUTES = 15          # scheduled retry window offered for failed deliveries
SIGNATURE_VERSION = "v1"

# Registered notification channels. `configured` reflects reality: in-app is live; the
# others are architecture + queueing only until a provider is wired up.
NOTIFICATION_CHANNELS = [
    {"key": "in_app", "label": "In-app", "configured": True,
     "note": "Delivered immediately to the bell menu and /app/notifications."},
    {"key": "email", "label": "Email", "configured": False,
     "note": "Queued. Requires an email provider to be configured — nothing is sent yet."},
    {"key": "web_push", "label": "Web push (PWA)", "configured": False,
     "note": "Queued. Requires VAPID keys + a push subscription from the installed PWA."},
    {"key": "mobile_push", "label": "Android / iOS push", "configured": False,
     "note": "Queued. Requires FCM/APNs credentials; the same event payload is reused."},
]

# Catalog of platform events: webhook-subscribable, notification-worthy, or both.
EVENT_CATALOG = [
    {"event": "employee.created", "category": "People", "webhook": True, "notify": False},
    {"event": "employee.updated", "category": "People", "webhook": True, "notify": False},
    {"event": "employee.terminated", "category": "People", "webhook": True, "notify": True},
    {"event": "salary.updated", "category": "Compensation", "webhook": True, "notify": False},
    {"event": "payroll.created", "category": "Payroll", "webhook": True, "notify": False},
    {"event": "payroll.calculated", "category": "Payroll", "webhook": True, "notify": True},
    {"event": "payroll.submitted", "category": "Payroll", "webhook": True, "notify": True},
    {"event": "payroll.approved", "category": "Payroll", "webhook": True, "notify": True},
    {"event": "payroll.locked", "category": "Payroll", "webhook": True, "notify": True},
    {"event": "payroll.reversed", "category": "Payroll", "webhook": True, "notify": True},
    {"event": "payslip.generated", "category": "Payroll", "webhook": True, "notify": True},
    {"event": "leave.approved", "category": "Leave", "webhook": True, "notify": True},
    {"event": "leave.rejected", "category": "Leave", "webhook": True, "notify": True},
    {"event": "reimbursement.approved", "category": "Reimbursements", "webhook": True, "notify": True},
    {"event": "reimbursement.rejected", "category": "Reimbursements", "webhook": True, "notify": True},
    {"event": "loan.created", "category": "Loans", "webhook": True, "notify": True},
    {"event": "ff.created", "category": "Full & Final", "webhook": True, "notify": False},
    {"event": "ff.approved", "category": "Full & Final", "webhook": True, "notify": True},
    {"event": "ff.settled", "category": "Full & Final", "webhook": True, "notify": True},
    {"event": "compliance.rule_added", "category": "Compliance", "webhook": True, "notify": True},
    {"event": "webhook.test", "category": "Platform", "webhook": True, "notify": False},
]

WEBHOOK_EVENTS = [e["event"] for e in EVENT_CATALOG if e["webhook"]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sign(secret: str, body: bytes, timestamp: str) -> str:
    """HMAC-SHA256 over "<timestamp>.<body>" — timestamped to defeat replay."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"{SIGNATURE_VERSION}={mac.hexdigest()}"


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
    """Record audit + notifications, then fan out webhooks (never blocks the caller's
    business action, and a webhook failure never fails that action)."""
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
        prefs = await db.notification_preferences.find_one({"org_id": org_id}) or {}
        channels = [c["key"] for c in NOTIFICATION_CHANNELS
                    if prefs.get("channels", {}).get(c["key"], c["configured"])]
        docs = [{
            "id": os.urandom(16).hex(),
            "org_id": org_id,
            "user_id": uid,
            "event": event,
            "title": summary or event,
            "data": data or {},
            "read": False,
            # in_app is delivered here and now; other channels stay 'queued' until a
            # provider exists — the UI shows that honestly instead of claiming a send.
            "channels": {c: ("delivered" if c == "in_app" else "queued") for c in channels},
            "created_at": _now(),
        } for uid in notify_user_ids]
        if docs:
            await db.notifications.insert_many(docs)

    hooks = await db.webhooks.find({"org_id": org_id, "active": True, "events": event}).to_list(50)
    if hooks:
        payload = {
            "event": event,
            "org_id": org_id,
            "entity": entity,
            "entity_id": entity_id,
            "timestamp": _now().isoformat(),
            "data": data or {},
        }
        asyncio.get_event_loop().create_task(_deliver_many(hooks, payload))


async def _deliver_many(hooks: list[dict], payload: dict) -> None:
    for hook in hooks:
        delivery_id = os.urandom(16).hex()
        await db.webhook_deliveries.insert_one({
            "id": delivery_id,
            "org_id": hook.get("org_id"),
            "webhook_id": hook["id"],
            "event": payload["event"],
            "url": hook["url"],
            "payload": payload,
            "status": "pending",
            "success": False,
            "status_code": None,
            "attempts": 0,
            "attempt_log": [],
            "error": None,
            "next_retry_at": None,
            "created_at": _now(),
        })
        try:
            await deliver(delivery_id)
        except Exception as exc:  # a delivery bug must never break the business action
            logger.exception("webhook delivery crashed: %s", exc)


async def deliver(delivery_id: str) -> dict:
    """Attempt (or re-attempt) one delivery with backoff; records every attempt."""
    delivery = await db.webhook_deliveries.find_one({"id": delivery_id})
    if not delivery:
        raise ValueError("delivery not found")
    hook = await db.webhooks.find_one({"id": delivery["webhook_id"]})
    if not hook:
        raise ValueError("webhook not found")

    body = json.dumps(delivery["payload"], default=str).encode()
    attempts = list(delivery.get("attempt_log") or [])
    status_code: int | None = None
    error: str | None = None

    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as http:
        for i in range(MAX_ATTEMPTS):
            ts = str(int(_now().timestamp()))
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Event": delivery["event"],
                "X-Webhook-Delivery": delivery_id,
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Signature": sign(hook.get("secret", ""), body, ts),
            }
            started = _now()
            try:
                res = await http.post(hook["url"], content=body, headers=headers)
                status_code = res.status_code
                error = None if res.status_code < 400 else f"HTTP {res.status_code}"
            except Exception as exc:
                status_code, error = None, str(exc)[:300]
            attempts.append({
                "attempt": len(attempts) + 1,
                "at": started,
                "status_code": status_code,
                "error": error,
                "duration_ms": round((_now() - started).total_seconds() * 1000, 1),
            })
            if error is None:
                break
            if i < MAX_ATTEMPTS - 1:
                await asyncio.sleep(BACKOFF_SECONDS[min(i, len(BACKOFF_SECONDS) - 1)])

    success = error is None
    updates = {
        "status": "success" if success else "failed",
        "success": success,
        "status_code": status_code,
        "error": error,
        "attempts": len(attempts),
        "attempt_log": attempts,
        "delivered_at": _now() if success else None,
        "next_retry_at": None if success else _now() + timedelta(minutes=RETRY_AFTER_MINUTES),
    }
    await db.webhook_deliveries.update_one({"id": delivery_id}, {"$set": updates})
    if not success:
        logger.warning("webhook %s delivery %s failed after %d attempt(s): %s",
                       hook["id"], delivery_id, len(attempts), error)
        await db.webhooks.update_one({"id": hook["id"]}, {"$set": {"last_failure_at": _now(),
                                                                   "last_error": error}})
    else:
        await db.webhooks.update_one({"id": hook["id"]}, {"$set": {"last_success_at": _now(),
                                                                   "last_error": None}})
    doc = await db.webhook_deliveries.find_one({"id": delivery_id}, {"_id": 0})
    return doc or {}
