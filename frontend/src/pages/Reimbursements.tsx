// Reimbursements: claims with taxability; approved taxable/non-taxable amounts
// flow into the next payroll run automatically.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Loader2, Plus, Receipt, X } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Employee, Paged, Reimbursement } from "@/lib/types";
import { dateLabel, inr, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

const CATEGORIES = ["travel", "fuel", "telephone", "internet", "food", "medical", "books", "relocation", "other"];

export default function Reimbursements() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ employee_id: "", category: "travel", amount: "", date: "", description: "", taxable: false });
  const [approveId, setApproveId] = useState<string | null>(null);
  const [approvedAmount, setApprovedAmount] = useState("");

  const isEmployeeRole = session.data?.role === "EMPLOYEE";
  const { data, isPending } = useQuery({ queryKey: ["reimbursements"], queryFn: () => apiGet<Reimbursement[]>("/v1/reimbursements") });
  const { data: employees } = useQuery({
    queryKey: ["employees", "reimb-page"],
    queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100"),
    enabled: !isEmployeeRole,
  });

  const create = useMutation({
    mutationFn: () => apiPost("/v1/reimbursements", {
      employee_id: form.employee_id || undefined, category: form.category,
      amount: Number(form.amount), date: form.date, description: form.description, taxable: form.taxable,
    }),
    onSuccess: () => { toast.success("Claim submitted"); queryClient.invalidateQueries({ queryKey: ["reimbursements"] }); setOpen(false); },
    onError: (err) => toast.error(String(err)),
  });

  const approve = useMutation({
    mutationFn: () => apiPost(`/v1/reimbursements/${approveId}/approve`, { approved_amount: Number(approvedAmount) }),
    onSuccess: () => { toast.success("Approved — lands in the next payroll run"); queryClient.invalidateQueries({ queryKey: ["reimbursements"] }); setApproveId(null); },
    onError: (err) => toast.error(String(err)),
  });

  const reject = useMutation({
    mutationFn: (id: string) => apiPost(`/v1/reimbursements/${id}/reject`, {}),
    onSuccess: () => { toast.success("Claim rejected"); queryClient.invalidateQueries({ queryKey: ["reimbursements"] }); },
    onError: (err) => toast.error(String(err)),
  });

  const columns: Column<Reimbursement>[] = [
    { key: "employee_name", label: "Employee", render: (r) => <span className="font-medium">{r.employee_name}</span> },
    { key: "category", label: "Category", render: (r) => titleCase(r.category) },
    { key: "amount", label: "Claimed", numeric: true, render: (r) => inr(r.amount) },
    { key: "approved_amount", label: "Approved", numeric: true, render: (r) => (r.status === "pending" ? "—" : inr(r.approved_amount)) },
    { key: "taxable", label: "Taxable", render: (r) => (r.taxable ? "Yes" : "No") },
    { key: "date", label: "Date", render: (r) => dateLabel(r.date) },
    { key: "status", label: "Status", render: (r) => (
      <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${
        r.status === "approved" || r.status === "paid" ? "border-emerald-200 bg-emerald-50 text-emerald-700"
        : r.status === "rejected" ? "border-red-200 bg-red-50 text-red-700"
        : "border-amber-200 bg-amber-50 text-amber-800"}`}>{r.status}</span>
    )},
    { key: "actions", label: "", render: (r) =>
      r.status === "pending" && can(session.data?.permissions, "reimbursements.approve") ? (
        <span className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" data-testid={`reimb-approve-${r.id.slice(0, 8)}`} onClick={() => { setApproveId(r.id); setApprovedAmount(String(r.amount)); }}>Review</Button>
          <Button size="sm" variant="ghost" data-testid={`reimb-reject-${r.id.slice(0, 8)}`} onClick={() => reject.mutate(r.id)}><X className="size-4" aria-hidden /></Button>
        </span>
      ) : null },
  ];

  return (
    <div>
      <PageHeader
        title="Reimbursements"
        description="Approved claims are paid through the next payroll run (taxable ones join gross)."
        testid="reimbursements-title"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="add-reimbursement-button"><Plus className="size-4" aria-hidden /> New claim</Button>} />
            <DialogContent className="sm:max-w-md">
              <DialogHeader><DialogTitle>New reimbursement claim</DialogTitle></DialogHeader>
              <div className="space-y-3">
                {!isEmployeeRole ? (
                  <div className="space-y-1"><Label>Employee</Label>
                    <Select value={form.employee_id} onValueChange={(v: string) => setForm({ ...form, employee_id: v })}>
                      <SelectTrigger data-testid="reimb-employee-select"><SelectValue>{(v: string) => employees?.items.find((e) => e.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
                      <SelectContent>{employees?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                ) : null}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1"><Label>Category</Label>
                    <Select value={form.category} onValueChange={(v: string) => setForm({ ...form, category: v })}>
                      <SelectTrigger data-testid="reimb-category-select"><SelectValue>{(v: string) => titleCase(v)}</SelectValue></SelectTrigger>
                      <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c} value={c}>{titleCase(c)}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1"><Label>Amount *</Label><Input type="number" data-testid="reimb-amount-input" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></div>
                  <div className="space-y-1"><Label>Date *</Label><Input type="date" data-testid="reimb-date-input" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></div>
                  <label className="flex items-center gap-2 pt-6 text-sm"><Checkbox checked={form.taxable} onCheckedChange={(c) => setForm({ ...form, taxable: Boolean(c) })} data-testid="reimb-taxable-checkbox" /> Taxable</label>
                </div>
                <div className="space-y-1"><Label>Description</Label><Input data-testid="reimb-description-input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
              </div>
              <DialogFooter><Button onClick={() => create.mutate()} disabled={create.isPending || !form.amount || !form.date} data-testid="reimb-submit-button">Submit claim</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      {isPending ? <div className="h-64 animate-pulse rounded-xl bg-muted" />
        : (data?.length ?? 0) === 0 ? (
          <EmptyState icon={<Receipt className="size-10" aria-hidden />} title="No claims yet" description="Employees and HR can raise reimbursement claims here." testid="reimbursements-empty" />
        ) : (
          <DataTable columns={columns} rows={data ?? []} rowKey={(r) => r.id} testid="reimbursements-table" />
        )}

      <Dialog open={!!approveId} onOpenChange={(o) => !o && setApproveId(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle>Approve claim</DialogTitle></DialogHeader>
          <div className="space-y-1"><Label>Approved amount</Label><Input type="number" data-testid="reimb-approved-amount-input" value={approvedAmount} onChange={(e) => setApprovedAmount(e.target.value)} /></div>
          <DialogFooter>
            <Button onClick={() => approve.mutate()} disabled={approve.isPending} data-testid="reimb-approve-confirm"><Check className="size-4" aria-hidden /> Approve</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
