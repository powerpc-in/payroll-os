"""Focused safety tests for payroll run state and final-settlement handling."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import payroll
from services import ff_engine


class FakeCollection:
    def __init__(self, documents=(), read_barrier=None):
        self.documents = [deepcopy(d) for d in documents]
        self.read_barrier = read_barrier
        self.reads = 0
        self.deleted = []

    async def find_one(self, query, projection=None):
        doc = next((d for d in self.documents if all(d.get(k) == v for k, v in query.items())), None)
        result = deepcopy(doc) if doc else None
        if self.read_barrier is not None and query.get("id") == "run-1":
            self.reads += 1
            if self.reads == 2:
                self.read_barrier.set()
            await self.read_barrier.wait()
        return result

    async def count_documents(self, query):
        return sum(1 for d in self.documents if all(d.get(k) == v for k, v in query.items()))

    async def update_one(self, query, update):
        doc = next((d for d in self.documents if all(d.get(k) == v for k, v in query.items())), None)
        if not doc:
            return SimpleNamespace(matched_count=0)
        doc.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1)

    async def update_many(self, query, update):
        for doc in self.documents:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))

    async def delete_one(self, query):
        self.deleted.append(query)
        self.documents = [d for d in self.documents if not all(d.get(k) == v for k, v in query.items())]

    async def insert_one(self, doc):
        self.documents.append(deepcopy(doc))


class FakeDB:
    def __init__(self, run, rows=(), read_barrier=None):
        self.payroll_runs = FakeCollection([run], read_barrier)
        self.payroll_employees = FakeCollection(rows)
        self.payroll_inputs = FakeCollection()
        self.employees = FakeCollection([{"id": "emp-1", "org_id": "org-1", "name": "Test Employee"}])


class TestContext:
    org_id = "org-1"
    user = {"id": "user-1", "email": "payroll@example.test"}


def use_payroll_db(monkeypatch, status, rows=(), read_barrier=None):
    fake = FakeDB({"id": "run-1", "org_id": "org-1", "period": "2026-04", "status": status}, rows,
                  read_barrier)
    monkeypatch.setattr(payroll, "db", fake)

    async def no_emit(*args, **kwargs):
        return None

    monkeypatch.setattr(payroll, "emit", no_emit)
    return fake


@pytest.mark.parametrize(("status", "route"), [("review", payroll.approve), ("approved", payroll.lock)])
async def test_error_employee_row_blocks_approval_and_lock(monkeypatch, status, route):
    use_payroll_db(monkeypatch, status, [{"run_id": "run-1", "org_id": "org-1", "status": "error"}])

    with pytest.raises(HTTPException) as exc:
        await route("run-1", TestContext())

    assert exc.value.status_code == 409
    assert "employee row(s) have errors" in exc.value.detail


@pytest.mark.parametrize("status", ["calculated", "locked"])
@pytest.mark.parametrize("operation", ["add", "delete"])
async def test_payroll_inputs_are_immutable_after_draft(monkeypatch, status, operation):
    fake = use_payroll_db(monkeypatch, status)
    if operation == "add":
        call = payroll.add_input("run-1", payroll.InputIn(employee_id="emp-1", input_type="bonus", amount=100),
                                 TestContext())
    else:
        call = payroll.delete_input("run-1", "input-1", TestContext())

    with pytest.raises(HTTPException) as exc:
        await call

    assert exc.value.status_code == 409
    assert fake.payroll_inputs.documents == []
    assert fake.payroll_inputs.deleted == []


async def test_locked_run_cannot_be_reversed_or_modified(monkeypatch):
    fake = use_payroll_db(monkeypatch, "locked")

    with pytest.raises(HTTPException) as exc:
        await payroll.reverse("run-1", payroll.TransitionIn(note="test"), TestContext())

    assert exc.value.status_code == 409
    assert fake.payroll_runs.documents[0]["status"] == "locked"


async def test_transition_is_single_winner_for_concurrent_requests(monkeypatch):
    barrier = asyncio.Event()
    fake = use_payroll_db(monkeypatch, "calculated", read_barrier=barrier)

    results = await asyncio.gather(
        payroll.submit_review("run-1", TestContext()),
        payroll.submit_review("run-1", TestContext()),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1
    assert failures[0].status_code == 409
    assert fake.payroll_runs.documents[0]["status"] == "review"


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    async def to_list(self, length):
        return self.documents[:length]


class FFFakeCollection(FakeCollection):
    def __init__(self, documents=(), one=None):
        super().__init__(documents)
        self.one = one

    async def find_one(self, query, projection=None):
        if self.one is not None:
            return deepcopy(self.one)
        return await super().find_one(query, projection)

    def find(self, query, projection=None):
        return FakeCursor(self.documents)


async def test_f_and_f_does_not_treat_error_row_as_paid(monkeypatch):
    fake = SimpleNamespace(
        salary_assignments=FFFakeCollection(one={"gross_monthly": 30000, "structure_id": "structure-1"}),
        salary_structures=FFFakeCollection(one={"components": [
            {"code": "BASIC", "name": "Basic", "calc": "pct_gross", "value": 100},
        ]}),
        payroll_runs=FFFakeCollection(one={"id": "run-1", "period": "2026-04", "status": "locked"}),
        payroll_employees=FFFakeCollection(one={"status": "error"}),
        attendance=FFFakeCollection(), leave_balances=FFFakeCollection(),
        leave_types=FFFakeCollection(), reimbursements=FFFakeCollection(), loans=FFFakeCollection(),
    )
    monkeypatch.setattr(ff_engine, "db", fake)

    async def no_rule(*args, **kwargs):
        from services.rules import RuleUnavailable
        raise RuleUnavailable("gratuity", "IN", None, "no verified rule")

    monkeypatch.setattr(ff_engine, "get_rule", no_rule)
    result = await ff_engine.compute_settlement(
        {"id": "org-1", "jurisdiction": "IN"},
        {"id": "emp-1", "name": "Test Employee", "joining_date": "2024-01-01"},
        {"last_working_day": "2026-04-15"},
    )

    salary = next(line for line in result["payable"] if line["code"] == "SALARY_PAYABLE")
    assert salary["amount"] == 15000
