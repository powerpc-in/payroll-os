// Hand-written mirrors of the backend Pydantic payloads — nothing infers across
// the Python boundary. When a backend model changes, change it here in the same edit.

export type RunStatus = "draft" | "calculated" | "review" | "approved" | "locked";

export interface OrgSummary {
  id: string;
  name: string;
  jurisdiction: string;
  onboarded: boolean;
  accept_unverified_statutory_values: boolean;
}

export interface SessionPayload {
  user: { id: string; name: string; email: string };
  org: OrgSummary;
  role: string;
  permissions: string[];
  employee_id: string | null;
}

export interface Employee {
  id: string;
  org_id?: string;
  employee_code: string;
  name: string;
  date_of_birth: string | null;
  gender: string | null;
  marital_status: string | null;
  personal_email: string | null;
  work_email: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  pin: string | null;
  joining_date: string;
  confirmation_date: string | null;
  employment_type: string;
  department_id: string | null;
  department_name: string | null;
  designation: string | null;
  grade: string | null;
  location_name: string | null;
  reporting_manager_id: string | null;
  cost_centre: string | null;
  status: string;
  exit_date: string | null;
  exit_reason: string | null;
  pan: string | null;
  uan: string | null;
  pf_number: string | null;
  pf_applicable: boolean;
  esi_number: string | null;
  esi_applicable: boolean;
  pt_applicable: boolean;
  lwf_applicable: boolean;
  tax_regime: string;
  bank_name: string | null;
  bank_account: string | null;
  ifsc: string | null;
  account_holder: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  user_id: string | null;
  created_at?: string;
  gross_monthly?: number | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

export interface Explanation {
  input: string;
  rule: string;
  calculation: string;
  formula?: string;
}

export interface PayLine {
  code: string;
  name: string;
  category: string;
  monthly?: number;
  amount: number;
  taxable?: boolean;
  explanation: Explanation;
}

export interface RuleRef {
  id: string;
  rule_type: string;
  jurisdiction: string;
  state: string | null;
  version: number;
  source?: string | null;
  verified: boolean;
  effective_from?: string | null;
  effective_to?: string | null;
}

export interface RunTotals {
  gross: number;
  net: number;
  deductions: number;
  employer_cost: number;
  headcount: number;
  errors: number;
}

export interface PayrollRun {
  id: string;
  org_id?: string;
  jurisdiction: string;
  period: string;
  title: string;
  status: RunStatus;
  totals: RunTotals;
  rule_refs?: RuleRef[];
  created_at: string;
  calculated_at?: string;
  created_by?: string;
  payslips_generated?: boolean;
}

export interface PayrollRow {
  run_id: string;
  org_id?: string;
  fy: string;
  period: string;
  employee_id: string;
  status: "ok" | "error";
  error_reason?: string | null;
  employee_snapshot: {
    name: string;
    employee_code: string | null;
    department?: string | null;
    designation?: string | null;
    location?: string | null;
    state?: string | null;
    cost_centre?: string | null;
    pan_masked?: string | null;
    tax_regime: string;
  };
  paid_days: number;
  lop_days: number;
  total_days: number;
  earnings: PayLine[];
  deductions: PayLine[];
  employer_contributions: PayLine[];
  gross_earnings: number;
  taxable_gross: number;
  total_deductions: number;
  total_employer_contributions: number;
  net_pay: number;
  employer_cost: number;
  tds_amount: number;
  pf_employee: number;
  pf_employer: number;
  esi_employee: number;
  esi_employer: number;
  pt_amount: number;
  lwf_amount: number;
  rule_refs: RuleRef[];
  computed_with_unverified_rules: boolean;
  reimbursement_ids?: string[];
}

export interface StatutoryRule extends RuleRef {
  params: Record<string, unknown>;
  active: boolean;
  notes?: string | null;
  verification_status?: string;
  created_by?: string;
}

export interface StructureComponent {
  code: string;
  name: string;
  calc: "fixed" | "pct_gross" | "pct_basic" | "gross_balance";
  value: number;
  taxable: boolean;
  pf_applicable: boolean;
  esi_applicable: boolean;
  ctc_included: boolean;
}

export interface SalaryStructure {
  id: string;
  org_id?: string;
  name: string;
  components: StructureComponent[];
  created_at: string;
}

export interface SalaryAssignment {
  id: string;
  org_id?: string;
  employee_id: string;
  structure_id: string;
  gross_monthly: number;
  effective_from: string;
  active: boolean;
  created_at?: string;
}

export interface Master {
  id: string;
  name: string;
  city?: string;
  state?: string;
}

export interface AttendanceRow {
  id?: string;
  employee_id: string;
  date: string;
  status: string;
  days: number;
  overtime_hours: number;
  period: string;
}

export interface LeaveType {
  id: string;
  code: string;
  name: string;
  annual_quota: number;
  paid: boolean;
  carry_forward: boolean;
}

export interface LeaveBalance {
  id: string;
  employee_id: string;
  leave_type_id: string;
  leave_code: string;
  granted: number;
  used: number;
  year: string;
}

export interface LeaveRequest {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type_id: string;
  leave_code: string;
  leave_name: string;
  paid: boolean;
  unpaid: boolean;
  from_date: string;
  to_date: string;
  days: number;
  reason?: string | null;
  status: string;
  created_at: string;
  decided_by?: string | null;
}

export interface Reimbursement {
  id: string;
  employee_id: string;
  employee_name: string;
  category: string;
  amount: number;
  description?: string | null;
  date: string;
  taxable: boolean;
  status: string;
  approved_amount: number;
  reject_reason?: string | null;
}

export interface ScheduleRow {
  n: number;
  period: string;
  emi: number;
  principal: number;
  interest: number;
  balance: number;
}

export interface Loan {
  id: string;
  employee_id: string;
  employee_name: string;
  name: string;
  principal: number;
  interest_rate: number;
  tenure_months: number;
  start_period: string;
  emi: number;
  schedule: ScheduleRow[];
  outstanding: number;
  status: string;
  deduct_from_payroll: boolean;
  repayments?: LoanRepayment[];
}

export interface LoanRepayment {
  id: string;
  loan_id: string;
  period: string;
  emi: number;
  principal: number;
  interest: number;
  paid_via: string;
}

export interface AuditLog {
  id: string;
  user_id?: string;
  user_email?: string;
  action: string;
  entity?: string | null;
  entity_id?: string | null;
  summary?: string | null;
  old?: Record<string, unknown> | null;
  new?: Record<string, unknown> | null;
  created_at: string;
}

export interface WebhookConfig {
  id: string;
  name: string;
  url: string;
  secret?: string;
  events: string[];
  active: boolean;
  created_at?: string;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
  failed_deliveries?: number;
}

export interface WebhookAttempt {
  attempt: number;
  at: string;
  status_code?: number | null;
  error?: string | null;
  duration_ms?: number;
}

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  event: string;
  url: string;
  status: string;
  success: boolean;
  status_code?: number | null;
  attempts: number;
  attempt_log?: WebhookAttempt[];
  error?: string | null;
  next_retry_at?: string | null;
  delivered_at?: string | null;
  created_at: string;
}

export interface WebhookEventInfo {
  event: string;
  category: string;
  webhook: boolean;
  notify: boolean;
}

export interface DeliveryFeed {
  items: WebhookDelivery[];
  counts: { success: number; failed: number; pending: number };
}

export interface NotificationChannel {
  key: string;
  label: string;
  configured: boolean;
  enabled: boolean;
  note: string;
}

export interface NotificationChannelState {
  channels: NotificationChannel[];
  events: WebhookEventInfo[];
}

export interface ConfigField {
  key: string;
  label: string;
  secret: boolean;
}

export interface IntegrationProvider {
  key: string;
  name: string;
  description: string;
  products: string[];
  status: string;
  config_fields: ConfigField[];
  objects: string[];
  auth: string;
}

export interface IntegrationConnection {
  id: string;
  provider: string;
  name: string;
  config: Record<string, string>;
  secrets_configured: boolean;
  status: string;
  mappings: { object: string; field_map: Record<string, string> }[];
  last_tested_at?: string | null;
  created_at?: string;
}

export interface SyncLog {
  id: string;
  connection_id: string;
  kind: string;
  success: boolean;
  message: string;
  created_at: string;
}

export interface RegimeResult {
  rule_ref: RuleRef;
  lines: { label: string; amount: number }[];
  taxable_income: number;
  tax_before_rebate: number;
  rebate_87a: number;
  surcharge: number;
  health_education_cess: number;
  annual_tax: number;
  monthly_tds: number;
  slab_lines: string[];
}

export interface TaxComparison {
  employee_id: string;
  fy: string;
  months_elapsed_in_fy: number;
  regimes: { old?: RegimeResult; new?: RegimeResult };
  difference?: { old_minus_new: number; cheaper_regime: string };
  unverified?: boolean;
  error?: string | null;
}

export interface FFLine {
  code: string;
  name: string;
  amount: number;
  explanation: Explanation;
  rule_ref?: RuleRef;
}

export interface FFSettlement {
  id: string;
  employee_id: string;
  employee_name: string;
  employee_code?: string | null;
  department?: string | null;
  joining_date?: string | null;
  last_working_day: string;
  period?: string;
  exit_reason?: string | null;
  notes?: string | null;
  payable: FFLine[];
  recoveries: FFLine[];
  tax_adjustment: number;
  tax_adjustment_note?: string;
  total_payable: number;
  total_recoveries: number;
  net_settlement: number;
  gratuity_note?: string | null;
  computation_notes?: string[];
  computed_with_unverified_rules?: boolean;
  payment_reference?: string | null;
  approved_by?: string | null;
  settled_by?: string | null;
  created_by?: string;
  created_at?: string;
  status: string;
}

export interface AppNotification {
  id: string;
  event: string;
  title: string;
  read: boolean;
  channels?: Record<string, string>;
  data?: Record<string, unknown>;
  created_at: string;
}

export interface DocumentMeta {
  id: string;
  employee_id?: string | null;
  category: string;
  filename: string;
  content_type: string;
  size: number;
  version: number;
  created_by: string;
  created_at: string;
}

export interface DeptCost {
  department: string;
  gross: number;
  net: number;
  headcount: number;
}

export interface DashboardData {
  role: string;
  org: OrgSummary | null;
  period: string;
  headcount?: number;
  exits?: number;
  new_joiners?: number;
  latest_run?: PayrollRun | null;
  dept_cost?: DeptCost[];
  trends?: { period: string; gross: number; net: number; employer_cost: number; headcount: number; errors: number }[];
  pending?: { leave: number; reimbursements: number };
  compliance_alerts?: { unverified_rules: number; missing_salary_assignments: boolean; run_errors: number };
  employee?: {
    profile: Employee | null;
    latest_payslip: PayrollRow | null;
    ytd: { gross: number; net: number; tds: number; pf: number };
    leave_balances: LeaveBalance[];
    attendance_this_month: { status: string; days: number }[];
    payslip_ready: boolean;
  } | null;
  notice?: string;
}

export interface ReportField {
  key: string;
  label: string;
  numeric: boolean;
}

export interface ReportDataset {
  key: string;
  name: string;
  fields: ReportField[];
  time_field: string | null;
  group_only: string | null;
  flatten: boolean;
  groupable: string[];
}

export interface ReportCatalog {
  datasets: ReportDataset[];
  aggregations: string[];
  filter_ops: string[];
}

export interface ReportResult {
  dataset: string;
  name: string;
  columns: string[];
  labels: Record<string, string>;
  numeric: string[];
  group_by?: string | null;
  aggregate?: string;
  rows: Record<string, unknown>[];
  totals: Record<string, number>;
  count: number;
}

export interface SavedReport {
  id: string;
  name: string;
  config: Record<string, unknown>;
  visualization?: string;
  created_by?: string;
  created_at?: string;
}

export interface Jurisdiction {
  code: string;
  name: string;
  currency: string;
  currency_symbol: string;
  status: string;
  tax_year_label: string;
  default_pay_frequency: string;
  states: { code: string; name: string }[];
  rule_types: string[];
  note?: string;
}

export interface OrgUser {
  id: string;
  name: string;
  email: string;
  role: string;
  employee_id: string | null;
  mfa_enabled: boolean;
}

export interface ImportReport {
  imported: number;
  errors: { row: number; name?: string; errors: string[] }[];
  total: number;
}
