"""Helpers for manager access to their direct reports."""

from fastapi import HTTPException

from lib.db import db


async def manager_employee_id(ctx) -> str | None:
    manager = await db.employees.find_one(
        {"org_id": ctx.org_id, "user_id": ctx.user_id}, {"id": 1})
    return manager.get("id") if manager else None


async def manager_team_ids(ctx) -> list[str]:
    manager_id = await manager_employee_id(ctx)
    if not manager_id:
        return []
    reports = await db.employees.find(
        {"org_id": ctx.org_id, "reporting_manager_id": manager_id}, {"id": 1}).to_list(5000)
    return [employee["id"] for employee in reports]


async def require_manager_team_member(ctx, employee_id: str) -> None:
    manager_id = await manager_employee_id(ctx)
    if not manager_id or not await db.employees.find_one(
            {"id": employee_id, "org_id": ctx.org_id, "reporting_manager_id": manager_id}, {"id": 1}):
        raise HTTPException(status_code=404, detail="Employee not found")
