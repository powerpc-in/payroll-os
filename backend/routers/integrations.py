"""Integration framework — provider registry, connections, field mappings, sync jobs.

Provider adapters (Salesforce, Zoho, future connectors) never touch business
collections directly: PayrollOS → Integration Layer → Provider Adapter → External
System. Connection tests perform REAL credential checks against the provider's
auth endpoint; when credentials are absent the result is an explicit
'requires configuration' failure — the system never fabricates a successful sync.
"""

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit

router = APIRouter(prefix="/v1/integrations", tags=["Integrations"])


def now() -> datetime:
    return datetime.now(timezone.utc)


SECRET_KEYS = {"client_secret", "password", "security_token", "refresh_token", "api_key"}

PROVIDERS: dict[str, dict] = {
    "salesforce": {
        "name": "Salesforce", "status": "available",
        "description": "Sync employees, departments and payroll summaries to Salesforce "
                       "Contacts/Users/Accounts and custom payroll objects.",
        "products": ["Salesforce CRM"],
        "config_fields": [
            {"key": "client_id", "label": "Consumer Key (client id)", "secret": False},
            {"key": "client_secret", "label": "Consumer Secret", "secret": True},
            {"key": "username", "label": "Integration user email", "secret": False},
            {"key": "password", "label": "Integration user password", "secret": True},
            {"key": "security_token", "label": "Security token", "secret": True},
        ],
        "objects": ["Contact", "User", "Account", "Custom payroll objects"],
        "auth": "OAuth2 (username-password or web flow)",
    },
    "zoho": {
        "name": "Zoho", "status": "available",
        "description": "Sync employees, organisation and payroll summaries to Zoho People / "
                       "Zoho Books / Zoho Payroll via OAuth.",
        "products": ["Zoho People", "Zoho Books", "Zoho Payroll"],
        "config_fields": [
            {"key": "client_id", "label": "Client ID", "secret": False},
            {"key": "client_secret", "label": "Client Secret", "secret": True},
            {"key": "refresh_token", "label": "Refresh token", "secret": True},
        ],
        "objects": ["Employee", "Organisation", "Payroll summary"],
        "auth": "OAuth2 (refresh token)",
    },
    "quickbooks": {
        "name": "QuickBooks", "status": "planned",
        "description": "Accounting sync (journal entries for payroll) — connector slot reserved.",
        "products": ["QuickBooks Online"], "config_fields": [], "objects": [], "auth": "OAuth2",
    },
    "xero": {
        "name": "Xero", "status": "planned",
        "description": "Accounting sync — connector slot reserved.",
        "products": ["Xero"], "config_fields": [], "objects": [], "auth": "OAuth2",
    },
    "slack": {
        "name": "Slack", "status": "planned",
        "description": "Notification delivery — connector slot reserved.",
        "products": ["Slack"], "config_fields": [], "objects": [], "auth": "OAuth bot token",
    },
}


def _mask_config(config: dict) -> dict:
    return {k: ("•••configured" if k in SECRET_KEYS and v else v) for k, v in (config or {}).items()}


@router.get("/providers")
async def providers(ctx: Context = Depends(require_perm("integrations.manage"))):
    return [{"key": k, **{kk: vv for kk, vv in v.items()}} for k, v in PROVIDERS.items()]


class ConnectionIn(BaseModel):
    provider: str
    name: str | None = None
    config: dict = {}


@router.get("/connections")
async def list_connections(ctx: Context = Depends(require_perm("integrations.manage"))):
    docs = await db.integration_connections.find({"org_id": ctx.org_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(100)
    for d in docs:
        d["config"] = _mask_config(d.get("config"))
    return docs


@router.post("/connections")
async def create_connection(input: ConnectionIn, ctx: Context = Depends(require_perm("integrations.manage"))):
    if input.provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{input.provider}'")
    provider = PROVIDERS[input.provider]
    if provider["status"] == "planned":
        raise HTTPException(status_code=409, detail=f"The {provider['name']} connector is not yet available")
    secrets_configured = any(input.config.get(k) for k in SECRET_KEYS)
    doc = {
        "id": new_id(), "org_id": ctx.org_id, "provider": input.provider,
        "name": input.name or provider["name"], "config": input.config,
        "secrets_configured": secrets_configured,
        "status": "requires_configuration" if not secrets_configured else "configured_unverified",
        "mappings": [], "created_at": now(),
    }
    await db.integration_connections.insert_one(doc)
    doc.pop("_id", None)
    doc["config"] = _mask_config(doc["config"])
    await emit(ctx.org_id, "integration.changed", actor=ctx.user, entity="integration_connection",
               entity_id=doc["id"], summary=f"{provider['name']} connection created "
                                            f"(status: {doc['status']})")
    return doc


class MappingIn(BaseModel):
    object: str
    field_map: dict[str, str]  # platform field → provider field


@router.put("/connections/{connection_id}/mapping")
async def upsert_mapping(connection_id: str, input: MappingIn,
                         ctx: Context = Depends(require_perm("integrations.manage"))):
    conn = await db.integration_connections.find_one({"id": connection_id, "org_id": ctx.org_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    mappings = [m for m in conn.get("mappings", []) if m["object"] != input.object]
    mappings.append(input.model_dump())
    await db.integration_connections.update_one({"id": connection_id},
                                                {"$set": {"mappings": mappings}})
    return {"ok": True, "mappings": mappings}


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, ctx: Context = Depends(require_perm("integrations.manage"))):
    conn = await db.integration_connections.find_one({"id": connection_id, "org_id": ctx.org_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    config = conn.get("config") or {}
    provider = conn["provider"]
    try:
        if provider == "salesforce":
            if not all(config.get(k) for k in ("client_id", "client_secret", "username", "password", "security_token")):
                raise ValueError("Not all Salesforce credentials are configured")
            res = httpx.post(
                "https://login.salesforce.com/services/oauth2/token",
                data={
                    "grant_type": "password", "client_id": config["client_id"],
                    "client_secret": config["client_secret"], "username": config["username"],
                    "password": config["password"] + config["security_token"],
                }, timeout=10)
            if res.status_code == 200:
                result, message = True, "Salesforce accepted the credentials (OAuth token issued)"
            else:
                result, message = False, f"Salesforce rejected the credentials (HTTP {res.status_code})"
        elif provider == "zoho":
            if not all(config.get(k) for k in ("client_id", "client_secret", "refresh_token")):
                raise ValueError("Not all Zoho credentials are configured")
            res = httpx.post(
                "https://accounts.zoho.com/oauth/v2/token",
                params={"refresh_token": config["refresh_token"], "client_id": config["client_id"],
                        "client_secret": config["client_secret"], "grant_type": "refresh_token"},
                timeout=10)
            if res.status_code == 200 and "access_token" in res.text:
                result, message = True, "Zoho accepted the credentials (access token issued)"
            else:
                result, message = False, f"Zoho rejected the credentials (HTTP {res.status_code})"
        else:
            raise ValueError(f"No live test implemented for '{provider}' yet")
    except ValueError as exc:
        result, message = False, str(exc)
    except Exception as exc:
        result, message = False, f"Connection attempt failed: {str(exc)[:200]}"

    status = "connected" if result else conn["status"]
    await db.integration_connections.update_one({"id": connection_id},
                                                {"$set": {"status": status, "last_tested_at": now()}})
    await db.sync_logs.insert_one({
        "id": new_id(), "org_id": ctx.org_id, "connection_id": connection_id,
        "kind": "connection_test", "success": result, "message": message, "created_at": now(),
    })
    return {"success": result, "message": message, "status": status}


class SyncIn(BaseModel):
    object: str


@router.post("/connections/{connection_id}/sync")
async def request_sync(connection_id: str, input: SyncIn,
                       ctx: Context = Depends(require_perm("integrations.manage"))):
    conn = await db.integration_connections.find_one({"id": connection_id, "org_id": ctx.org_id})
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.get("status") != "connected":
        job = {
            "id": new_id(), "org_id": ctx.org_id, "connection_id": connection_id,
            "object": input.object, "status": "skipped",
            "reason": "Connection is not authenticated — no sync was performed "
                      "(the platform never fabricates sync results). Connect and test first.",
            "records_synced": 0, "created_at": now(),
        }
        await db.sync_jobs.insert_one(job)
        await db.sync_logs.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "connection_id": connection_id,
            "kind": "sync", "success": False, "message": job["reason"], "created_at": now(),
        })
        job.pop("_id", None)
        return job
    # A connected adapter would run here per provider module — none ship in this MVP,
    # so an authenticated-but-unimplemented provider also reports honestly:
    job = {
        "id": new_id(), "org_id": ctx.org_id, "connection_id": connection_id,
        "object": input.object, "status": "not_implemented",
        "reason": "The connector architecture is in place but no sync adapter ships in this MVP.",
        "records_synced": 0, "created_at": now(),
    }
    await db.sync_jobs.insert_one(job)
    job.pop("_id", None)
    return job


@router.get("/connections/{connection_id}/logs")
async def logs(connection_id: str, ctx: Context = Depends(require_perm("integrations.manage"))):
    docs = await db.sync_logs.find({"org_id": ctx.org_id, "connection_id": connection_id},
                                   {"_id": 0}).sort("created_at", -1).to_list(100)
    return docs


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, ctx: Context = Depends(require_perm("integrations.manage"))):
    await db.integration_connections.delete_one({"id": connection_id, "org_id": ctx.org_id})
    return {"ok": True}
