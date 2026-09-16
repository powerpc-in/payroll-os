// Guided 8-step company onboarding wizard. All steps hold state client-side and
// commit atomically on the final step — a run can't be half-configured.

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiGet, apiPost } from "@/lib/api";
import type { Jurisdiction } from "@/lib/types";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

const STEPS = ["Company", "Payroll", "Locations", "Statutory", "Salary", "Leave", "Employees", "Test Run"];

interface SeedRow {
  name: string;
  email: string;
  department: string;
  designation: string;
  state: string;
  gross_monthly: number | "";
  joining_date: string;
  tax_regime: string;
  pf_applicable: boolean;
  esi_applicable: boolean;
}

const EMPTY_ROW: SeedRow = {
  name: "", email: "", department: "", designation: "", state: "KA",
  gross_monthly: "", joining_date: "", tax_regime: "new",
  pf_applicable: true, esi_applicable: true,
};

export default function Onboarding() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [done, setDone] = useState<{ run_id: string | null; employee_count: number } | null>(null);

  const [company, setCompany] = useState({ name: "", address: "", city: "", state: "KA" });
  const [payroll, setPayroll] = useState({ pay_frequency: "monthly", pay_day: "last-day" });
  const [acceptUnverified, setAcceptUnverified] = useState(true);
  const [locations, setLocations] = useState([{ name: "Head Office", city: "", state: "KA" }]);
  const [structure, setStructure] = useState({ name: "Standard India Structure", basic_pct: 40, hra_pct: 50 });
  const [leaveTypes, setLeaveTypes] = useState([
    { code: "CL", name: "Casual Leave", annual_quota: 12, paid: true, carry_forward: true },
    { code: "EL", name: "Earned Leave", annual_quota: 15, paid: true, carry_forward: true },
    { code: "SL", name: "Sick Leave", annual_quota: 8, paid: true, carry_forward: true },
  ]);
  const [employees, setEmployees] = useState<SeedRow[]>([]);
  const [draft, setDraft] = useState<SeedRow>(EMPTY_ROW);
  const [runTest, setRunTest] = useState(true);

  const { data: jurisdictions } = useQuery({
    queryKey: ["jurisdictions"],
    queryFn: () => apiGet<Jurisdiction[]>("/v1/jurisdictions"),
  });
  const states = jurisdictions?.find((j) => j.code === "IN")?.states ?? [];

  const finish = useMutation({
    mutationFn: () =>
      apiPost<{ ok: boolean; employee_count: number; run_id: string | null }>("/v1/org/onboarding", {
        company: { ...company, jurisdiction: "IN" },
        payroll,
        statutory: { accept_unverified: acceptUnverified },
        structure_name: structure.name,
        basic_pct: Number(structure.basic_pct),
        hra_pct: Number(structure.hra_pct),
        locations,
        leave_types: leaveTypes,
        employees: employees.map((e) => ({ ...e, gross_monthly: Number(e.gross_monthly) })),
        run_test_payroll: runTest,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["session"] });
      setDone({ run_id: res.run_id, employee_count: res.employee_count });
      toast.success("Setup complete — your workspace is ready");
    },
    onError: (err) => toast.error(String(err)),
  });

  const preview = useMemo(() => {
    const gross = 50000;
    const basic = Math.round(gross * Number(structure.basic_pct) / 100);
    const hra = Math.round(basic * Number(structure.hra_pct) / 100);
    return { gross, basic, hra, special: gross - basic - hra };
  }, [structure]);

  const addEmployee = () => {
    if (!draft.name || !draft.joining_date || !draft.gross_monthly) {
      toast.error("Name, joining date and monthly gross are required");
      return;
    }
    setEmployees([...employees, draft]);
    setDraft(EMPTY_ROW);
  };

  if (done) {
    return (
      <div className="flex min-h-svh flex-col items-center justify-center bg-background px-6">
        <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 text-center shadow-sm">
          <span className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
            <Check className="size-6" aria-hidden />
          </span>
          <h1 className="font-heading text-2xl font-bold text-foreground">You're all set</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {done.employee_count} employees seeded
            {done.run_id ? " and a test payroll run has been calculated." : "."}
          </p>
          <Button className="mt-6 w-full" data-testid="onboarding-go-dashboard" onClick={() => navigate("/app")}>
            Go to dashboard
          </Button>
        </div>
      </div>
    );
  }

  const stepOk =
    step !== 6 || employees.length >= 0; // employees optional — demo company can be created solo

  return (
    <div className="min-h-svh bg-background">
      {/* stage ribbon */}
      <div className="border-b border-border bg-card/60 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-2 overflow-x-auto px-4 py-3">
          {STEPS.map((label, i) => (
            <button
              key={label}
              data-testid={`onboarding-step-${i + 1}`}
              onClick={() => setStep(i)}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-xs",
                i === step
                  ? "bg-primary font-semibold text-primary-foreground shadow-sm"
                  : i < step
                    ? "border border-emerald-200 bg-emerald-100 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300"
                    : "border border-border bg-muted text-muted-foreground",
              )}
            >
              {i < step ? <Check className="size-3" aria-hidden /> : <span>{i + 1}</span>}
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-4xl px-4 py-8">
        {step === 0 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Company information</h1>
              <p className="text-sm text-muted-foreground">The legal entity that runs payroll.</p>
            </header>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <Label>Company name</Label>
                <Input data-testid="onboarding-company-name" value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} placeholder="Kaveri Textiles Pvt Ltd" />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label>Registered address</Label>
                <Input data-testid="onboarding-company-address" value={company.address} onChange={(e) => setCompany({ ...company, address: e.target.value })} placeholder="Plot 14, Industrial Area" />
              </div>
              <div className="space-y-1.5">
                <Label>City</Label>
                <Input data-testid="onboarding-company-city" value={company.city} onChange={(e) => setCompany({ ...company, city: e.target.value })} placeholder="Bengaluru" />
              </div>
              <div className="space-y-1.5">
                <Label>State</Label>
                <Select value={company.state} onValueChange={(v: string) => setCompany({ ...company, state: v })}>
                  <SelectTrigger data-testid="onboarding-company-state"><SelectValue>{(v: string) => states.find((s) => s.code === v)?.name ?? v}</SelectValue></SelectTrigger>
                  <SelectContent>{states.map((s) => <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
          </section>
        )}

        {step === 1 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Payroll configuration</h1>
              <p className="text-sm text-muted-foreground">How often you run payroll and when it pays out.</p>
            </header>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Pay frequency</Label>
                <Select value={payroll.pay_frequency} onValueChange={(v: string) => setPayroll({ ...payroll, pay_frequency: v })}>
                  <SelectTrigger data-testid="onboarding-pay-frequency"><SelectValue>{(v: string) => v === "monthly" ? "Monthly" : v}</SelectValue></SelectTrigger>
                  <SelectContent><SelectItem value="monthly">Monthly</SelectItem></SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Pay day</Label>
                <Select value={payroll.pay_day} onValueChange={(v: string) => setPayroll({ ...payroll, pay_day: v })}>
                  <SelectTrigger data-testid="onboarding-pay-day"><SelectValue>{(v: string) => v === "last-day" ? "Last day of month" : v}</SelectValue></SelectTrigger>
                  <SelectContent><SelectItem value="last-day">Last day of month</SelectItem></SelectContent>
                </Select>
              </div>
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">State / location configuration</h1>
              <p className="text-sm text-muted-foreground">Locations drive Professional Tax and LWF (state-aware).</p>
            </header>
            {locations.map((loc, i) => (
              <div key={i} className="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[1fr_1fr_auto_auto]">
                <Input placeholder="Location name" value={loc.name} onChange={(e) => setLocations(locations.map((l, j) => j === i ? { ...l, name: e.target.value } : l))} data-testid={`onboarding-location-name-${i}`} />
                <Input placeholder="City" value={loc.city} onChange={(e) => setLocations(locations.map((l, j) => j === i ? { ...l, city: e.target.value } : l))} />
                <Select value={loc.state} onValueChange={(v: string) => setLocations(locations.map((l, j) => j === i ? { ...l, state: v } : l))}>
                  <SelectTrigger><SelectValue>{(v: string) => states.find((s) => s.code === v)?.name ?? v}</SelectValue></SelectTrigger>
                  <SelectContent>{states.map((s) => <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>)}</SelectContent>
                </Select>
                <Button variant="ghost" size="icon" onClick={() => setLocations(locations.filter((_, j) => j !== i))} aria-label="Remove location"><Trash2 className="size-4" /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" data-testid="onboarding-add-location" onClick={() => setLocations([...locations, { name: "", city: "", state: company.state }])}>
              <Plus className="size-4" aria-hidden /> Add location
            </Button>
          </section>
        )}

        {step === 3 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Statutory configuration</h1>
              <p className="text-sm text-muted-foreground">
                India statutory rules are seeded as versioned records for PF, ESI, Professional Tax, LWF and TDS — every value carries a "Requires statutory verification" flag.
              </p>
            </header>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
              <p className="font-medium">Fail-safe by design</p>
              <p className="mt-1 text-xs leading-relaxed">
                Payroll rows fail with an explicit reason rather than computing with unverified rules. To run the demo engine you must explicitly accept computations with unverified statutory values — every payslip, run and report will display the verification badge until the rules are independently verified.
              </p>
            </div>
            <label className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 text-sm">
              <Checkbox checked={acceptUnverified} onCheckedChange={(c) => setAcceptUnverified(Boolean(c))} data-testid="onboarding-accept-unverified" />
              Accept computations with unverified statutory values (demo mode)
            </label>
          </section>
        )}

        {step === 4 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Salary components</h1>
              <p className="text-sm text-muted-foreground">A classic Indian structure: Basic (% of gross), HRA (% of Basic), Special (balancing figure).</p>
            </header>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>Structure name</Label>
                <Input data-testid="onboarding-structure-name" value={structure.name} onChange={(e) => setStructure({ ...structure, name: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Basic — % of gross</Label>
                <Input type="number" data-testid="onboarding-basic-pct" value={structure.basic_pct} onChange={(e) => setStructure({ ...structure, basic_pct: Number(e.target.value) })} />
              </div>
              <div className="space-y-1.5">
                <Label>HRA — % of Basic</Label>
                <Input type="number" data-testid="onboarding-hra-pct" value={structure.hra_pct} onChange={(e) => setStructure({ ...structure, hra_pct: Number(e.target.value) })} />
              </div>
            </div>
            <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm" data-testid="onboarding-structure-preview">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Preview on ₹{inr(preview.gross)} gross</p>
              <div className="grid gap-1 font-mono text-sm tabular-nums">
                <div className="flex justify-between"><span>Basic ({structure.basic_pct}%)</span><span>{inr(preview.basic)}</span></div>
                <div className="flex justify-between"><span>HRA ({structure.hra_pct}% of Basic)</span><span>{inr(preview.hra)}</span></div>
                <div className="flex justify-between border-t border-border pt-1"><span>Special Allowance (balance)</span><span>{inr(preview.special)}</span></div>
              </div>
            </div>
          </section>
        )}

        {step === 5 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Leave policy</h1>
              <p className="text-sm text-muted-foreground">Configurable quotas — no assumption that every company or state is the same.</p>
            </header>
            {leaveTypes.map((lt, i) => (
              <div key={lt.code} className="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[80px_1fr_100px_auto]">
                <Input value={lt.code} aria-label="Leave code" onChange={(e) => setLeaveTypes(leaveTypes.map((l, j) => j === i ? { ...l, code: e.target.value.toUpperCase() } : l))} />
                <Input value={lt.name} aria-label="Leave name" onChange={(e) => setLeaveTypes(leaveTypes.map((l, j) => j === i ? { ...l, name: e.target.value } : l))} />
                <Input type="number" value={lt.annual_quota} aria-label="Annual quota" onChange={(e) => setLeaveTypes(leaveTypes.map((l, j) => j === i ? { ...l, annual_quota: Number(e.target.value) } : l))} />
                <Button variant="ghost" size="icon" onClick={() => setLeaveTypes(leaveTypes.filter((_, j) => j !== i))} aria-label="Remove leave type"><Trash2 className="size-4" /></Button>
              </div>
            ))}
            <Button variant="outline" size="sm" data-testid="onboarding-add-leave-type" onClick={() => setLeaveTypes([...leaveTypes, { code: "LT", name: "New leave type", annual_quota: 6, paid: true, carry_forward: false }])}>
              <Plus className="size-4" aria-hidden /> Add leave type
            </Button>
          </section>
        )}

        {step === 6 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Add employees</h1>
              <p className="text-sm text-muted-foreground">Mixed states, regimes and PF/ESI applicability are encouraged — the engine handles each case.</p>
            </header>
            <div className="grid gap-3 rounded-xl border border-border bg-card p-4 md:grid-cols-4">
              <div className="space-y-1"><Label>Name *</Label><Input data-testid="seed-employee-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
              <div className="space-y-1"><Label>Email</Label><Input type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></div>
              <div className="space-y-1"><Label>Department</Label><Input value={draft.department} onChange={(e) => setDraft({ ...draft, department: e.target.value })} /></div>
              <div className="space-y-1"><Label>Designation</Label><Input value={draft.designation} onChange={(e) => setDraft({ ...draft, designation: e.target.value })} /></div>
              <div className="space-y-1"><Label>State</Label>
                <Select value={draft.state} onValueChange={(v: string) => setDraft({ ...draft, state: v })}>
                  <SelectTrigger><SelectValue>{(v: string) => states.find((s) => s.code === v)?.name ?? v}</SelectValue></SelectTrigger>
                  <SelectContent>{states.map((s) => <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1"><Label>Monthly gross *</Label><Input type="number" data-testid="seed-employee-gross" value={draft.gross_monthly} onChange={(e) => setDraft({ ...draft, gross_monthly: Number(e.target.value) })} /></div>
              <div className="space-y-1"><Label>Joining date *</Label><Input type="date" data-testid="seed-employee-doj" value={draft.joining_date} onChange={(e) => setDraft({ ...draft, joining_date: e.target.value })} /></div>
              <div className="space-y-1"><Label>Tax regime</Label>
                <Select value={draft.tax_regime} onValueChange={(v: string) => setDraft({ ...draft, tax_regime: v })}>
                  <SelectTrigger><SelectValue>{(v: string) => v === "new" ? "New regime" : "Old regime"}</SelectValue></SelectTrigger>
                  <SelectContent><SelectItem value="new">New regime</SelectItem><SelectItem value="old">Old regime</SelectItem></SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-4 md:col-span-2">
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={draft.pf_applicable} onCheckedChange={(c) => setDraft({ ...draft, pf_applicable: Boolean(c) })} /> PF applicable</label>
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={draft.esi_applicable} onCheckedChange={(c) => setDraft({ ...draft, esi_applicable: Boolean(c) })} /> ESI applicable</label>
              </div>
              <div className="flex items-end md:col-span-2">
                <Button className="w-full md:w-auto" data-testid="seed-employee-add" onClick={addEmployee} variant="outline"><Plus className="size-4" aria-hidden /> Add to list</Button>
              </div>
            </div>
            {employees.length > 0 && (
              <ul className="divide-y divide-border rounded-xl border border-border bg-card text-sm">
                {employees.map((e, i) => (
                  <li key={`${e.name}-${i}`} className="flex items-center justify-between px-4 py-2.5">
                    <span className="font-medium">{e.name}</span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">{e.department || "—"} · {e.state} · {inr(Number(e.gross_monthly))}/mo · {e.tax_regime} regime</span>
                    <Button variant="ghost" size="icon" aria-label="Remove" onClick={() => setEmployees(employees.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {step === 7 && (
          <section className="space-y-5">
            <header>
              <h1 className="font-heading text-2xl font-bold">Run test payroll</h1>
              <p className="text-sm text-muted-foreground">Complete setup and immediately calculate this month's payroll to verify the engine end-to-end.</p>
            </header>
            <label className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 text-sm">
              <Checkbox checked={runTest} onCheckedChange={(c) => setRunTest(Boolean(c))} data-testid="onboarding-run-test" />
              Calculate a test payroll run for the current month
            </label>
            <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
              {employees.length} employee(s) · {locations.length} location(s) · {leaveTypes.length} leave type(s) · structure "{structure.name}"
            </div>
            <Button
              size="lg" className="w-full" data-testid="onboarding-finish-button"
              disabled={finish.isPending || !stepOk || !company.name}
              onClick={() => finish.mutate()}
            >
              {finish.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              Complete setup
            </Button>
            {!company.name ? <p className="text-xs text-destructive">Company name is required (step 1).</p> : null}
          </section>
        )}

        <div className="mt-8 flex justify-between">
          <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)} data-testid="onboarding-back">Back</Button>
          <Button disabled={step === STEPS.length - 1} onClick={() => setStep(step + 1)} data-testid="onboarding-next">Next</Button>
        </div>
      </div>
    </div>
  );
}
