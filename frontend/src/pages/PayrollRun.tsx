// Payroll run detail: workflow actions, inputs, per-employee rows and the
// "View Calculation" explanation drawer (INPUT → RULE → FORMULA → CALCULATION).

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle2, FileDown, Loader2, Lock, Play, Plus, ShieldCheck, Trash2, Undo2 } from "lucide-react";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import type { Employee, PayrollRow, PayrollRun, Paged } from "@/lib/types";
import { inr, monthLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader, RunStatusBadge, VerificationBadge } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

function ExplanationLine({ line }: { line: { code: string; name: string; amount: number; explanation: { input: string; rule: string; calculation: string } } }) {
  return (
    <div className="rounded-lg border border-border/80 bg-muted/40 p-3" data-testid={`explanation-${line.code.toLowerCase()}`}>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{line.name}</span>
        <span className="font-mono tabular-nums">{inr(line.amount, 2)}</span>
      </div>
      <div className="mt-2 space-y-1 text-xs text-muted-foreground">
        <p><span className="font-semibold uppercase tracking-wider">Input:</span> {line.explanation.input}</p>
        <p><span className="font-semibold uppercase tracking-wider">Rule:</span> {line.explanation.rule}</p>
        <p className="rounded bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {line.explanation.calculation}
        </p>
      </div>
    </div>
  );
}

function CalculationDrawer({ runId, employeeId, employeeName, locked, testid }: {
  runId: string; employeeId: string; employeeName: string; locked: boolean; testid: string;
}) {
  const [open, setOpen] = useState(false);
  const { data, isPending } = useQuery({
    queryKey: ["run-employee", runId, employeeId],
    queryFn: () => apiGet<{ result: PayrollRow; inputs: Record<string, unknown>[] }>(`/v1/payroll/runs/${runId}/employees/${employeeId}`),
    enabled: open,
  });
  const row = data?.result;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<Button size="sm" variant="outline" data-testid={testid}>View calculation</Button>} />
      <SheetContent className="w-full overflow-y-auto sm:max-w-[580px]">
        <SheetHeader>
          <SheetTitle className="font-heading text-lg">Calculation — {employeeName}</SheetTitle>
        </SheetHeader>
        {isPending || !row ? (
          <div className="space-y-3 p-4">{[1, 2, 3].map((i) => <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />)}</div>
        ) : row.status === "error" ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" data-testid="calculation-error">
            <p className="font-semibold">Safe failure — no payroll computed</p>
            <p className="mt-1 text-xs">{row.error_reason}</p>
          </div>
        ) : (
          <div className="space-y-5 p-4">
            <div className="flex items-center gap-2 rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground" data-testid="calculation-attendance">
              <span>{monthLabel(row.period)} · {row.paid_days} paid / {row.total_days} days · LOP {row.lop_days}</span>
              {row.computed_with_unverified_rules ? <VerificationBadge verified={false} compact /> : null}
            </div>

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Earnings</h4>
              <div className="space-y-2">{row.earnings.map((line) => <ExplanationLine key={line.code + line.name} line={line} />)}</div>
              <div className="mt-2 flex justify-between border-t border-border pt-2 text-sm font-medium">
                <span>Gross earnings</span><span className="font-mono tabular-nums">{inr(row.gross_earnings, 2)}</span>
              </div>
            </section>

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Deductions</h4>
              <div className="space-y-2">{row.deductions.length > 0 ? row.deductions.map((line) => <ExplanationLine key={line.code + line.name} line={line} />) : <p className="text-sm text-muted-foreground">None</p>}</div>
              <div className="mt-2 flex justify-between border-t border-border pt-2 text-sm font-medium">
                <span>Total deductions</span><span className="font-mono tabular-nums">{inr(row.total_deductions, 2)}</span>
              </div>
            </section>

            {row.employer_contributions.length > 0 ? (
              <section>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Employer contributions (cost, not deducted)</h4>
                <div className="space-y-2">{row.employer_contributions.map((line) => <ExplanationLine key={line.code} line={line} />)}</div>
                <div className="mt-2 flex justify-between border-t border-border pt-2 text-sm font-medium">
                  <span>Employer cost</span><span className="font-mono tabular-nums">{inr(row.employer_cost, 2)}</span>
                </div>
              </section>
            ) : null}

            <section className="rounded-lg bg-[#0F172A] p-4 text-white">
              <div className="flex items-center justify-between">
                <span className="text-sm">Net pay</span>
                <span className="font-mono text-xl tabular-nums" data-testid="calculation-net-pay">{inr(row.net_pay, 2)}</span>
              </div>
            </section>

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Rule versions used (snapshot)</h4>
              <ul className="space-y-1.5" data-testid="calculation-rule-refs">
                {row.rule_refs.map((r) => (
                  <li key={r.id} className="flex items-center justify-between rounded border border-border/60 px-2.5 py-1.5 text-xs">
                    <span>{titleCase(r.rule_type.replace(/_/g, " "))} · v{r.version}</span>
                    <VerificationBadge verified={r.verified} compact />
                  </li>
                ))}
              </ul>
            </section>

            {locked ? (
              <a href={`/api/v1/payroll/payslips/${runId}/${employeeId}`} download data-testid="calculation-payslip-download">
                <Button className="w-full"><FileDown className="size-4" aria-hidden /> Download payslip PDF</Button>
              </a>
            ) : null}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default function PayrollRun() {
  const session = useSession();
  const queryClient = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [inputOpen, setInputOpen] = useState(false);
  const [inputForm, setInputForm] = useState({ employee_id: "", input_type: "bonus", amount: "", note: "", taxable: true });

  const { data, isPending } = useQuery({
    queryKey: ["run", id, page, q],
    queryFn: () => apiGet<{ run: PayrollRun; rows: PayrollRow[]; total: number }>(`/v1/payroll/runs/${id}?page=${page}&limit=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
    enabled: !!id,
  });
  const run = data?.run;

  const { data: employees } = useQuery({
    queryKey: ["employees", "run-inputs"],
    queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100"),
    enabled: inputOpen,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["run", id] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const action = useMutation({
    mutationFn: (step: string) => apiPost(`/v1/payroll/runs/${id}/${step}`, {}),
    onSuccess: (_d, step) => { toast.success(`${titleCase(step.replace("-", " "))} done`); invalidate(); },
    onError: (err) => toast.error(String(err)),
  });

  const addInput = useMutation({
    mutationFn: () => apiPost(`/v1/payroll/runs/${id}/inputs`, {
      employee_id: inputForm.employee_id, input_type: inputForm.input_type,
      amount: Number(inputForm.amount), note: inputForm.note, taxable: inputForm.taxable,
    }),
    onSuccess: () => {
      toast.success("Input added — recalculate to apply");
      setInputOpen(false);
      queryClient.invalidateQueries({ queryKey: ["run", id] });
    },
    onError: (err) => toast.error(String(err)),
  });

  if (isPending) return <div className="h-96 animate-pulse rounded-xl bg-muted" />;
  if (!run) return <EmptyState title="Run not found" description="It may belong to another organisation." testid="run-not-found" />;

  const totals = run.totals;
  const status = run.status;
  const canCalc = can(session.data?.permissions, "payroll.calculate");
  const rows = data?.rows ?? [];

  const columns: Column<PayrollRow>[] = [
    { key: "name", label: "Employee", render: (r) => (
      <span className="font-medium text-foreground">{r.employee_snapshot.name}</span>
    )},
    { key: "employee_code", label: "ID", render: (r) => r.employee_snapshot.employee_code ?? "—" },
    { key: "paid_days", label: "Paid / total", render: (r) => `${r.paid_days} / ${r.total_days}` },
    { key: "gross_earnings", label: "Gross", numeric: true, render: (r) => inr(r.gross_earnings) },
    { key: "tds", label: "TDS", numeric: true, render: (r) => (r.status === "ok" ? inr(r.tds_amount) : "—") },
    { key: "total_deductions", label: "Deductions", numeric: true, render: (r) => (r.status === "ok" ? inr(r.total_deductions) : "—") },
    { key: "net_pay", label: "Net pay", numeric: true, render: (r) => (r.status === "ok" ? <span className="font-semibold">{inr(r.net_pay)}</span> : "—") },
    { key: "status", label: "Status", render: (r) => r.status === "ok"
      ? <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">ok</span>
      : <span className="inline-flex rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-700" title={r.error_reason ?? ""}>error</span> },
    { key: "calc", label: "", render: (r) => (
      <div className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
        <CalculationDrawer runId={run.id} employeeId={r.employee_id} employeeName={r.employee_snapshot.name}
                           locked={status === "locked"} testid={`view-calculation-${r.employee_id.slice(0, 8)}`} />
        {status === "locked" && r.status === "ok" ? (
          <a href={`/api/v1/payroll/payslips/${run.id}/${r.employee_id}`} download data-testid={`payslip-download-${r.employee_id.slice(0, 8)}`}>
            <Button size="sm" variant="ghost" aria-label="Download payslip"><FileDown className="size-4" aria-hidden /></Button>
          </a>
        ) : null}
      </div>
    )},
  ];

  const errorRows = rows.filter((r) => r.status === "error");

  return (
    <div>
      <PageHeader
        title={`Payroll — ${monthLabel(run.period)}`}
        description={`Created by ${run.created_by ?? "—"} · jurisdiction ${run.jurisdiction}`}
        testid="payroll-run-title"
        actions={
          <>
            <Link to="/app/payroll"><Button variant="ghost" data-testid="run-back-button"><ArrowLeft className="size-4" aria-hidden /> All runs</Button></Link>
            {status === "draft" || status === "calculated" || status === "review" ? (
              <>
                {canCalc ? <Button variant="outline" data-testid="add-input-button" onClick={() => setInputOpen(true)}><Plus className="size-4" aria-hidden /> Add input</Button> : null}
                {canCalc ? (
                  <Button data-testid="calculate-button" onClick={() => action.mutate("calculate")} disabled={action.isPending}>
                    {action.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />} Calculate
                  </Button>
                ) : null}
              </>
            ) : null}
            {status === "calculated" && can(session.data?.permissions, "payroll.review") ? (
              <Button data-testid="submit-review-button" onClick={() => action.mutate("submit-review")} disabled={action.isPending}>Submit for review</Button>
            ) : null}
            {status === "review" && can(session.data?.permissions, "payroll.approve") ? (
              <Button data-testid="approve-button" onClick={() => action.mutate("approve")} disabled={action.isPending}><CheckCircle2 className="size-4" aria-hidden /> Approve</Button>
            ) : null}
            {status === "approved" && can(session.data?.permissions, "payroll.lock") ? (
              <Button data-testid="lock-button" onClick={() => action.mutate("lock")} disabled={action.isPending}><Lock className="size-4" aria-hidden /> Lock & generate payslips</Button>
            ) : null}
            {can(session.data?.permissions, "payroll.reverse") && ["calculated", "review", "approved"].includes(status) ? (
              <Button variant="ghost" data-testid="reverse-button" onClick={() => action.mutate("reverse")} disabled={action.isPending}><Undo2 className="size-4" aria-hidden /> Reverse</Button>
            ) : null}
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <div className="rounded-xl border border-border bg-card p-4" data-testid="run-status-card">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">State</p>
          <div className="mt-1.5"><RunStatusBadge status={status} /></div>
        </div>
        {[
          ["Employees", totals.headcount, "run-tot-headcount"],
          ["Gross", inr(totals.gross), "run-tot-gross"],
          ["Deductions", inr(totals.deductions), "run-tot-deductions"],
          ["Net payroll", inr(totals.net), "run-tot-net"],
          ["Employer cost", inr(totals.employer_cost), "run-tot-employer"],
        ].map(([label, value, tid]) => (
          <div key={String(tid)} className="rounded-xl border border-border bg-card p-4" data-testid={String(tid)}>
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
            <p className="mt-1.5 font-mono text-lg tabular-nums text-foreground">{value}</p>
          </div>
        ))}
      </div>

      {errorRows.length > 0 ? (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300" data-testid="run-errors-panel">
          <p className="font-semibold">{totals.errors} employee(s) failed safely (no guessed numbers):</p>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {errorRows.map((r) => <li key={r.employee_id}>{r.employee_snapshot.name}: {r.error_reason}</li>)}
          </ul>
        </div>
      ) : null}

      {run.rule_refs && run.rule_refs.some((r) => !r.verified) ? (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300" data-testid="run-unverified-strip">
          <ShieldCheck className="size-4" aria-hidden /> This run computed with rule versions marked "Requires statutory verification" — values are indicative only.
        </div>
      ) : null}

      <div className="mb-4">
        <Input placeholder="Search employee…" data-testid="run-search-input" className="max-w-xs" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>

      <DataTable columns={columns} rows={rows} rowKey={(r) => r.employee_id} testid="run-rows-table" />

      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span>Page {page} of {Math.max(1, Math.ceil((data?.total ?? 0) / 25))}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="run-prev-page">Previous</Button>
          <Button variant="outline" size="sm" disabled={page >= Math.max(1, Math.ceil((data?.total ?? 0) / 25))} onClick={() => setPage(page + 1)} data-testid="run-next-page">Next</Button>
        </div>
      </div>

      <AddInputDialog open={inputOpen} onOpenChange={setInputOpen} form={inputForm} setForm={setInputForm}
                      employees={employees?.items ?? []} onSave={() => addInput.mutate()} saving={addInput.isPending} />
    </div>
  );
}

function AddInputDialog({ open, onOpenChange, form, setForm, employees, onSave, saving }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  form: { employee_id: string; input_type: string; amount: string; note: string; taxable: boolean };
  setForm: (f: { employee_id: string; input_type: string; amount: string; note: string; taxable: boolean }) => void;
  employees: Employee[];
  onSave: () => void;
  saving: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Add payroll input</DialogTitle></DialogHeader>
        <DialogDescription>Bonus, overtime, arrears or adjustments — applied on the next calculation.</DialogDescription>
        <div className="space-y-3">
          <div className="space-y-1"><Label>Employee *</Label>
            <Select value={form.employee_id} onValueChange={(v: string) => setForm({ ...form, employee_id: v })}>
              <SelectTrigger data-testid="input-employee-select"><SelectValue>{(v: string) => employees.find((e) => e.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
              <SelectContent>{employees.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1"><Label>Type</Label>
              <Select value={form.input_type} onValueChange={(v: string) => setForm({ ...form, input_type: v })}>
                <SelectTrigger data-testid="input-type-select"><SelectValue>{(v: string) => titleCase(v)}</SelectValue></SelectTrigger>
                <SelectContent>
                  <SelectItem value="bonus">Bonus</SelectItem><SelectItem value="overtime">Overtime</SelectItem>
                  <SelectItem value="arrear">Arrear</SelectItem><SelectItem value="adjustment">Adjustment</SelectItem>
                  <SelectItem value="deduction">Deduction</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Amount *</Label><Input type="number" data-testid="input-amount-input" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></div>
          </div>
          <div className="space-y-1"><Label>Note</Label><Input data-testid="input-note-input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></div>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.taxable} onCheckedChange={(c) => setForm({ ...form, taxable: Boolean(c) })} data-testid="input-taxable-checkbox" /> Taxable</label>
        </div>
        <DialogFooter><Button onClick={onSave} disabled={saving || !form.employee_id || !form.amount} data-testid="input-save-button">Add input</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
