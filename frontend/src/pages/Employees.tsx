// Employee master list + creation dialog with optional salary assignment.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, Users } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Employee, Jurisdiction, Paged, SalaryStructure } from "@/lib/types";
import { inr } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader } from "@/components/ui-kit";

const EMPTY_FORM = {
  name: "", work_email: "", phone: "", joining_date: "", designation: "",
  department_name: "", state: "KA", employment_type: "full_time",
  tax_regime: "new", pf_applicable: true, esi_applicable: true,
  gross_monthly: "",
};

export default function Employees() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const { data, isPending } = useQuery({
    queryKey: ["employees", page, q, status],
    queryFn: () => apiGet<Paged<Employee>>(
      `/v1/employees?page=${page}&limit=20${q ? `&q=${encodeURIComponent(q)}` : ""}${status ? `&status=${status}` : ""}`,
    ),
  });

  const { data: jurisdictions } = useQuery({
    queryKey: ["jurisdictions"],
    queryFn: () => apiGet<Jurisdiction[]>("/v1/jurisdictions"),
  });
  const states = jurisdictions?.find((j) => j.code === "IN")?.states ?? [];
  const { data: structures } = useQuery({
    queryKey: ["structures"],
    queryFn: () => apiGet<SalaryStructure[]>("/v1/salary/structures"),
    enabled: open,
  });

  const create = useMutation({
    mutationFn: async () => {
      const emp = await apiPost<Employee>("/v1/employees", {
        ...form,
        pf_applicable: form.pf_applicable,
        esi_applicable: form.esi_applicable,
      });
      const gross = Number(form.gross_monthly);
      if (gross > 0 && structures && structures.length > 0) {
        await apiPost("/v1/salary/assignments", {
          employee_id: emp.id, structure_id: structures[0].id,
          gross_monthly: gross, effective_from: form.joining_date,
        });
      } else if (gross > 0) {
        toast.warning("Employee created — no salary structure exists yet, so gross pay wasn't assigned");
      }
      return emp;
    },
    onSuccess: () => {
      toast.success("Employee created");
      queryClient.invalidateQueries({ queryKey: ["employees"] });
      setOpen(false);
      setForm(EMPTY_FORM);
    },
    onError: (err) => toast.error(String(err)),
  });

  const columns: Column<Employee>[] = [
    { key: "employee_code", label: "ID" },
    { key: "name", label: "Name", render: (row) => <span className="font-medium text-foreground">{row.name}</span> },
    { key: "designation", label: "Designation" },
    { key: "department_name", label: "Department" },
    { key: "state", label: "State" },
    { key: "gross_monthly", label: "Gross / month", numeric: true, render: (row) => (row.gross_monthly ? inr(row.gross_monthly) : "—") },
    {
      key: "status", label: "Status",
      render: (row) => (
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${row.status === "active" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-100 text-slate-600"}`}>
          {row.status}
        </span>
      ),
    },
  ];

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 20));

  return (
    <div>
      <PageHeader
        title="Employees"
        description={`${total} in this organisation · sensitive fields masked by default`}
        testid="employees-title"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="add-employee-button"><Plus className="size-4" aria-hidden /> Add employee</Button>} />
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
              <DialogHeader>
                <DialogTitle>Add employee</DialogTitle>
                <DialogDescription>Master record with statutory profile. Assign salary from the Salary module too if you set gross here.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1"><Label>Name *</Label><Input data-testid="new-employee-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
                <div className="space-y-1"><Label>Work email</Label><Input type="email" data-testid="new-employee-email" value={form.work_email} onChange={(e) => setForm({ ...form, work_email: e.target.value })} /></div>
                <div className="space-y-1"><Label>Phone</Label><Input data-testid="new-employee-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
                <div className="space-y-1"><Label>Joining date *</Label><Input type="date" data-testid="new-employee-doj" value={form.joining_date} onChange={(e) => setForm({ ...form, joining_date: e.target.value })} /></div>
                <div className="space-y-1"><Label>Department</Label><Input data-testid="new-employee-department" value={form.department_name} onChange={(e) => setForm({ ...form, department_name: e.target.value })} /></div>
                <div className="space-y-1"><Label>Designation</Label><Input data-testid="new-employee-designation" value={form.designation} onChange={(e) => setForm({ ...form, designation: e.target.value })} /></div>
                <div className="space-y-1"><Label>State</Label>
                  <Select value={form.state} onValueChange={(v: string) => setForm({ ...form, state: v })}>
                    <SelectTrigger data-testid="new-employee-state"><SelectValue>{(v: string) => states.find((s) => s.code === v)?.name ?? v}</SelectValue></SelectTrigger>
                    <SelectContent>{states.map((s) => <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>Tax regime</Label>
                  <Select value={form.tax_regime} onValueChange={(v: string) => setForm({ ...form, tax_regime: v })}>
                    <SelectTrigger data-testid="new-employee-regime"><SelectValue>{(v: string) => v === "new" ? "New regime" : "Old regime"}</SelectValue></SelectTrigger>
                    <SelectContent><SelectItem value="new">New regime</SelectItem><SelectItem value="old">Old regime</SelectItem></SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>Monthly gross (assigns default structure)</Label><Input type="number" data-testid="new-employee-gross" value={form.gross_monthly} onChange={(e) => setForm({ ...form, gross_monthly: e.target.value })} /></div>
                <div className="flex items-center gap-4 pt-5 sm:col-span-2">
                  <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.pf_applicable} onCheckedChange={(c) => setForm({ ...form, pf_applicable: Boolean(c) })} data-testid="new-employee-pf" /> PF applicable</label>
                  <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.esi_applicable} onCheckedChange={(c) => setForm({ ...form, esi_applicable: Boolean(c) })} data-testid="new-employee-esi" /> ESI applicable</label>
                </div>
              </div>
              <DialogFooter>
                <Button onClick={() => create.mutate()} disabled={create.isPending || !form.name || !form.joining_date} data-testid="new-employee-submit">
                  {create.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Create employee
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search name, code or email…" data-testid="employee-search-input"
          className="max-w-xs" value={q}
          onChange={(e) => { setQ(e.target.value); setPage(1); }}
        />
        <Select value={status} onValueChange={(v: string) => { setStatus(v); setPage(1); }}>
          <SelectTrigger className="w-36" data-testid="employee-status-filter"><SelectValue>{(v: string) => (v ? titleCase(v) : "All statuses")}</SelectValue></SelectTrigger>
          <SelectContent>
            <SelectItem value="">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="exited">Exited</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isPending ? (
        <div className="h-64 animate-pulse rounded-xl bg-muted" />
      ) : total === 0 ? (
        <EmptyState
          icon={<Users className="size-10" aria-hidden />}
          title="No employees yet"
          description="Add your first employee, or import a CSV from Data Import."
          testid="employees-empty"
        />
      ) : (
        <DataTable
          columns={columns} rows={data?.items ?? []} rowKey={(r) => r.id}
          testid="employees-table" onRowClick={(row) => navigate(`/app/employees/${row.id}`)}
        />
      )}

      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span data-testid="employees-page-info">Page {page} of {pages}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="employees-prev-page">Previous</Button>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)} data-testid="employees-next-page">Next</Button>
        </div>
      </div>
    </div>
  );
}

function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
