# Vetan — Payroll & HR Operating System (MVP SPEC)

Multi-tenant, API-first payroll/HR SaaS on this pod's stack: **FastAPI + MongoDB** backend
(port 8001, all routes under `/api`, app APIs versioned at `/api/v1/*`) and **React 19 +
TypeScript strict + Tailwind v4 + shadcn (base-ui)** frontend (port 3000, relative `/api`
calls through `src/lib/api.ts`). Cross-platform strategy: **installable PWA** (manifest +
no-op SW) serving web/Android/iOS/Windows from ONE codebase and ONE backend.

## Global architecture (not India-hardcoded)
- `backend/jurisdictions/registry.py` — country registry. `IN` is `status="active"`;
  `GB, US, GH, SG, AU, AE` are `architecture_ready` placeholders with **no statutory rules**.
- `backend/services/rules.py` — resolves versioned rules from the `statutory_rules`
  collection by (jurisdiction, rule_type, state, effective date). **Fail-safe:** a missing or
  unverified rule raises `RuleUnavailable` → the employee's payroll row errors with the
  reason instead of computing a guessed number.
- Orgs may explicitly opt into computing with unverified values
  (`payroll_settings.accept_unverified_statutory_values`) — results then carry a
  "computed with unverified rules" flag and badges everywhere (UI + payslip PDF).

## Data model (Mongo; every tenant doc carries `org_id`)
organisations, users (embedded memberships [{org_id, role}]), employees,
departments/locations/designations/cost_centres, salary_structures (+inline components:
calc ∈ fixed | pct_gross | pct_basic | gross_balance), salary_assignments,
payroll_runs, payroll_employees (per-employee results + explanations + rule_refs snapshot),
payroll_inputs, statutory_rules (versioned, verified flag, source, effective_from/to),
tax_declarations, attendance, leave_types/leave_balances/leave_requests,
reimbursements, loans (+schedule)/loan_repayments, ffs (full & final),
documents (base64 ≤5MB), webhooks/webhook_deliveries, integration_connections/sync_jobs/sync_logs,
notifications, audit_logs, saved_reports. Indexes in `backend/lib/db.py` INDEXES.

## Payroll engine (deterministic; NO AI anywhere in calculations)
- `services/payroll_engine.py` — LOP-based paid days from attendance (absent +
  unpaid_leave + 0.5×half), earnings = structure components × paid factor + one-time
  inputs; statutory: PF (12%/12%, EPS 8.33%), ESI (0.75%/3.25% if gross ≤ 21k),
  PT & LWF (state-aware rules), TDS (regime-aware, annual projection → due-to-date − YTD).
- `services/tax_engine.py` — slab tax/rebate 87A/surcharge/cess from rule docs;
  old vs new regime comparison (numeric only, no recommendation).
- Workflow: DRAFT → CALCULATED → (submit) REVIEW → (approve) APPROVED → LOCK.
  Lock applies loan repayments, marks reimbursements paid, enables payslips. Reverse walks back;
  LOCKED is immutable. Every result stores the exact rule versions used (`rule_refs`).
- Payslips: `services/payslips.py` (fpdf2) at
  `/api/v1/payroll/payslips/{run_id}/{employee_id}` (payroll.view) and
  `/api/v1/me/payslips/{run_id}` (own).

## Auth & RBAC
httpOnly cookie sessions (JWT). Endpoints `/api/v1/auth/{signup,login,logout,me,
password-reset/request,password-reset/confirm}`. Roles: SUPER_ADMIN, COMPANY_ADMIN,
HR_ADMIN, PAYROLL_ADMIN, FINANCE, MANAGER, EMPLOYEE → granular permissions
(`backend/lib/rbac.py`); dependencies `require_perm(...)` enforce server-side; the
frontend mirrors for UI only (`src/lib/permissions.ts`). Tenant isolation: every query
filters `org_id` from the session context.

## Key flows
- Onboarding wizard (`/onboarding`): 8 steps → POST `/api/v1/org/onboarding`
  (company, payroll config, locations, statutory opt-in, structure, leave types,
  employees, optional test run) — atomic.
- Demo flow: signup → onboarding → employees → salary assign → attendance →
  reimbursement → payroll run create → calculate → review → approve → lock →
  payslip PDF → reports → employee login → payslip.
- Full & Final (`/app/settlements`, `/api/v1/settlements`): preview (no write) → draft →
  approve (payroll.approve) → settle (payroll.lock) → statement PDF. `services/ff_engine.py`
  computes salary payable for days served (skipped if a locked run already covers the month),
  attendance-driven LOP, leave encashment, notice pay/recovery, bonus/incentive/other,
  unpaid approved reimbursements, gratuity (versioned rule, fail-safe note when ineligible or
  rule missing), loan/advance recovery and a manually entered tax adjustment — every line has
  INPUT/RULE/FORMULA/CALCULATION + `rule_ref`. Settling is exit processing: employee →
  `exited` + exit_date/reason, salary assignment deactivated, recovered loans closed with a
  repayment row, settled reimbursements marked paid, `ff.settled` + `employee.terminated`
  emitted. Settled records are immutable. Statement PDF: `services/ff_statement.py` (fpdf2,
  transliterates when the DejaVu font is absent). Perms: `ff.view` / `ff.manage`.
  Legacy `/api/v1/compliance/ff` delegates to the same engine.
- Reporting engine (`routers/reports.py`): 19 datasets (incl. attendance summary, leave
  requests, F&F). ReportRun takes dataset + field subset + generic filters
  (eq/ne/contains/gt/gte/lt/lte) + period range + group_by + aggregate (sum/avg/min/max/count)
  + sort + limit; aggregation is server-side. Exports CSV/XLSX/PDF (`reports.export`).
  Saved reports store *configurations* (create/update/delete/run, `reports.manage`) and re-run
  against live data; the builder UI adds table/bar visualization.
- Events & webhooks (`lib/events.py`): one `emit()` → audit log + notifications + signed
  webhook deliveries. `EVENT_CATALOG` (21 events) is the single subscription surface for
  webhooks *and* future connectors. Deliveries are persisted first (`pending`), then attempted
  up to 3 times with backoff; every attempt is recorded in `attempt_log` (status, error,
  duration) and failures keep `next_retry_at` + support manual `POST
  /webhooks/deliveries/{id}/retry` (appends attempts, never resets). Signature:
  `X-Webhook-Signature: v1=hmac_sha256(secret, "<timestamp>.<raw_body>")` with
  `X-Webhook-Timestamp`/`X-Webhook-Delivery`/`X-Webhook-Event`. Org-wide feed +
  per-endpoint log + counts in the console.
- Notifications: `NOTIFICATION_CHANNELS` = in_app (live) + email / web_push / mobile_push
  (registered, `configured: false`). Each notification records per-channel state
  (`delivered` for in-app, `queued` for the rest) — nothing claims a send that did not happen.
  Org preferences at `GET/PUT /api/v1/notifications/channels` (`settings.manage`).
  Payslip-ready alerts fire per employee on payroll lock (`payslip.generated`, with
  payslip_url in the payload); leave decisions notify the applicant. User↔employee lookups
  use `memberships.org_id` + `employee_id` (users have no top-level org_id).
- Integrations: provider registry (Salesforce/Zoho available; QuickBooks/Xero/Slack
  planned). Connection test does a REAL credential check against provider OAuth
  endpoints; syncs without credentials are logged `skipped` — never faked.

## Demo data (seed.py — idempotent, fictional)
Company "Kaveri Textiles Pvt Ltd", 12 employees (states KA/MH/DL/TG/RJ, mixed regimes,
PF/ESI applicability), attendance for the previous month, approved CL leave,
reimbursements (one approved+paid via the locked run, one pending), one active loan,
previous-month payroll run LOCKED (11 ok + 1 intentional fail-safe error for Dev Patel —
RJ has no PT/LWF rules seeded, demonstrating the compliance fail-safe).
All demo logins + password in `memory/test_credentials.md`.

## Tests
- Backend: `cd /app/backend && pytest` (pytest.ini pinned; hits the live uvicorn).
- Frontend: Playwright workspace at `/app/tests` (testing subagent owns browser runs).

## Not certified
This MVP is not statutorily certified. All seeded statutory values carry
verified=False → "Requires statutory verification" badges; nothing claims government filing.
