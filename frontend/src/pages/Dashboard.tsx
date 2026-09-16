// Role-aware dashboard: admins get payroll operations bento + charts; employees
// get their own pay, leave and payslip panel. All figures are live aggregates.

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowRight, Banknote, CalendarClock, Download, ShieldCheck, Users } from "lucide-react";
import { apiGet } from "@/lib/api";
import type { DashboardData } from "@/lib/types";
import { inr, monthLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunStatusBadge, StatCard, VerificationBadge, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";

const compactInr = (v: number) =>
  v >= 100000 ? `${(v / 100000).toFixed(1)}L` : v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v);

export default function Dashboard() {
  const session = useSession();
  const { data, isPending } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiGet<DashboardData>("/v1/dashboards"),
    refetchOnWindowFocus: false,
  });

  if (isPending) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-64 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-28 animate-pulse rounded-xl bg-muted" />)}
        </div>
      </div>
    );
  }

  if (data?.employee) {
    const e = data.employee;
    const latest = e.latest_payslip;
    return (
      <div className="space-y-6">
        <PageHeader
          title={`Hello, ${data.employee.profile?.name?.split(" ")[0] ?? "there"}`}
          description={`${data.org?.name ?? ""} · ${monthLabel(data.period)}`}
          testid="dashboard-title"
        />
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Latest net pay" value={latest ? inr(latest.net_pay) : "—"} sub={latest ? monthLabel(latest.period) : "No payroll yet"} testid="stat-net-pay" />
          <StatCard label="YTD gross" value={inr(e.ytd.gross)} testid="stat-ytd-gross" />
          <StatCard label="YTD TDS" value={inr(e.ytd.tds)} testid="stat-ytd-tds" />
          <StatCard label="YTD PF (employee)" value={inr(e.ytd.pf)} testid="stat-ytd-pf" />
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="text-base">Latest payslip</CardTitle></CardHeader>
            <CardContent>
              {latest && e.payslip_ready ? (
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{monthLabel(latest.period)}</p>
                    <p className="font-mono text-xs tabular-nums text-muted-foreground">
                      Gross {inr(latest.gross_earnings)} · Net {inr(latest.net_pay)}
                    </p>
                  </div>
                  <a href={`/api/v1/me/payslips/${latest.run_id}`} download data-testid="dashboard-payslip-download">
                    <Button size="sm" variant="outline"><Download className="size-4" aria-hidden /> PDF</Button>
                  </a>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Your payslip appears here once the current run is locked.</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Leave balances</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {e.leave_balances.length === 0 ? (
                <p className="text-sm text-muted-foreground">No leave configured yet.</p>
              ) : e.leave_balances.map((b) => (
                <span key={b.id} data-testid={`leave-balance-${b.leave_code}`} className="rounded-lg border border-border bg-muted/50 px-3 py-1.5 text-xs">
                  <span className="font-medium">{b.leave_code}</span> · {Math.max(0, b.granted - b.used)} left
                </span>
              ))}
            </CardContent>
          </Card>
        </div>
        <Link to="/me" data-testid="dashboard-selfservice-link" className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400">
          Open my workspace <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    );
  }

  const run = data?.latest_run;
  const totals = run?.totals;
  const trends = data?.trends ?? [];
  const deptCost = data?.dept_cost ?? [];
  const alerts = data?.compliance_alerts;
  const role = data?.role ?? session.data?.role ?? "";

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${titleCase(role.replace("_", " ").toLowerCase())} dashboard`}
        description={`${data?.org?.name ?? ""} · payroll operations for ${monthLabel(data?.period ?? "")}`}
        testid="dashboard-title"
      />

      {alerts && alerts.unverified_rules > 0 ? (
        <div data-testid="compliance-alert-strip" className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
          <AlertTriangle className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">{alerts.unverified_rules} statutory rule version(s) are marked "Requires statutory verification".</span>
          <VerificationBadge verified={false} compact />
          <Link to="/app/compliance" className="text-xs font-medium underline">Review rules</Link>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Active employees" value={data?.headcount ?? 0} sub={`${data?.new_joiners ?? 0} joined this month`} testid="stat-headcount" />
        <StatCard label="Payroll cost (latest run)" value={inr(totals?.gross ?? 0)} sub={run ? `${monthLabel(run.period)} · ${totals?.headcount ?? 0} employees` : "No run yet"} testid="stat-payroll-cost" />
        <StatCard label="Net payroll" value={inr(totals?.net ?? 0)} sub={run ? monthLabel(run.period) : ""} testid="stat-net-payroll" />
        <StatCard label="Employer cost" value={inr(totals?.employer_cost ?? 0)} sub="Gross + contributions" testid="stat-employer-cost" />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">Payroll trend</CardTitle>
            <Link to="/app/payroll" className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400">All runs</Link>
          </CardHeader>
          <CardContent>
            {trends.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={trends} margin={{ left: 8, right: 8, top: 8 }}>
                  <defs>
                    <linearGradient id="gGross" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#2563EB" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#2563EB" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => compactInr(v)} width={48} />
                  <Tooltip formatter={(value: number, name: string) => [inr(value), titleCase(name)]} />
                  <Area dataKey="gross" name="gross" stroke="#2563EB" strokeWidth={2} fill="url(#gGross)" />
                  <Area dataKey="net" name="net pay" stroke="#10B981" strokeWidth={2} fill="transparent" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-10 text-center text-sm text-muted-foreground">Run payroll to see the trend.</p>
            )}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader><CardTitle className="text-base">Current run</CardTitle></CardHeader>
            <CardContent>
              {run ? (
                <div className="space-y-3" data-testid="current-run-card">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">{monthLabel(run.period)}</p>
                    <RunStatusBadge status={run.status} />
                  </div>
                  <p className="font-mono text-xs tabular-nums text-muted-foreground">
                    {totals?.headcount ?? 0} employees · {totals?.errors ?? 0} error(s)
                  </p>
                  {run.status !== "locked" ? (
                    <Link to={`/app/payroll/${run.id}`}>
                      <Button size="sm" className="w-full" data-testid="current-run-open-button">Open run <ArrowRight className="size-4" aria-hidden /></Button>
                    </Link>
                  ) : (
                    <p className="text-xs text-muted-foreground">Locked — payslips available to employees.</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No payroll run yet — create one from Payroll Runs.</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Pending approvals</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm" data-testid="pending-approvals-card">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-muted-foreground"><CalendarClock className="size-4" aria-hidden /> Leave requests</span>
                <span className="font-mono tabular-nums">{data?.pending?.leave ?? 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-muted-foreground"><Banknote className="size-4" aria-hidden /> Reimbursements</span>
                <span className="font-mono tabular-nums">{data?.pending?.reimbursements ?? 0}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Department cost ({run ? monthLabel(run.period) : "—"})</CardTitle></CardHeader>
          <CardContent>
            {deptCost.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={deptCost} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => compactInr(v)} />
                  <YAxis type="category" dataKey="department" tick={{ fontSize: 11 }} width={96} />
                  <Tooltip formatter={(value: number) => inr(value)} />
                  <Bar dataKey="gross" fill="#2563EB" radius={[0, 4, 4, 0]} barSize={16} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-8 text-center text-sm text-muted-foreground">No payroll rows yet.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Salary distribution</CardTitle></CardHeader>
          <CardContent>
            <DistributionChart />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function DistributionChart() {
  const { data } = useQuery({
    queryKey: ["analytics"],
    queryFn: () => apiGet<Record<string, unknown>>("/v1/analytics"),
    refetchOnWindowFocus: false,
  });
  const buckets = (data?.salary_distribution as { band: string; employees: number }[]) ?? [];
  if (buckets.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">Assign salaries to see the distribution.</p>;
  }
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={buckets}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="band" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} allowDecimals={false} width={32} />
        <Tooltip formatter={(value: number) => [`${value} employees`, ""]} />
        <Bar dataKey="employees" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
