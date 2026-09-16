// Loans & advances: amortised schedules; EMIs are deducted automatically by the
// payroll engine while the loan is active.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { HandCoins, Loader2, Plus } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Employee, Loan, Paged } from "@/lib/types";
import { currentPeriod, inr, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";

export default function Loans() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Loan | null>(null);
  const [form, setForm] = useState({ employee_id: "", name: "Salary advance", principal: "", interest_rate: "0", tenure_months: "6", start_period: currentPeriod() });

  const { data, isPending } = useQuery({ queryKey: ["loans"], queryFn: () => apiGet<Loan[]>("/v1/loans") });
  const { data: employees } = useQuery({
    queryKey: ["employees", "loans-page"],
    queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100"),
    enabled: open && session.data?.role !== "EMPLOYEE",
  });

  const create = useMutation({
    mutationFn: () => apiPost("/v1/loans", {
      employee_id: form.employee_id, name: form.name, principal: Number(form.principal),
      interest_rate: Number(form.interest_rate), tenure_months: Number(form.tenure_months),
      start_period: form.start_period, deduct_from_payroll: true,
    }),
    onSuccess: () => { toast.success("Loan created with repayment schedule"); queryClient.invalidateQueries({ queryKey: ["loans"] }); setOpen(false); },
    onError: (err) => toast.error(String(err)),
  });

  const close = useMutation({
    mutationFn: (id: string) => apiPost(`/v1/loans/${id}/close`, {}),
    onSuccess: () => { toast.success("Loan closed"); queryClient.invalidateQueries({ queryKey: ["loans"] }); },
    onError: (err) => toast.error(String(err)),
  });

  const { data: detailData } = useQuery({
    queryKey: ["loan", detail?.id],
    queryFn: () => apiGet<Loan>(`/v1/loans/${detail!.id}`),
    enabled: !!detail,
  });

  const columns: Column<Loan>[] = [
    { key: "employee_name", label: "Employee", render: (r) => <span className="font-medium">{r.employee_name}</span> },
    { key: "name", label: "Loan" },
    { key: "principal", label: "Principal", numeric: true, render: (r) => inr(r.principal) },
    { key: "emi", label: "EMI", numeric: true, render: (r) => inr(r.emi) },
    { key: "outstanding", label: "Outstanding", numeric: true, render: (r) => inr(r.outstanding) },
    { key: "tenure_months", label: "Tenure", numeric: true },
    { key: "status", label: "Status", render: (r) => (
      <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${r.status === "active" ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>{r.status}</span>
    )},
    { key: "actions", label: "", render: (r) => (
      <span className="flex justify-end gap-1.5">
        <Button size="sm" variant="outline" data-testid={`loan-schedule-${r.id.slice(0, 8)}`} onClick={() => setDetail(r)}>Schedule</Button>
        {r.status === "active" && session.data?.role !== "EMPLOYEE" ? (
          <Button size="sm" variant="ghost" data-testid={`loan-close-${r.id.slice(0, 8)}`} onClick={() => close.mutate(r.id)}>Close</Button>
        ) : null}
      </span>
    )},
  ];

  return (
    <div>
      <PageHeader
        title="Loans & Advances"
        description="EMIs are scheduled deterministically and deducted by payroll while active."
        testid="loans-title"
        actions={session.data?.role !== "EMPLOYEE" ? (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="add-loan-button"><Plus className="size-4" aria-hidden /> New loan</Button>} />
            <DialogContent className="sm:max-w-md">
              <DialogHeader><DialogTitle>New loan / advance</DialogTitle></DialogHeader>
              <DialogDescription>Interest 0 = salary advance (straight-line principal).</DialogDescription>
              <div className="space-y-3">
                <div className="space-y-1"><Label>Employee *</Label>
                  <Select value={form.employee_id} onValueChange={(v: string) => setForm({ ...form, employee_id: v })}>
                    <SelectTrigger data-testid="loan-employee-select"><SelectValue>{(v: string) => employees?.items.find((e) => e.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
                    <SelectContent>{employees?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1"><Label>Label</Label><Input data-testid="loan-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
                  <div className="space-y-1"><Label>Principal *</Label><Input type="number" data-testid="loan-principal-input" value={form.principal} onChange={(e) => setForm({ ...form, principal: e.target.value })} /></div>
                  <div className="space-y-1"><Label>Interest % p.a.</Label><Input type="number" data-testid="loan-interest-input" value={form.interest_rate} onChange={(e) => setForm({ ...form, interest_rate: e.target.value })} /></div>
                  <div className="space-y-1"><Label>Tenure (months) *</Label><Input type="number" data-testid="loan-tenure-input" value={form.tenure_months} onChange={(e) => setForm({ ...form, tenure_months: e.target.value })} /></div>
                </div>
                <div className="space-y-1"><Label>First deduction month *</Label><Input type="month" data-testid="loan-start-input" value={form.start_period} onChange={(e) => setForm({ ...form, start_period: e.target.value })} /></div>
              </div>
              <DialogFooter><Button onClick={() => create.mutate()} disabled={create.isPending || !form.employee_id || !form.principal} data-testid="loan-save-button">Create loan</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        ) : undefined}
      />

      {isPending ? <div className="h-64 animate-pulse rounded-xl bg-muted" />
        : (data?.length ?? 0) === 0 ? (
          <EmptyState icon={<HandCoins className="size-10" aria-hidden />} title="No loans" description="Salary advances and loans with EMI schedules appear here." testid="loans-empty" />
        ) : (
          <DataTable columns={columns} rows={data ?? []} rowKey={(r) => r.id} testid="loans-table" />
        )}

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader><DialogTitle>{detail?.name} — repayment schedule</DialogTitle></DialogHeader>
          <p className="text-xs text-muted-foreground">Outstanding {inr(detailData?.outstanding ?? 0)} · EMI {inr(detailData?.emi ?? 0)} · {titleCase(detailData?.status ?? "")}</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-1.5">#</th><th>Period</th><th className="text-right">EMI</th>
                <th className="text-right">Principal</th><th className="text-right">Interest</th><th className="text-right">Balance</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {(detailData?.schedule ?? []).map((r) => (
                <tr key={r.n} className="border-b border-border/40">
                  <td className="py-1">{r.n}</td><td>{r.period}</td><td className="text-right">{inr(r.emi)}</td>
                  <td className="text-right">{inr(r.principal)}</td><td className="text-right">{inr(r.interest)}</td><td className="text-right">{inr(r.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </DialogContent>
      </Dialog>
    </div>
  );
}
