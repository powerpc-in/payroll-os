// Leave: types, balances, requests with the manager/HR approval flow.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Loader2, Plane, Plus, X } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Employee, LeaveBalance, LeaveRequest, LeaveType, Paged } from "@/lib/types";
import { currentPeriod, dateLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

export default function Leave() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ employee_id: "", leave_type_id: "", from_date: "", to_date: "", days: "1", reason: "" });
  const [balanceFor, setBalanceFor] = useState("");

  const isEmployeeRole = session.data?.role === "EMPLOYEE";

  const { data: types } = useQuery({ queryKey: ["leave-types"], queryFn: () => apiGet<LeaveType[]>("/v1/leave/types") });
  const { data: requests, isPending } = useQuery({ queryKey: ["leave-requests"], queryFn: () => apiGet<LeaveRequest[]>("/v1/leave/requests") });
  const { data: employees } = useQuery({
    queryKey: ["employees", "leave-page"],
    queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100"),
  });
  const { data: balances } = useQuery({
    queryKey: ["leave-balances", balanceFor],
    queryFn: () => apiGet<LeaveBalance[]>(`/v1/leave/balances?employee_id=${balanceFor}`),
    enabled: !!balanceFor,
  });

  const create = useMutation({
    mutationFn: () => apiPost("/v1/leave/requests", {
      employee_id: form.employee_id || undefined, leave_type_id: form.leave_type_id,
      from_date: form.from_date, to_date: form.to_date, days: Number(form.days), reason: form.reason,
    }),
    onSuccess: () => {
      toast.success("Leave request submitted");
      queryClient.invalidateQueries({ queryKey: ["leave-requests"] });
      setOpen(false);
    },
    onError: (err) => toast.error(String(err)),
  });

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      apiPost(`/v1/leave/requests/${id}/${approve ? "approve" : "reject"}`, {}),
    onSuccess: (_d, vars) => {
      toast.success(vars.approve ? "Leave approved — attendance updated" : "Leave rejected");
      queryClient.invalidateQueries({ queryKey: ["leave-requests"] });
      queryClient.invalidateQueries({ queryKey: ["leave-balances"] });
      queryClient.invalidateQueries({ queryKey: ["attendance-summary"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const columns: Column<LeaveRequest>[] = [
    { key: "employee_name", label: "Employee", render: (r) => <span className="font-medium">{r.employee_name}</span> },
    { key: "leave_code", label: "Type", render: (r) => <span>{r.leave_code} · {r.leave_name}</span> },
    { key: "from_date", label: "From", render: (r) => dateLabel(r.from_date) },
    { key: "to_date", label: "To", render: (r) => dateLabel(r.to_date) },
    { key: "days", label: "Days", numeric: true },
    { key: "paid", label: "Paid?", render: (r) => (r.paid ? "Paid" : "Unpaid (LOP)") },
    {
      key: "status", label: "Status",
      render: (r) => (
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${
          r.status === "approved" ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : r.status === "rejected" ? "border-red-200 bg-red-50 text-red-700"
          : "border-amber-200 bg-amber-50 text-amber-800"}`}>
          {r.status}
        </span>
      ),
    },
    {
      key: "actions", label: "", render: (r) =>
        r.status === "pending" && can(session.data?.permissions, "leave.approve") ? (
          <span className="flex justify-end gap-1.5">
            <Button size="sm" variant="outline" data-testid={`leave-approve-${r.id.slice(0, 8)}`} onClick={() => decide.mutate({ id: r.id, approve: true })}><Check className="size-4" aria-hidden /></Button>
            <Button size="sm" variant="ghost" data-testid={`leave-reject-${r.id.slice(0, 8)}`} onClick={() => decide.mutate({ id: r.id, approve: false })}><X className="size-4" aria-hidden /></Button>
          </span>
        ) : r.decided_by ? <span className="text-xs text-muted-foreground">by {r.decided_by}</span> : null,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Leave"
        description="Requests feed attendance on approval — paid leave keeps pay, unpaid becomes LOP."
        testid="leave-title"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="apply-leave-button"><Plus className="size-4" aria-hidden /> Apply leave</Button>} />
            <DialogContent className="sm:max-w-md">
              <DialogHeader><DialogTitle>Apply leave</DialogTitle></DialogHeader>
              <div className="space-y-3">
                {!isEmployeeRole ? (
                  <div className="space-y-1"><Label>Employee</Label>
                    <Select value={form.employee_id} onValueChange={(v: string) => setForm({ ...form, employee_id: v })}>
                      <SelectTrigger data-testid="leave-employee-select"><SelectValue>{(v: string) => employees?.items.find((e) => e.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
                      <SelectContent>{employees?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                ) : null}
                <div className="space-y-1"><Label>Leave type *</Label>
                  <Select value={form.leave_type_id} onValueChange={(v: string) => setForm({ ...form, leave_type_id: v })}>
                    <SelectTrigger data-testid="leave-type-select"><SelectValue>{(v: string) => types?.find((t) => t.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
                    <SelectContent>{types?.map((t) => <SelectItem key={t.id} value={t.id}>{t.name} ({t.annual_quota}d, {t.paid ? "paid" : "unpaid"})</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1"><Label>From *</Label><Input type="date" data-testid="leave-from-input" value={form.from_date} onChange={(e) => setForm({ ...form, from_date: e.target.value })} /></div>
                  <div className="space-y-1"><Label>To *</Label><Input type="date" data-testid="leave-to-input" value={form.to_date} onChange={(e) => setForm({ ...form, to_date: e.target.value })} /></div>
                  <div className="space-y-1"><Label>Days</Label><Input type="number" data-testid="leave-days-input" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} /></div>
                </div>
                <div className="space-y-1"><Label>Reason</Label><Textarea data-testid="leave-reason-input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} rows={2} /></div>
              </div>
              <DialogFooter><Button onClick={() => create.mutate()} disabled={create.isPending || !form.leave_type_id || !form.from_date} data-testid="leave-submit-button">Submit request</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div>
          {isPending ? <div className="h-64 animate-pulse rounded-xl bg-muted" /> : (requests?.length ?? 0) === 0 ? (
            <EmptyState icon={<Plane className="size-10" aria-hidden />} title="No leave requests" description="Applied leave and its approval status will appear here." testid="leave-empty" />
          ) : (
            <DataTable columns={columns} rows={requests ?? []} rowKey={(r) => r.id} testid="leave-requests-table" />
          )}
        </div>
        <div className="space-y-3 rounded-xl border border-border bg-card p-5">
          <h3 className="text-sm font-semibold">Balances</h3>
          <Select value={balanceFor} onValueChange={(v: string) => setBalanceFor(v)}>
            <SelectTrigger data-testid="leave-balance-employee-select"><SelectValue>{(v: string) => employees?.items.find((e) => e.id === v)?.name ?? "Pick an employee…"}</SelectValue></SelectTrigger>
            <SelectContent>{employees?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}</SelectContent>
          </Select>
          {balances?.map((b) => (
            <div key={b.id} className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2 text-sm">
              <span className="font-medium">{b.leave_code}</span>
              <span className="font-mono tabular-nums text-muted-foreground">{b.granted - b.used} / {b.granted} left</span>
            </div>
          ))}
          {!balanceFor ? <p className="text-xs text-muted-foreground">Select an employee to view balances.</p> : null}
        </div>
      </div>
    </div>
  );
}
