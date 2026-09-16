"""Secure document storage — metadata + base64 payload with access control.
Sensitive documents are never served without an authenticated session."""

from base64 import b64decode, b64encode
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from lib.auth import Context, get_ctx, require_perm
from lib.db import db

router = APIRouter(prefix="/v1/documents", tags=["Documents"])


def now() -> datetime:
    return datetime.now(timezone.utc)


MAX_SIZE = 5 * 1024 * 1024  # 5 MB per document in the MVP


@router.get("")
async def list_documents(ctx: Context = Depends(get_ctx), employee_id: str | None = None):
    if ctx.role == "EMPLOYEE":
        employee_id = ctx.user.get("employee_id") or "__none__"
    query: dict = {"org_id": ctx.org_id}
    if employee_id:
        query["employee_id"] = employee_id
    docs = await db.documents.find(query, {"_id": 0, "data": 0}).sort("created_at", -1).to_list(200)
    return docs


@router.post("")
async def upload(employee_id: str | None = Form(None), category: str = Form("other"),
                 file: UploadFile = File(...), ctx: Context = Depends(get_ctx)):
    if not ctx.can("documents.upload"):
        raise HTTPException(status_code=403, detail="Missing permission: documents.upload")
    if employee_id:
        if ctx.role == "EMPLOYEE":
            raise HTTPException(status_code=403, detail="Employees can only upload their own documents")
        emp = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id})
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    else:
        employee_id = ctx.user.get("employee_id") if ctx.role == "EMPLOYEE" else None
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 5 MB MVP limit")
    import uuid
    doc = {
        "id": str(uuid.uuid4()), "org_id": ctx.org_id, "employee_id": employee_id,
        "category": category, "filename": file.filename, "content_type": file.content_type,
        "size": len(content), "version": 1, "data": b64encode(content).decode(),
        "created_by": ctx.user["email"], "created_at": now(),
    }
    await db.documents.insert_one(doc)
    meta = {k: v for k, v in doc.items() if k != "data"}
    return meta


@router.get("/{document_id}/download")
async def download(document_id: str, ctx: Context = Depends(get_ctx)):
    doc = await db.documents.find_one({"id": document_id, "org_id": ctx.org_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if ctx.role == "EMPLOYEE" and doc.get("employee_id") != ctx.user.get("employee_id"):
        raise HTTPException(status_code=403, detail="Not your document")
    import io
    data = b64decode(doc["data"])
    return StreamingResponse(iter([data]), media_type=doc.get("content_type") or "application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'})


@router.delete("/{document_id}")
async def delete_document(document_id: str, ctx: Context = Depends(require_perm("documents.delete"))):
    await db.documents.delete_one({"id": document_id, "org_id": ctx.org_id})
    return {"ok": True}
