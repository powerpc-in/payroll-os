// Full & Final settlements: preview the computation, create a draft, approve, then settle
// (exit processing) and download the statement PDF. Every figure comes from the backend
// F&F engine — the UI never computes money.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Calculator, CheckCircle2, FileDown, Plus, Trash2, UserMinus } from "lucide-react";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import type { Employee, FFLine, FFSettlement } from "@/lib/types";
import { dateLabel, inr } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

interface FFForm {
  employee_id: string;
  last_working_day: string;
  exit_reason: string;
  notice_pay_days: string;
  notice_recovery_days: string;
  bonus: string;
  incentive: string;
  other_earnings: string;
  other_deductions: string;
  tax_adjustment: string;
  notes: string;
}

const EMPTY_FORM: FFForm = {
  employee_id: "", last_working_day: "", exit_reason: "", notice_pay_days: "0",
  notice_recovery_days: "0", bonus: "0", incentive: "0", other_earnings: "0",
  other_deductions: "0", tax_adjustment: "0", notes: "",
};

const num = (v: string) => Number(v || 0);

function payload(form: FFForm) {
  return {
    employee_id: form.employee_id,
    last_working_day: form.last_working_day,
    exit_reason: form.exit_reason || null,
    notice_pay_days: num(form.notice_pay_days),
    notice_recovery_days: num(form.notice_recovery_days),
    bonus: num(form.bonus),
    incentive: num(form.incentive),
    other_earnings: num(form.other_earnings),
    other_deductions: num(form.other_deductions),
    tax_adjustment: num(form.tax_adjustment),
    notes: form.notes || null,
  };
}

const STATUS_STYLES: Record<string, string> = {
  draft: "border-amber-200 bg-amber-50 text-amber-700",
  approved: "border-blue-200 bg-blue-50 text-blue-700",
  settled: "border-emerald-200 bg-emerald-50 text-emerald-700",
  preview: "border-slate-200 bg-slate-100 text-slate-600",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[status] ?? STATUS_STYLES.preview}`}>
      {status}
    </span>
  );
}

function LineTable({ title, lines, testid }: { title: string; lines: FFLine[]; testid: string }) {
  return (
    <div className="min-w-0" data-testid={testid}>
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
      {lines.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">None</p>
      ) : (
        <ul className="space-y-1.5">
          {lines.map((l) => (
            <li key={l.code} className="rounded-lg border border-border bg-card px-3 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-foreground">{l.name}</span>
                <span className="font-mono text-sm tabular-nums">{inr(l.amount, 2)}</span>
              </div>
              <p className="mt-0.5 font-mono text-[11px] leading-relaxed text-muted-foreground">
                {l.explanation?.calculation}
              </p>
              <p className="text-[11px] text-muted-foreground">{l.explanation?.rule}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Settlements() {
  const queryClient = useQueryClient();
  const session = useSession();
  const permissions = session.data?.permissions;
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FFForm>(EMPTY_FORM);
  const [preview, setPreview] = useState<FFSettlement | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data: settlements, isPending } = useQuery({
    queryKey: ["settlements"],
    queryFn: () => apiGet<FFSettlement[]>("/v1/settlements"),
  });
  const { data: employees } = useQuery({
    queryKey: ["employees", "active-for-ff"],
    queryFn: () => apiGet<{ items: Employee[] }>("/v1/employees?status=active&limit=100"),
    enabled: can(permissions, "ff.manage"),
  });

  const activeEmployees = useMemo(() => employees?.items ?? [], [employees]);
  const set = (patch: Partial<FFForm>) => setForm((f) => ({ ...f, ...patch }));

  const runPreview = useMutation({
    mutationFn: () => {
      const p = payload(form);
      const qs = new URLSearchParams({
        employee_id: p.employee_id, last_working_day: p.last_working_day,
        notice_pay_days: String(p.notice_pay_days), notice_recovery_days: String(p.notice_recovery_days),
        bonus: String(p.bonus), incentive: String(p.incentive),
        other_earnings: String(p.other_earnings), other_deductions: String(p.other_deductions),
        tax_adjustment: String(p.tax_adjustment),
      });
      return apiGet<FFSettlement>(`/v1/settlements/preview?${qs.toString()}`);
    },
    onSuccess: (res) => setPreview(res),
    onError: (err) => toast.error(String(err)),
  });

  const create = useMutation({
    mutationFn: () => apiPost<FFSettlement>("/v1/settlements", payload(form)),
    onSuccess: (res) => {
      toast.success(`Settlement drafted — net ${inr(res.net_settlement, 2)}`);
      queryClient.invalidateQueries({ queryKey: ["settlements"] });
      setOpen(false);
      setForm(EMPTY_FORM);
      setPreview(null);
      setExpanded(res.id);
    },
    onError: (err) => toast.error(String(err)),
  });

  const approve = useMutation({
    mutationFn: (id: string) => apiPost<FFSettlement>(`/v1/settlements/${id}/approve`, {}),
    onSuccess: () => { toast.success("Settlement approved"); queryClient.invalidateQueries({ queryKey: ["settlements"] }); },
    onError: (err) => toast.error(String(err)),
  });

  const settle = useMutation({
    mutationFn: (id: string) => apiPost<FFSettlement>(`/v1/settlements/${id}/settle`, { payment_reference: null }),
    onSuccess: () => {
      toast.success("Settled — employee exited, loans closed, reimbursements paid");
      queryClient.invalidateQueries({ queryKey: ["settlements"] });
      queryClient.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/settlements/${id}`),
    onSuccess: () => { toast.success("Draft deleted"); queryClient.invalidateQueries({ queryKey: ["settlements"] }); },
    onError: (err) => toast.error(String(err)),
  });

  const downloadStatement = async (ff: FFSettlement) => {
    const res = await fetch(`/api/v1/settlements/${ff.id}/statement`);
    if (!res.ok) { toast.error(`Statement failed (${res.status})`); return; }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `FF-${ff.employee_code ?? ff.employee_id.slice(0, 6)}-${ff.last_working_day}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const shown = preview;

  return (
    <div>
      <PageHeader
        title="Full & Final Settlement"
        description="Exit processing with salary payable, LOP, leave encashment, notice pay/recovery, loan recovery, gratuity and the final tax adjustment — every line explainable."
        testid="settlements-title"
        actions={can(permissions, "ff.manage") ? (
          <Dialog open={open} onOpenChange={(o: boolean) => { setOpen(o); if (!o) setPreview(null); }}>
            <DialogTrigger render={<Button data-testid="new-settlement-button"><Plus className="size-4" aria-hidden /> New settlement</Button>} />
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
              <DialogHeader><DialogTitle>Process an exit</DialogTitle></DialogHeader>
              <DialogDescription>
                Preview recomputes from live records (attendance, leave balances, loans, reimbursements,
                gratuity rules). Nothing is saved until you create the settlement.
              </DialogDescription>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1 sm:col-span-2">
                  <Label>Employee *</Label>
                  <Select value={form.employee_id} onValueChange={(v: string) => { set({ employee_id: v }); setPreview(null); }}>
                    <SelectTrigger data-testid="ff-employee-select">
                      <SelectValue>{(v: string) => activeEmployees.find((e) => e.id === v)?.name ?? "Select an employee"}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {activeEmployees.map((e) => (
                        <SelectItem key={e.id} value={e.id}>{e.employee_code} · {e.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>Last working day *</Label>
                  <Input type="date" data-testid="ff-lwd-input" value={form.last_working_day}
                         onChange={(e) => { set({ last_working_day: e.target.value }); setPreview(null); }} />
                </div>
                <div className="space-y-1">
                  <Label>Exit reason</Label>
                  <Input data-testid="ff-exit-reason-input" placeholder="Resignation" value={form.exit_reason}
                         onChange={(e) => set({ exit_reason: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Notice pay (days)</Label>
                  <Input type="number" data-testid="ff-notice-pay-input" value={form.notice_pay_days}
                         onChange={(e) => set({ notice_pay_days: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Notice shortfall recovery (days)</Label>
                  <Input type="number" data-testid="ff-notice-recovery-input" value={form.notice_recovery_days}
                         onChange={(e) => set({ notice_recovery_days: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Bonus</Label>
                  <Input type="number" data-testid="ff-bonus-input" value={form.bonus}
                         onChange={(e) => set({ bonus: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Incentive / commission</Label>
                  <Input type="number" data-testid="ff-incentive-input" value={form.incentive}
                         onChange={(e) => set({ incentive: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Other payable</Label>
                  <Input type="number" data-testid="ff-other-earnings-input" value={form.other_earnings}
                         onChange={(e) => set({ other_earnings: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label>Other deductions</Label>
                  <Input type="number" data-testid="ff-other-deductions-input" value={form.other_deductions}
                         onChange={(e) => set({ other_deductions: e.target.value })} />
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <Label>Tax / TDS adjustment on settlement</Label>
                  <Input type="number" data-testid="ff-tax-adjustment-input" value={form.tax_adjustment}
                         onChange={(e) => set({ tax_adjustment: e.target.value })} />
                  <p className="text-[11px] text-muted-foreground">
                    Entered by you — the engine never guesses a settlement tax figure. Requires statutory verification.
                  </p>
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <Label>Remarks</Label>
                  <Textarea data-testid="ff-notes-input" value={form.notes} onChange={(e) => set({ notes: e.target.value })} />
                </div>
              </div>

              {shown ? (
                <div className="mt-2 space-y-3 rounded-xl border border-border bg-muted/40 p-3" data-testid="ff-preview">
                  <div className="grid gap-3 md:grid-cols-2">
                    <LineTable title="Payable" lines={shown.payable} testid="ff-preview-payable" />
                    <LineTable title="Recoveries" lines={shown.recoveries} testid="ff-preview-recoveries" />
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-2 text-sm">
                    <span className="text-muted-foreground">
                      Payable {inr(shown.total_payable, 2)} − Recoveries {inr(shown.total_recoveries, 2)} − Tax {inr(shown.tax_adjustment, 2)}
                    </span>
                    <span className="font-mono text-base font-semibold tabular-nums" data-testid="ff-preview-net">
                      Net {inr(shown.net_settlement, 2)}
                    </span>
                  </div>
                  {shown.gratuity_note ? (
                    <p className="flex items-start gap-1.5 text-[11px] text-amber-700" data-testid="ff-preview-gratuity-note">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {shown.gratuity_note}
                    </p>
                  ) : null}
                  {(shown.computation_notes ?? []).map((n) => (
                    <p key={n} className="text-[11px] text-muted-foreground">• {n}</p>
                  ))}
                </div>
              ) : null}

              <DialogFooter>
                <Button variant="outline" data-testid="ff-preview-button"
                        disabled={!form.employee_id || !form.last_working_day || runPreview.isPending}
                        onClick={() => runPreview.mutate()}>
                  <Calculator className="size-4" aria-hidden /> Preview calculation
                </Button>
                <Button data-testid="ff-create-button"
                        disabled={!form.employee_id || !form.last_working_day || create.isPending}
                        onClick={() => create.mutate()}>Create settlement</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        ) : undefined}
      />

      {isPending ? <div className="h-40 animate-pulse rounded-xl bg-muted" />
        : (settlements?.length ?? 0) === 0 ? (
          <EmptyState icon={<UserMinus className="size-10" aria-hidden />} title="No settlements yet"
            description="Process an exit to compute a full & final settlement with a downloadable statement."
            testid="settlements-empty" />
        ) : (
          <ul className="space-y-3" data-testid="settlements-list">
            {settlements!.map((ff) => (
              <li key={ff.id} className="rounded-xl border border-border bg-card p-4" data-testid={`settlement-row-${ff.id.slice(0, 8)}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 font-medium text-foreground">
                      {ff.employee_name}
                      <span className="text-xs text-muted-foreground">{ff.employee_code}</span>
                      <StatusPill status={ff.status} />
                      {ff.computed_with_unverified_rules ? (
                        <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                          unverified rules
                        </span>
                      ) : null}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      LWD {dateLabel(ff.last_working_day)} · {ff.exit_reason || "reason not recorded"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-lg font-semibold tabular-nums" data-testid={`settlement-net-${ff.id.slice(0, 8)}`}>
                      {inr(ff.net_settlement, 2)}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      payable {inr(ff.total_payable, 2)} · recoveries {inr(ff.total_recoveries, 2)}
                    </p>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" data-testid={`settlement-view-${ff.id.slice(0, 8)}`}
                          onClick={() => setExpanded(expanded === ff.id ? null : ff.id)}>
                    {expanded === ff.id ? "Hide calculation" : "View calculation"}
                  </Button>
                  <Button size="sm" variant="outline" data-testid={`settlement-statement-${ff.id.slice(0, 8)}`}
                          onClick={() => downloadStatement(ff)}>
                    <FileDown className="size-3.5" aria-hidden /> Statement PDF
                  </Button>
                  {ff.status === "draft" && can(permissions, "payroll.approve") ? (
                    <Button size="sm" data-testid={`settlement-approve-${ff.id.slice(0, 8)}`}
                            disabled={approve.isPending} onClick={() => approve.mutate(ff.id)}>
                      <CheckCircle2 className="size-3.5" aria-hidden /> Approve
                    </Button>
                  ) : null}
                  {ff.status === "approved" && can(permissions, "payroll.lock") ? (
                    <Button size="sm" data-testid={`settlement-settle-${ff.id.slice(0, 8)}`}
                            disabled={settle.isPending} onClick={() => settle.mutate(ff.id)}>
                      <UserMinus className="size-3.5" aria-hidden /> Settle &amp; exit employee
                    </Button>
                  ) : null}
                  {ff.status === "draft" && can(permissions, "ff.manage") ? (
                    <Button size="sm" variant="ghost" aria-label="Delete draft"
                            data-testid={`settlement-delete-${ff.id.slice(0, 8)}`}
                            onClick={() => remove.mutate(ff.id)}><Trash2 className="size-4" aria-hidden /></Button>
                  ) : null}
                </div>

                {expanded === ff.id ? (
                  <div className="mt-3 space-y-3 border-t border-border pt-3" data-testid={`settlement-detail-${ff.id.slice(0, 8)}`}>
                    <div className="grid gap-3 md:grid-cols-2">
                      <LineTable title="Payable" lines={ff.payable} testid={`settlement-payable-${ff.id.slice(0, 8)}`} />
                      <LineTable title="Recoveries" lines={ff.recoveries} testid={`settlement-recoveries-${ff.id.slice(0, 8)}`} />
                    </div>
                    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs">
                      <p>Tax / TDS adjustment: <span className="font-mono">{inr(ff.tax_adjustment, 2)}</span></p>
                      <p className="mt-1 text-muted-foreground">{ff.tax_adjustment_note}</p>
                      {ff.gratuity_note ? <p className="mt-1 text-amber-700">{ff.gratuity_note}</p> : null}
                      {(ff.computation_notes ?? []).map((n) => <p key={n} className="mt-1 text-muted-foreground">• {n}</p>)}
                      {ff.notes ? <p className="mt-1 text-muted-foreground">Remarks: {ff.notes}</p> : null}
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
