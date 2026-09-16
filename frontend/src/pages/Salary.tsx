// Salary engine UI: structures (component recipes), custom components, and
// employee assignments.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type { Employee, Paged, SalaryAssignment, SalaryStructure, StructureComponent } from "@/lib/types";
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

const DEFAULT_COMPONENTS: StructureComponent[] = [
  { code: "BASIC", name: "Basic Salary", calc: "pct_gross", value: 40, taxable: true, pf_applicable: true, esi_applicable: true, ctc_included: true },
  { code: "HRA", name: "House Rent Allowance", calc: "pct_basic", value: 50, taxable: true, pf_applicable: false, esi_applicable: true, ctc_included: true },
  { code: "SPECIAL", name: "Special Allowance", calc: "gross_balance", value: 0, taxable: true, pf_applicable: false, esi_applicable: true, ctc_included: true },
];

export default function Salary() {
  const [tab, setTab] = useState("structures");
  return (
    <div>
      <PageHeader title="Salary & Compensation" description="Component engine, structures and assignments — the recipe payroll consumes." testid="salary-title" />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="salary-tabs">
          <TabsTrigger value="structures">Structures</TabsTrigger>
          <TabsTrigger value="components">Components</TabsTrigger>
          <TabsTrigger value="assignments">Assignments</TabsTrigger>
        </TabsList>
        <TabsContent value="structures"><StructuresTab /></TabsContent>
        <TabsContent value="components"><ComponentsTab /></TabsContent>
        <TabsContent value="assignments"><AssignmentsTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function StructuresTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [components, setComponents] = useState<StructureComponent[]>(DEFAULT_COMPONENTS);

  const { data, isPending } = useQuery({
    queryKey: ["structures"],
    queryFn: () => apiGet<SalaryStructure[]>("/v1/salary/structures"),
  });

  const create = useMutation({
    mutationFn: () => apiPost("/v1/salary/structures", { name, components }),
    onSuccess: () => {
      toast.success("Structure created");
      queryClient.invalidateQueries({ queryKey: ["structures"] });
      setOpen(false); setName(""); setComponents(DEFAULT_COMPONENTS);
    },
    onError: (err) => toast.error(String(err)),
  });

  return (
    <div className="mt-4 space-y-4">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger render={<Button data-testid="add-structure-button"><Plus className="size-4" aria-hidden /> New structure</Button>} />
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>New salary structure</DialogTitle></DialogHeader>
          <div className="space-y-1"><Label>Structure name *</Label><Input data-testid="structure-name-input" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-2">
            {components.map((c, i) => (
              <div key={i} className="grid grid-cols-[1fr_1.4fr_1fr_80px_auto] items-center gap-2">
                <Input placeholder="Code" value={c.code} onChange={(e) => setComponents(components.map((x, j) => j === i ? { ...x, code: e.target.value.toUpperCase() } : x))} />
                <Input placeholder="Name" value={c.name} onChange={(e) => setComponents(components.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                <Select value={c.calc} onValueChange={(v: string) => setComponents(components.map((x, j) => j === i ? { ...x, calc: v as StructureComponent["calc"] } : x))}>
                  <SelectTrigger><SelectValue>{(v: string) => ({ fixed: "Fixed amount", pct_gross: "% of gross", pct_basic: "% of basic", gross_balance: "Gross balance" })[v] ?? v}</SelectValue></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fixed">Fixed amount</SelectItem>
                    <SelectItem value="pct_gross">% of gross</SelectItem>
                    <SelectItem value="pct_basic">% of basic</SelectItem>
                    <SelectItem value="gross_balance">Gross balance</SelectItem>
                  </SelectContent>
                </Select>
                <Input type="number" value={c.value} aria-label="Value" onChange={(e) => setComponents(components.map((x, j) => j === i ? { ...x, value: Number(e.target.value) } : x))} />
                <Button variant="ghost" size="icon" aria-label="Remove component" onClick={() => setComponents(components.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" data-testid="structure-add-component" onClick={() => setComponents([...components, { code: "", name: "", calc: "fixed", value: 0, taxable: true, pf_applicable: false, esi_applicable: true, ctc_included: true }])}>
              <Plus className="size-4" aria-hidden /> Add component
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => create.mutate()} disabled={create.isPending || !name} data-testid="structure-save-button">Save structure</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isPending ? <div className="h-40 animate-pulse rounded-xl bg-muted" /> : (data?.length ?? 0) === 0 ? (
        <EmptyState title="No salary structures" description="Create the recipe payroll uses to compute earnings." testid="structures-empty" />
      ) : (
        <ul className="space-y-3" data-testid="structures-list">
          {data!.map((s) => (
            <li key={s.id} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center justify-between">
                <p className="font-medium text-foreground">{s.name}</p>
                <span className="text-xs text-muted-foreground">{s.components.length} components</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {s.components.map((c) => (
                  <span key={c.code} className="rounded-md border border-border bg-muted/60 px-2 py-0.5 text-xs font-mono">
                    {c.code} · {c.calc}{c.calc !== "gross_balance" ? ` ${c.value}` : ""}
                    {c.pf_applicable ? " · PF" : ""}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ComponentsTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", type: "earning", calc: "fixed", value: 0, taxable: true, pf_applicable: false, esi_applicable: true });
  const { data } = useQuery({ queryKey: ["components"], queryFn: () => apiGet<Record<string, unknown>[]>("/v1/salary/components") });
  const create = useMutation({
    mutationFn: () => apiPost("/v1/salary/components", form),
    onSuccess: () => { toast.success("Component created"); queryClient.invalidateQueries({ queryKey: ["components"] }); setOpen(false); },
    onError: (err) => toast.error(String(err)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/salary/components/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["components"] }),
  });
  return (
    <div className="mt-4 space-y-4">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger render={<Button data-testid="add-component-button"><Plus className="size-4" aria-hidden /> New component</Button>} />
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>New salary component</DialogTitle></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label>Code *</Label><Input data-testid="component-code-input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} /></div>
            <div className="space-y-1"><Label>Name *</Label><Input data-testid="component-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="space-y-1"><Label>Type</Label>
              <Select value={form.type} onValueChange={(v: string) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="component-type-select"><SelectValue>{(v: string) => titleCase(v)}</SelectValue></SelectTrigger>
                <SelectContent><SelectItem value="earning">Earning</SelectItem><SelectItem value="deduction">Deduction</SelectItem><SelectItem value="employer_contribution">Employer contribution</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Calculation</Label>
              <Select value={form.calc} onValueChange={(v: string) => setForm({ ...form, calc: v })}>
                <SelectTrigger data-testid="component-calc-select"><SelectValue>{(v: string) => ({ fixed: "Fixed", pct_gross: "% of gross", pct_basic: "% of basic", gross_balance: "Gross balance" })[v] ?? v}</SelectValue></SelectTrigger>
                <SelectContent><SelectItem value="fixed">Fixed</SelectItem><SelectItem value="pct_gross">% of gross</SelectItem><SelectItem value="pct_basic">% of basic</SelectItem><SelectItem value="gross_balance">Gross balance</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Value</Label><Input type="number" data-testid="component-value-input" value={form.value} onChange={(e) => setForm({ ...form, value: Number(e.target.value) })} /></div>
            <div className="flex items-center gap-3 pt-5">
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.taxable} onCheckedChange={(c) => setForm({ ...form, taxable: Boolean(c) })} /> Taxable</label>
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.pf_applicable} onCheckedChange={(c) => setForm({ ...form, pf_applicable: Boolean(c) })} /> PF</label>
            </div>
          </div>
          <DialogFooter><Button onClick={() => create.mutate()} disabled={create.isPending || !form.code || !form.name} data-testid="component-save-button">Save component</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      {(data ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">No custom components — structures can define components inline.</p>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="components-list">
          {data!.map((c) => (
            <li key={String(c.id)} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <span className="font-medium font-mono">{String(c.code)}</span>
              <span>{String(c.name)}</span>
              <span className="text-xs text-muted-foreground">{titleCase(String(c.type))}</span>
              <Button variant="ghost" size="icon" aria-label="Delete component" onClick={() => remove.mutate(String(c.id))}><Trash2 className="size-4" /></Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssignmentsTab() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ employee_id: "", structure_id: "", gross_monthly: "", effective_from: "" });
  const { data } = useQuery({ queryKey: ["assignments"], queryFn: () => apiGet<SalaryAssignment[]>("/v1/salary/assignments") });
  const { data: employees } = useQuery({ queryKey: ["employees", "for-assign"], queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100"), enabled: open });
  const { data: structures } = useQuery({ queryKey: ["structures"], queryFn: () => apiGet<SalaryStructure[]>("/v1/salary/structures"), enabled: open });
  const { data: empIndex } = useQuery({ queryKey: ["employees", "index-assign"], queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100") });

  const create = useMutation({
    mutationFn: () => apiPost("/v1/salary/assignments", { ...form, gross_monthly: Number(form.gross_monthly) }),
    onSuccess: () => {
      toast.success("Salary assigned");
      queryClient.invalidateQueries({ queryKey: ["assignments"] });
      queryClient.invalidateQueries({ queryKey: ["employees"] });
      setOpen(false);
    },
    onError: (err) => toast.error(String(err)),
  });

  const empName = (eid: string) => empIndex?.items.find((e) => e.id === eid)?.name ?? eid.slice(0, 8);

  return (
    <div className="mt-4 space-y-4">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger render={<Button data-testid="assign-salary-button"><Plus className="size-4" aria-hidden /> Assign salary</Button>} />
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>Assign salary structure</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><Label>Employee *</Label>
              <Select value={form.employee_id} onValueChange={(v: string) => setForm({ ...form, employee_id: v })}>
                <SelectTrigger data-testid="assign-employee-select"><SelectValue>{(v: string) => empName(v)}</SelectValue></SelectTrigger>
                <SelectContent>{employees?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name} ({e.employee_code})</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Structure *</Label>
              <Select value={form.structure_id} onValueChange={(v: string) => setForm({ ...form, structure_id: v })}>
                <SelectTrigger data-testid="assign-structure-select"><SelectValue>{(v: string) => structures?.find((s) => s.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
                <SelectContent>{structures?.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Monthly gross (CTC basis) *</Label><Input type="number" data-testid="assign-gross-input" value={form.gross_monthly} onChange={(e) => setForm({ ...form, gross_monthly: e.target.value })} /></div>
            <div className="space-y-1"><Label>Effective from *</Label><Input type="date" data-testid="assign-effective-from" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} /></div>
          </div>
          <DialogFooter><Button onClick={() => create.mutate()} disabled={create.isPending || !form.employee_id || !form.structure_id || !form.gross_monthly} data-testid="assign-save-button">Assign</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      {(data ?? []).length === 0 ? (
        <EmptyState title="No assignments" description="Assign a structure with monthly gross to each employee." testid="assignments-empty" />
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="assignments-list">
          {data!.map((a) => (
            <li key={a.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <span className="font-medium">{empName(a.employee_id)}</span>
              <span className="font-mono tabular-nums">{inr(a.gross_monthly)}/mo</span>
              <span className="text-xs text-muted-foreground">from {dateLabel(a.effective_from)}</span>
              <span className={`rounded-full border px-2 py-0.5 text-xs ${a.active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>{a.active ? "Active" : "Superseded"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
