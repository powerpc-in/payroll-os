"""Jurisdiction-aware statutory rule resolution.

Rules live as versioned documents in `statutory_rules`. The payroll engine never
hard-codes a rate or threshold: it asks this service for the rule that was in
force on the payroll date, for the employee's jurisdiction + state. Historical
runs keep a snapshot of the exact rule versions they used (data versioning), so
later rule changes never rewrite history.

Fail-safe semantics: if a required rule is missing or the applicable rule is
unverified AND the organisation has not opted into unverified values, callers
raise RuleUnavailable and the employee's payroll row fails safely instead of
producing a guessed figure.
"""

from datetime import datetime, timezone

from lib.db import db


class RuleUnavailable(Exception):
    def __init__(self, rule_type: str, jurisdiction: str, state: str | None, reason: str):
        self.rule_type = rule_type
        self.jurisdiction = jurisdiction
        self.state = state
        self.reason = reason
        super().__init__(reason)


def _on_date_str(on_date: str | None) -> str:
    if on_date:
        return on_date
    from lib.dates import today_iso
    return today_iso()


async def find_rules(
    org_id: str, jurisdiction: str, rule_type: str, on_date: str | None = None,
    state: str | None = None,
) -> list[dict]:
    on = _on_date_str(on_date)
    query: dict = {
        "jurisdiction": jurisdiction,
        "rule_type": rule_type,
        "active": True,
        "effective_from": {"$lte": on},
        "$or": [{"effective_to": None}, {"effective_to": {"$gte": on}}],
    }
    if state:
        query["state"] = {"$in": [None, state]}
    else:
        query["state"] = None
    docs = await db.statutory_rules.find(query).sort("version", -1).to_list(50)
    if state:
        docs.sort(key=lambda d: 0 if d.get("state") == state else 1)  # state-specific wins
    return docs


async def get_rule(
    org_id: str, jurisdiction: str, rule_type: str, on_date: str | None = None,
    state: str | None = None, allow_unverified: bool = False,
) -> dict:
    docs = await find_rules(org_id, jurisdiction, rule_type, on_date, state)
    if not docs:
        raise RuleUnavailable(
            rule_type, jurisdiction, state,
            f"No active '{rule_type}' rule found for {jurisdiction}"
            + (f"/{state}" if state else "") + f" effective {on_date or 'today'}",
        )
    doc = docs[0]
    if not doc.get("verified", False) and not allow_unverified:
        raise RuleUnavailable(
            rule_type, jurisdiction, state,
            f"Rule '{rule_type}' v{doc.get('version')} is marked 'Requires statutory "
            "verification' — refusing to compute with unverified values",
        )
    return doc


def rule_ref(doc: dict) -> dict:
    """The snapshot a payroll result stores, tying it to the exact rule version used."""
    return {
        "id": doc.get("id"),
        "rule_type": doc.get("rule_type"),
        "jurisdiction": doc.get("jurisdiction"),
        "state": doc.get("state"),
        "version": doc.get("version"),
        "source": doc.get("source"),
        "source_date": doc.get("source_date"),
        "verified": doc.get("verified", False),
        "effective_from": doc.get("effective_from"),
        "effective_to": doc.get("effective_to"),
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
