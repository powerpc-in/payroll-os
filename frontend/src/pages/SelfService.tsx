// Employee self-service workspace: payslips, tax comparison + declarations,
// leave, attendance, profile, documents, reimbursements. Mobile-first layout.

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, FileDown, Loader2, Plane, Plus, Upload } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { apiGet, apiPost, apiPut, apiUpload } from "@/lib/api";
import type {
  DashboardData, DocumentMeta, Employee, LeaveBalance, LeaveRequest, Loan, PayrollRow,
  Reimbursement, SalaryAssignment, SalaryStructure, TaxComparison,
} from "@/lib/types";
import { currentPeriod, dateLabel, inr, monthLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, PageHeader, StatCard, VerificationBadge } from "@/components/ui-kit";

interface ProfilePayload {
  employee: Employee;
  assignment: SalaryAssignment | null;
  structure: SalaryStructure | null;
}

export default function SelfService() {
  const [tab, setTab] = useState("overview");
  return (
    <div>
      <PageHeader title="My workspace" description="Your pay, tax, leave and documents." testid="selfservice-title" />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="selfservice-tabs">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="payslips">Payslips</TabsTrigger>
          <TabsTrigger value="tax">Tax</TabsTrigger>
          <TabsTrigger value="leave">Leave</TabsTrigger>
          <TabsTrigger value="attendance">Attendance</TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="more">More</TabsTrigger>
        </TabsList>
        <TabsContent value="overview"><OverviewTab /></TabsContent>
        <TabsContent value="payslips"><PayslipsTab /></TabsContent>
        <TabsContent value="tax"><TaxTab /></TabsContent>
        <TabsContent value="leave"><LeaveTab /></TabsContent>
        <TabsContent value="attendance"><AttendanceTab /></TabsContent>
        <TabsContent value="profile"><ProfileTab /></TabsContent>
        <TabsContent value="more"><MoreTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function OverviewTab() {
  const { data } = useQuery({ queryKey: ["me-dashboard"], queryFn: () => apiGet<DashboardData>("/v1/dashboards") });
  const emp = data?.employee;
  if (!emp?.profile) return <EmptyState title="No employee record linked" description="Ask your HR admin to link your login to your employee record." testid="me-no-record" />;
  const latest = emp.latest_payslip;
  const att = emp.attendance_this_month ?? [];
  const present = att.filter((a) => a.status === "present").length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Net pay (latest)" value={latest ? inr(latest.net_pay) : "—"} sub={latest ? monthLabel(latest.period) : "No payroll yet"} testid="me-stat-net" />
        <StatCard label="YTD gross" value={inr(emp.ytd.gross)} testid="me-stat-ytd-gross" />
        <StatCard label="YTD TDS" value={inr(emp.ytd.tds)} testid="me-stat-ytd-tds" />
        <StatCard label="Days present this month" value={present} testid="me-stat-attendance" />
      </div>
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold">Monthly net pay trend</h3>
        {emp.ytd.gross > 0 ? (
          <NetTrend />
        ) : (
          <p className="text-sm text-muted-foreground">Payslip data appears after your first payroll run.</p>
        )}
      </div>
    </div>
  );
}

function NetTrend() {
  const { data } = useQuery({ queryKey: ["me-payslips"], queryFn: () => apiGet<PayrollRow[]>("/v1/me/payslips") });
  const chart = (data ?? []).slice(0, 6).reverse().map((p) => ({ period: p.period.slice(5), net: p.net_pay }));
  if (chart.length === 0) return <p className="text-sm text-muted-foreground">No payslips yet.</p>;
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={chart}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} />
        <Tooltip formatter={(value: number) => inr(value)} />
        <Bar dataKey="net" fill="#2563EB" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function PayslipsTab() {
  const { data, isPending } = useQuery({ queryKey: ["me-payslips"], queryFn: () => apiGet<PayrollRow[]>("/v1/me/payslips") });
  if (isPending) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  if ((data?.length ?? 0) === 0) return <EmptyState title="No payslips yet" description="Payslips appear once a payroll run that includes you is locked." testid="me-payslips-empty" />;
  return (
    <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="me-payslips-list">
      {data!.map((p) => (
        <li key={p.run_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <p className="text-sm font-medium">{monthLabel(p.period)}</p>
            <p className="font-mono text-xs tabular-nums text-muted-foreground">
              Gross {inr(p.gross_earnings)} · Deductions {inr(p.total_deductions)} · Net {inr(p.net_pay)}
            </p>
          </div>
          <a href={`/api/v1/me/payslips/${p.run_id}`} download data-testid={`me-payslip-download-${p.period}`}>
            <Button size="sm" variant="outline"><Download className="size-4" aria-hidden /> PDF</Button>
          </a>
        </li>
      ))}
    </ul>
  );
}

function TaxTab() {
  const queryClient = useQueryClient();
  const { data: cmp, isPending } = useQuery({ queryKey: ["me-tax"], queryFn: () => apiGet<TaxComparison>("/v1/me/tax/compare") });
  const { data: decl } = useQuery({ queryKey: ["me-declarations"], queryFn: () => apiGet<Record<string, number | boolean>>("/v1/me/tax/declarations") });
  const [form, setForm] = useState<Record<string, string>>({});
  const val = (k: string) => form[k] ?? String(decl?.[k] ?? 0);

  const save = useMutation({
    mutationFn: () => apiPut("/v1/me/tax/declarations", {
      deduction_80c: Number(val("deduction_80c")) || 0,
      deduction_80d: Number(val("deduction_80d")) || 0,
      annual_rent_paid: Number(val("annual_rent_paid")) || 0,
      other_income: Number(val("other_income")) || 0,
      metro: decl?.metro === true,
    }),
    onSuccess: () => { toast.success("Declarations saved"); queryClient.invalidateQueries({ queryKey: ["me-tax"] }); queryClient.invalidateQueries({ queryKey: ["me-declarations"] }); },
    onError: (err) => toast.error(String(err)),
  });

  if (isPending) return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  if (!cmp || cmp.error) {
    return <EmptyState title="Tax comparison unavailable" description={cmp?.error ?? "No salary assigned yet."} testid="me-tax-error" />;
  }
  const oldR = cmp.regimes.old;
  const newR = cmp.regimes.new;

  return (
    <div className="space-y-6">
      {cmp.unverified ? <VerificationBadge verified={false} /> : null}
      <div className="grid gap-5 md:grid-cols-2" data-testid="regime-comparison">
        {[["Old regime", oldR], ["New regime", newR]].map(([label, r]) => {
          const regime = r as typeof oldR;
          return (
            <div key={String(label)} className="rounded-xl border border-border bg-card p-5">
              <h3 className="font-heading text-base font-semibold">{String(label)}</h3>
              {regime ? (
                <div className="mt-3 space-y-1.5 text-sm">
                  {regime.lines.map((l, i) => (
                    <div key={i} className="flex justify-between text-xs text-muted-foreground">
                      <span>{l.label}</span>
                      <span className="font-mono tabular-nums">{inr(l.amount)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between border-t border-border pt-1.5"><span>Taxable income</span><span className="font-mono tabular-nums">{inr(regime.taxable_income)}</span></div>
                  <div className="flex justify-between"><span>Tax (slabs)</span><span className="font-mono tabular-nums">{inr(regime.tax_before_rebate)}</span></div>
                  <div className="flex justify-between"><span>Rebate 87A</span><span className="font-mono tabular-nums">−{inr(regime.rebate_87a)}</span></div>
                  <div className="flex justify-between"><span>Surcharge</span><span className="font-mono tabular-nums">{inr(regime.surcharge)}</span></div>
                  <div className="flex justify-between"><span>Health & education cess</span><span className="font-mono tabular-nums">{inr(regime.health_education_cess)}</span></div>
                  <div className="flex justify-between border-t border-border pt-1.5 font-medium"><span>Annual tax</span><span className="font-mono tabular-nums">{inr(regime.annual_tax)}</span></div>
                  <div className="flex justify-between text-blue-600 dark:text-blue-400"><span>Monthly TDS</span><span className="font-mono tabular-nums">{inr(regime.monthly_tds)}</span></div>
                </div>
              ) : <p className="mt-2 text-sm text-muted-foreground">Not available.</p>}
            </div>
          );
        })}
      </div>
      {cmp.difference ? (
        <p className="rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm" data-testid="regime-difference">
          Difference: the <strong>{cmp.difference.cheaper_regime}</strong> regime is lower by{" "}
          <span className="font-mono tabular-nums">{inr(Math.abs(cmp.difference.old_minus_new))}</span> per year.
          This is a numeric comparison only — not a recommendation.
        </p>
      ) : null}

      <div className="max-w-md space-y-3 rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-semibold">Tax declarations (old regime)</h3>
        {[["deduction_80c", "80C investments (₹/year)"], ["deduction_80d", "80D medical insurance (₹/year)"], ["annual_rent_paid", "Annual rent paid (₹)"], ["other_income", "Other income (₹/year)"]].map(([k, label]) => (
          <div key={k} className="space-y-1"><Label>{label}</Label>
            <Input type="number" data-testid={`declaration-${k.replace(/_/g, "-")}`} value={val(k)} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></div>
        ))}
        <Button onClick={() => save.mutate()} disabled={save.isPending} data-testid="declaration-save-button">
          {save.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Save declarations
        </Button>
      </div>
    </div>
  );
}

function LeaveTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ leave_type_id: "", from_date: "", to_date: "", days: "1", reason: "" });
  const { data: balances } = useQuery({ queryKey: ["me-leave-balances"], queryFn: () => apiGet<LeaveBalance[]>("/v1/me/leave/balances") });
  const { data: requests } = useQuery({ queryKey: ["me-leave-requests"], queryFn: () => apiGet<LeaveRequest[]>("/v1/me/leave/requests") });
  const { data: types } = useQuery({ queryKey: ["leave-types"], queryFn: () => apiGet<{ id: string; code: string; name: string; annual_quota: number; paid: boolean }[]>("/v1/leave/types") });

  const apply = useMutation({
    mutationFn: () => apiPost("/v1/me/leave/requests", {
      leave_type_id: form.leave_type_id, from_date: form.from_date, to_date: form.to_date,
      days: Number(form.days), reason: form.reason,
    }),
    onSuccess: () => { toast.success("Leave applied — your manager will review"); setOpen(false); queryClient.invalidateQueries({ queryKey: ["me-leave-requests"] }); },
    onError: (err) => toast.error(String(err)),
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2" data-testid="me-leave-balances">
        {(balances ?? []).map((b) => (
          <span key={b.id} className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs">
            <strong>{b.leave_code}</strong> · {Math.max(0, b.granted - b.used)} of {b.granted} left
          </span>
        ))}
      </div>
      <Button size="sm" data-testid="me-apply-leave" onClick={() => setOpen(true)}><Plus className="size-4" aria-hidden /> Apply leave</Button>
      {open ? (
        <div className="max-w-md space-y-3 rounded-xl border border-border bg-card p-4">
          <div className="space-y-1"><Label>Leave type</Label>
            <select className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm" data-testid="me-leave-type-select"
                    value={form.leave_type_id} onChange={(e) => setForm({ ...form, leave_type_id: e.target.value })}>
              <option value="">Choose…</option>
              {(types ?? []).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.paid ? "paid" : "unpaid"})</option>)}
            </select>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div className="space-y-1"><Label>From</Label><Input type="date" data-testid="me-leave-from" value={form.from_date} onChange={(e) => setForm({ ...form, from_date: e.target.value })} /></div>
            <div className="space-y-1"><Label>To</Label><Input type="date" data-testid="me-leave-to" value={form.to_date} onChange={(e) => setForm({ ...form, to_date: e.target.value })} /></div>
            <div className="space-y-1"><Label>Days</Label><Input type="number" data-testid="me-leave-days" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} /></div>
          </div>
          <div className="space-y-1"><Label>Reason</Label><Input data-testid="me-leave-reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => apply.mutate()} disabled={apply.isPending || !form.leave_type_id || !form.from_date} data-testid="me-leave-submit">Submit</Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      ) : null}
      {(requests?.length ?? 0) > 0 ? (
        <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="me-leave-requests">
          {requests!.map((r) => (
            <li key={r.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <span>{r.leave_code} · {dateLabel(r.from_date)} → {dateLabel(r.to_date)} ({r.days}d)</span>
              <span className={`rounded-full border px-2 py-0.5 text-xs ${r.status === "approved" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : r.status === "rejected" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-800"}`}>{r.status}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function AttendanceTab() {
  const [period, setPeriod] = useState(currentPeriod());
  const { data } = useQuery({ queryKey: ["me-attendance", period], queryFn: () => apiGet<{ date: string; status: string; overtime_hours: number }[]>(`/v1/me/attendance?period=${period}`) });
  return (
    <div className="space-y-4">
      <Input type="month" className="w-44" data-testid="me-attendance-period" value={period} onChange={(e) => setPeriod(e.target.value)} />
      {(data?.length ?? 0) === 0 ? (
        <EmptyState icon={<Plane className="size-10" aria-hidden />} title="No attendance this month" testid="me-attendance-empty" />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="me-attendance-list">
          {data!.map((a, i) => (
            <li key={`${a.date}-${i}`} className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2 text-xs">
              <span>{dateLabel(a.date)}</span>
              <span className="flex items-center gap-2">
                <span className={`rounded-full border px-2 py-0.5 ${a.status === "present" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : a.status === "absent" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>{titleCase(a.status)}</span>
                {a.overtime_hours > 0 ? <span className="font-mono text-muted-foreground">+{a.overtime_hours}h OT</span> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProfileTab() {
  const { data, isPending } = useQuery({ queryKey: ["me-profile"], queryFn: () => apiGet<ProfilePayload>("/v1/me/profile") });
  if (isPending) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  const e = data?.employee;
  if (!e) return <EmptyState title="No employee record linked" testid="me-profile-empty" />;
  const rows: [string, string | null | undefined][] = [
    ["Employee ID", e.employee_code], ["Designation", e.designation], ["Department", e.department_name],
    ["Joining date", dateLabel(e.joining_date)], ["PAN", e.pan], ["UAN", e.uan],
    ["Tax regime", titleCase(e.tax_regime) + " regime"], ["Bank", e.bank_name],
    ["Account", e.bank_account], ["Phone", e.phone], ["Work email", e.work_email],
  ];
  return (
    <div className="grid max-w-2xl gap-3 sm:grid-cols-2" data-testid="me-profile-grid">
      {rows.map(([label, v]) => (
        <div key={label} className="rounded-lg border border-border bg-card px-4 py-3">
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
          <p className="mt-0.5 text-sm">{v || "—"}</p>
        </div>
      ))}
    </div>
  );
}

function MoreTab() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: docs } = useQuery({ queryKey: ["me-documents"], queryFn: () => apiGet<DocumentMeta[]>("/v1/me/documents") });
  const { data: reimbs } = useQuery({ queryKey: ["me-reimbursements"], queryFn: () => apiGet<Reimbursement[]>("/v1/me/reimbursements") });
  const { data: loans } = useQuery({ queryKey: ["me-loans"], queryFn: () => apiGet<Loan[]>("/v1/me/loans") });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("category", "personal");
      fd.append("file", file);
      return apiUpload("/v1/documents", fd);
    },
    onSuccess: () => { toast.success("Document uploaded"); queryClient.invalidateQueries({ queryKey: ["me-documents"] }); },
    onError: (err) => toast.error(String(err)),
  });

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold">My documents</h3>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-xs hover:bg-muted/50">
          {upload.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Upload className="size-3.5" aria-hidden />} Upload (max 5 MB)
          <input ref={fileRef} type="file" className="hidden" data-testid="me-document-upload" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }} />
        </label>
        <ul className="mt-3 space-y-1.5" data-testid="me-documents-list">
          {(docs ?? []).map((d) => (
            <li key={d.id} className="flex items-center justify-between text-xs">
              <span>{d.filename} · {(d.size / 1024).toFixed(0)} KB</span>
              <a href={`/api/v1/documents/${d.id}/download`} download className="text-blue-600 hover:underline dark:text-blue-400">Download</a>
            </li>
          ))}
          {(docs?.length ?? 0) === 0 ? <li className="text-xs text-muted-foreground">No documents yet.</li> : null}
        </ul>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold">My reimbursements</h3>
        <ul className="space-y-1.5 text-xs" data-testid="me-reimbursements-list">
          {(reimbs ?? []).map((r) => (
            <li key={r.id} className="flex items-center justify-between">
              <span>{titleCase(r.category)} · {dateLabel(r.date)}</span>
              <span className="font-mono tabular-nums">{inr(r.status === "pending" ? r.amount : r.approved_amount)} <span className="text-muted-foreground">({r.status})</span></span>
            </li>
          ))}
          {(reimbs?.length ?? 0) === 0 ? <li className="text-muted-foreground">No claims yet — raise them from the Reimbursements module or ask HR.</li> : null}
        </ul>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold">My loans & advances</h3>
        <ul className="space-y-1.5 text-xs" data-testid="me-loans-list">
          {(loans ?? []).map((l) => (
            <li key={l.id} className="flex items-center justify-between">
              <span>{l.name}</span>
              <span className="font-mono tabular-nums">EMI {inr(l.emi)} · outstanding {inr(l.outstanding)} <span className="text-muted-foreground">({l.status})</span></span>
            </li>
          ))}
          {(loans?.length ?? 0) === 0 ? <li className="text-muted-foreground">No active loans.</li> : null}
        </ul>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><FileDown className="size-4" aria-hidden /> Offline note</h3>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Sensitive payroll data is never cached insecurely on this device. When you're offline the app shows your last-synced screens with a clear offline banner and queues nothing sensitive.
        </p>
      </section>
    </div>
  );
}
