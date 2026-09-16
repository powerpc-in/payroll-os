"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

logger = logging.getLogger(__name__)

# One entry per collection: every field a route filters, sorts, or dedupes on. Applied by ensure_indexes() at startup.
def _uid() -> IndexModel:
    return IndexModel([("id", ASCENDING)], name="id", unique=True)


INDEXES: dict[str, list[IndexModel]] = {
    "status_checks": [IndexModel([("timestamp", DESCENDING)], name="timestamp_desc")],
    "users": [_uid(), IndexModel([("email", ASCENDING)], name="email", unique=True)],
    "organisations": [_uid()],
    "employees": [
        _uid(),
        IndexModel([("org_id", ASCENDING), ("employee_code", ASCENDING)], name="org_code", unique=True),
        IndexModel([("org_id", ASCENDING), ("status", ASCENDING)], name="org_status"),
        IndexModel([("org_id", ASCENDING), ("department_id", ASCENDING)], name="org_dept"),
        IndexModel([("org_id", ASCENDING), ("user_id", ASCENDING)], name="org_user"),
    ],
    "salary_assignments": [
        _uid(),
        IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("active", ASCENDING)], name="org_emp_active"),
        IndexModel([("org_id", ASCENDING), ("structure_id", ASCENDING)], name="org_structure"),
    ],
    "salary_structures": [_uid(), IndexModel([("org_id", ASCENDING)], name="org")],
    "salary_components": [_uid(), IndexModel([("org_id", ASCENDING), ("code", ASCENDING)], name="org_code", unique=True)],
    "departments": [_uid(), IndexModel([("org_id", ASCENDING), ("name", ASCENDING)], name="org_name")],
    "locations": [_uid(), IndexModel([("org_id", ASCENDING), ("name", ASCENDING)], name="org_name")],
    "designations": [_uid(), IndexModel([("org_id", ASCENDING), ("name", ASCENDING)], name="org_name")],
    "cost_centres": [_uid(), IndexModel([("org_id", ASCENDING), ("name", ASCENDING)], name="org_name")],
    "payroll_runs": [_uid(), IndexModel([("org_id", ASCENDING), ("period", ASCENDING)], name="org_period", unique=True)],
    "payroll_employees": [
        _uid(),
        IndexModel([("run_id", ASCENDING), ("employee_id", ASCENDING)], name="run_emp", unique=True),
        IndexModel([("org_id", ASCENDING), ("period", DESCENDING), ("run_status", ASCENDING)], name="org_period_status"),
        IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("period", DESCENDING)], name="org_emp_period"),
    ],
    "payroll_inputs": [_uid(), IndexModel([("run_id", ASCENDING), ("employee_id", ASCENDING)], name="run_emp")],
    "statutory_rules": [
        _uid(),
        IndexModel([("jurisdiction", ASCENDING), ("rule_type", ASCENDING), ("state", ASCENDING), ("version", DESCENDING)], name="rule_lookup"),
    ],
    "leave_types": [_uid(), IndexModel([("org_id", ASCENDING), ("code", ASCENDING)], name="org_code")],
    "leave_balances": [_uid(), IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("leave_type_id", ASCENDING)], name="org_emp_type")],
    "leave_requests": [
        _uid(),
        IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("created_at", DESCENDING)], name="org_emp_created"),
        IndexModel([("org_id", ASCENDING), ("status", ASCENDING)], name="org_status"),
    ],
    "attendance": [
        _uid(),
        IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("date", ASCENDING)], name="org_emp_date", unique=True),
        IndexModel([("org_id", ASCENDING), ("period", ASCENDING)], name="org_period"),
    ],
    "reimbursements": [
        _uid(),
        IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("status", ASCENDING)], name="org_emp_status"),
        IndexModel([("org_id", ASCENDING), ("status", ASCENDING)], name="org_status"),
    ],
    "loans": [_uid(), IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING), ("status", ASCENDING)], name="org_emp_status")],
    "loan_repayments": [_uid(), IndexModel([("loan_id", ASCENDING)], name="loan")],
    "documents": [_uid(), IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING)], name="org_emp")],
    "ffs": [_uid(), IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING)], name="org_emp")],
    "webhooks": [_uid(), IndexModel([("org_id", ASCENDING)], name="org")],
    "webhook_deliveries": [_uid(), IndexModel([("webhook_id", ASCENDING), ("created_at", DESCENDING)], name="hook_created")],
    "notifications": [_uid(), IndexModel([("org_id", ASCENDING), ("user_id", ASCENDING), ("created_at", DESCENDING)], name="org_user_created")],
    "audit_logs": [_uid(), IndexModel([("org_id", ASCENDING), ("created_at", DESCENDING)], name="org_created")],
    "integration_connections": [_uid(), IndexModel([("org_id", ASCENDING), ("provider", ASCENDING)], name="org_provider")],
    "sync_jobs": [_uid(), IndexModel([("org_id", ASCENDING), ("connection_id", ASCENDING)], name="org_conn")],
    "sync_logs": [_uid(), IndexModel([("connection_id", ASCENDING), ("created_at", DESCENDING)], name="conn_created")],
    "tax_declarations": [_uid(), IndexModel([("org_id", ASCENDING), ("employee_id", ASCENDING)], name="org_emp", unique=True)],
    "saved_reports": [_uid(), IndexModel([("org_id", ASCENDING)], name="org")],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
