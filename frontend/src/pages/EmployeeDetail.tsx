// Employee detail: profile tabs, edit, documents, salary assignments, exit flow.

import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, Loader2, Pencil, Trash2, Upload } from "lucide-react";
import { apiDelete, apiGet, apiPost, apiPut, apiUpload } from "@/lib/api";
import type { DocumentMeta, Employee, SalaryAssignment, SalaryStructure } from "@/lib/types";
import { dateLabel, inr, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

function Field({ label, value, testid }: { label: string; value: React.ReactNode; testid: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm text-foreground" data-testid={testid}>{value || "—"}</p>
    </div>
  );
}

export default function EmployeeDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const session = useSession();
  const [editOpen, setEditOpen] = useState(false);
  const [exitOpen, setExitOpen] = useState(false);
  const [exitDate, setExitDate] = useState("");
  const [exitReason, setExitReason] = useState("");

  const { data, isPending } = useQuery({
    queryKey: ["employee", id],
    queryFn: () => apiGet<{ employee: Employee; assignments: SalaryAssignment[]; structures: SalaryStructure[] }>(`/v1/employees/${id}?reveal=true`),
    enabled: !!id,
  });
  const emp = data?.employee;

  const { data: docs } = useQuery({
    queryKey: ["documents", id],
    queryFn: () => apiGet<DocumentMeta[]>(`/v1/documents?employee_id=${id}`),
    enabled: !!id && can(session.data?.permissions, "documents.view"),
  });

  const [form, setForm] = useState<Record<string, string>>({});
  const openEdit = () => {
    if (!emp) return;
    setForm({
      name: emp.name, work_email: emp.work_email ?? "", phone: emp.phone ?? "",
      date_of_birth: emp.date_of_birth ?? "", gender: emp.gender ?? "", marital_status: emp.marital_status ?? "",
      personal_email: emp.personal_email ?? "", address: emp.address ?? "", city: emp.city ?? "",
      state: emp.state ?? "", pin: emp.pin ?? "", joining_date: emp.joining_date,
      designation: emp.designation ?? "", department_name: emp.department_name ?? "",
      grade: emp.grade ?? "", location_name: emp.location_name ?? "", cost_centre: emp.cost_centre ?? "",
      pan: emp.pan ?? "", uan: emp.uan ?? "", pf_number: emp.pf_number ?? "", esi_number: emp.esi_number ?? "",
      tax_regime: emp.tax_regime, bank_name: emp.bank_name ?? "", bank_account: emp.bank_account ?? "",
      ifsc: emp.ifsc ?? "", account_holder: emp.account_holder ?? "",
      emergency_contact_name: emp.emergency_contact_name ?? "", emergency_contact_phone: emp.emergency_contact_phone ?? "",
    });
    setEditOpen(true);
  };

  const save = useMutation({
    mutationFn: () => apiPut(`/v1/employees/${id}`, {
      ...emp,
      ...form,
      pf_applicable: emp!.pf_applicable, esi_applicable: emp!.esi_applicable,
      pt_applicable: emp!.pt_applicable, lwf_applicable: emp!.lwf_applicable,
      joining_date: form.joining_date || emp!.joining_date,
      pf_number: form.pf_number, uan: form.uan,
    }),
    onSuccess: () => {
      toast.success("Employee updated");
      queryClient.invalidateQueries({ queryKey: ["employee", id] });
      queryClient.invalidateQueries({ queryKey: ["employees"] });
      setEditOpen(false);
    },
    onError: (err) => toast.error(String(err)),
  });

  const exit = useMutation({
    mutationFn: () => apiPost(`/v1/employees/${id}/exit`, { exit_date: exitDate, exit_reason: exitReason }),
    onSuccess: () => {
      toast.success("Employee marked as exited");
      queryClient.invalidateQueries({ queryKey: ["employee", id] });
      setExitOpen(false);
    },
    onError: (err) => toast.error(String(err)),
  });

  const remove = useMutation({
    mutationFn: () => apiDelete(`/v1/employees/${id}`),
    onSuccess: () => {
      toast.success("Employee deleted");
      queryClient.invalidateQueries({ queryKey: ["employees"] });
      navigate("/app/employees");
    },
    onError: (err) => toast.error(String(err)),
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("employee_id", id!);
      fd.append("category", "employee_document");
      fd.append("file", file);
      return apiUpload("/v1/documents", fd);
    },
    onSuccess: () => {
      toast.success("Document uploaded");
      queryClient.invalidateQueries({ queryKey: ["documents", id] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const deleteDoc = useMutation({
    mutationFn: (docId: string) => apiDelete(`/v1/documents/${docId}`),
    onSuccess: () => {
      toast.success("Document deleted");
      queryClient.invalidateQueries({ queryKey: ["documents", id] });
    },
    onError: (err) => toast.error(String(err)),
  });

  if (isPending) return <div className="h-96 animate-pulse rounded-xl bg-muted" />;
  if (!emp) return <EmptyState title="Employee not found" description="It may belong to another organisation." testid="employee-not-found" />;

  const stat = (b: boolean) => (b ? "Applicable" : "Not applicable");

  return (
    <div>
      <PageHeader
        title={emp.name}
        description={`${emp.employee_code} · ${titleCase(emp.status)} · ${emp.designation || "—"} · ${emp.department_name || "—"}`}
        testid="employee-detail-title"
        actions={
          <>
            <Button variant="outline" data-testid="employee-edit-button" onClick={openEdit}><Pencil className="size-4" aria-hidden /> Edit</Button>
            {emp.status === "active" ? (
              <Button variant="outline" data-testid="employee-exit-button" onClick={() => setExitOpen(true)}>Record exit</Button>
            ) : null}
            <Button variant="destructive" data-testid="employee-delete-button" onClick={() => { if (confirm("Delete this employee? Payroll history remains.")) remove.mutate(); }}>
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </>
        }
      />

      <Tabs defaultValue="profile">
        <TabsList data-testid="employee-detail-tabs">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="salary">Salary</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
        </TabsList>

        <TabsContent value="profile" className="mt-4 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          <section className="space-y-3 rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold">Personal</h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Date of birth" value={dateLabel(emp.date_of_birth)} testid="emp-dob" />
              <Field label="Gender" value={titleCase(emp.gender)} testid="emp-gender" />
              <Field label="Marital status" value={titleCase(emp.marital_status)} testid="emp-marital" />
              <Field label="Phone" value={emp.phone} testid="emp-phone" />
              <Field label="Work email" value={emp.work_email} testid="emp-work-email" />
              <Field label="Personal email" value={emp.personal_email} testid="emp-personal-email" />
              <div className="col-span-2">
                <Field label="Address" value={[emp.address, emp.city, emp.state, emp.pin].filter(Boolean).join(", ")} testid="emp-address" />
              </div>
            </div>
          </section>
          <section className="space-y-3 rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold">Employment & statutory</h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Joining date" value={dateLabel(emp.joining_date)} testid="emp-doj" />
              <Field label="Employment type" value={titleCase(emp.employment_type)} testid="emp-employment-type" />
              <Field label="Grade" value={emp.grade} testid="emp-grade" />
              <Field label="Cost centre" value={emp.cost_centre} testid="emp-cost-centre" />
              <Field label="PAN" value={emp.pan} testid="emp-pan" />
              <Field label="UAN" value={emp.uan} testid="emp-uan" />
              <Field label="PF number" value={emp.pf_number} testid="emp-pf-number" />
              <Field label="ESI number" value={emp.esi_number} testid="emp-esi-number" />
              <Field label="PF" value={stat(emp.pf_applicable)} testid="emp-pf-applicable" />
              <Field label="ESI" value={stat(emp.esi_applicable)} testid="emp-esi-applicable" />
              <Field label="Professional Tax" value={stat(emp.pt_applicable)} testid="emp-pt-applicable" />
              <Field label="LWF" value={stat(emp.lwf_applicable)} testid="emp-lwf-applicable" />
              <Field label="Tax regime" value={titleCase(emp.tax_regime) + " regime"} testid="emp-tax-regime" />
            </div>
          </section>
          <section className="space-y-3 rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold">Bank & emergency</h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Bank" value={emp.bank_name} testid="emp-bank-name" />
              <Field label="Account number" value={emp.bank_account} testid="emp-bank-account" />
              <Field label="IFSC" value={emp.ifsc} testid="emp-ifsc" />
              <Field label="Account holder" value={emp.account_holder} testid="emp-account-holder" />
              <Field label="Emergency contact" value={emp.emergency_contact_name} testid="emp-emergency-name" />
              <Field label="Emergency phone" value={emp.emergency_contact_phone} testid="emp-emergency-phone" />
            </div>
          </section>
        </TabsContent>

        <TabsContent value="salary" className="mt-4">
          {data?.assignments.length === 0 ? (
            <EmptyState title="No salary assigned" description="Assign a structure from the Salary module." testid="employee-salary-empty" />
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <th className="px-4 py-2.5 font-semibold">Structure</th>
                    <th className="px-4 py-2.5 text-right font-semibold">Gross / month</th>
                    <th className="px-4 py-2.5 font-semibold">Effective from</th>
                    <th className="px-4 py-2.5 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.assignments.map((a) => (
                    <tr key={a.id} className="border-b border-border/60 last:border-b-0">
                      <td className="px-4 py-2.5">{data.structures.find((s) => s.id === a.structure_id)?.name ?? a.structure_id.slice(0, 8)}</td>
                      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{inr(a.gross_monthly)}</td>
                      <td className="px-4 py-2.5">{dateLabel(a.effective_from)}</td>
                      <td className="px-4 py-2.5">{a.active ? "Active" : "Superseded"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="documents" className="mt-4 space-y-4">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border bg-card px-4 py-2.5 text-sm hover:bg-muted/50">
            {upload.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Upload className="size-4" aria-hidden />}
            Upload document (max 5 MB)
            <input type="file" className="hidden" data-testid="employee-document-upload"
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }} />
          </label>
          {docs && docs.length > 0 ? (
            <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="employee-documents-list">
              {docs.map((d) => (
                <li key={d.id} className="flex items-center justify-between px-4 py-3 text-sm">
                  <div>
                    <p className="font-medium">{d.filename}</p>
                    <p className="text-xs text-muted-foreground">{titleCase(d.category)} · v{d.version} · {(d.size / 1024).toFixed(0)} KB · {dateLabel(d.created_at)}</p>
                  </div>
                  <div className="flex gap-2">
                    <a href={`/api/v1/documents/${d.id}/download`} download data-testid="document-download-link">
                      <Button size="sm" variant="outline"><Download className="size-4" aria-hidden /></Button>
                    </a>
                    {can(session.data?.permissions, "documents.delete") ? (
                      <Button size="sm" variant="ghost" aria-label="Delete document" onClick={() => deleteDoc.mutate(d.id)}><Trash2 className="size-4" /></Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No documents uploaded yet.</p>
          )}
        </TabsContent>
      </Tabs>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>Edit employee</DialogTitle></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              ["name", "Name *"], ["work_email", "Work email"], ["phone", "Phone"],
              ["date_of_birth", "Date of birth"], ["gender", "Gender"], ["marital_status", "Marital status"],
              ["personal_email", "Personal email"], ["address", "Address"], ["city", "City"],
              ["state", "State (code)"], ["pin", "PIN"], ["joining_date", "Joining date"],
              ["designation", "Designation"], ["department_name", "Department"], ["grade", "Grade"],
              ["location_name", "Location"], ["cost_centre", "Cost centre"], ["pan", "PAN"],
              ["uan", "UAN"], ["pf_number", "PF number"], ["esi_number", "ESI number"],
              ["tax_regime", "Tax regime (old/new)"], ["bank_name", "Bank"], ["bank_account", "Account number"],
              ["ifsc", "IFSC"], ["account_holder", "Account holder"],
              ["emergency_contact_name", "Emergency contact"], ["emergency_contact_phone", "Emergency phone"],
            ].map(([key, label]) => (
              <div key={key} className="space-y-1">
                <Label>{label}</Label>
                <Input
                  data-testid={`employee-edit-${key}`}
                  type={key === "date_of_birth" || key === "joining_date" ? "date" : "text"}
                  value={form[key] ?? ""}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                />
              </div>
            ))}
            <div className="flex items-center gap-4 sm:col-span-2">
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={emp.pf_applicable} onCheckedChange={() => {}} /> PF applicable (use employee list to toggle)</label>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name} data-testid="employee-edit-save">
              {save.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Save changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Exit dialog */}
      <Dialog open={exitOpen} onOpenChange={setExitOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>Record exit</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><Label>Last working day *</Label><Input type="date" data-testid="exit-date-input" value={exitDate} onChange={(e) => setExitDate(e.target.value)} /></div>
            <div className="space-y-1"><Label>Reason</Label><Input data-testid="exit-reason-input" value={exitReason} onChange={(e) => setExitReason(e.target.value)} placeholder="Resignation / termination…" /></div>
          </div>
          <DialogFooter>
            <Button onClick={() => exit.mutate()} disabled={exit.isPending || !exitDate} data-testid="exit-confirm-button">Confirm exit</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
