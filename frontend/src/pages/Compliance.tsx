// Compliance console: jurisdiction registry (India active, others are verified
// placeholders) + versioned statutory rules with verification badges.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, ShieldAlert, ShieldCheck } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Jurisdiction, StatutoryRule } from "@/lib/types";
import { titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageHeader, VerificationBadge } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

export default function Compliance() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ rule_type: "professional_tax", state: "", effective_from: "", source: "", params: "{}", verified: false });

  const { data: rules, isPending } = useQuery({ queryKey: ["statutory-rules"], queryFn: () => apiGet<StatutoryRule[]>("/v1/compliance/rules") });
  const { data: jurisdictions } = useQuery({ queryKey: ["jurisdictions"], queryFn: () => apiGet<Jurisdiction[]>("/v1/jurisdictions") });

  const addRule = useMutation({
    mutationFn: () => apiPost("/v1/compliance/rules", {
      jurisdiction: "IN", rule_type: form.rule_type, state: form.state || undefined,
      effective_from: form.effective_from, source: form.source,
      params: JSON.parse(form.params), verified: form.verified,
    }),
    onSuccess: () => {
      toast.success(form.verified ? "Rule version added (verified)" : "Rule version added — marked requires verification");
      queryClient.invalidateQueries({ queryKey: ["statutory-rules"] });
      setOpen(false);
    },
    onError: (err) => toast.error(String(err)),
  });

  const filtered = (rules ?? []).filter((r) => !filter || r.rule_type.includes(filter));

  return (
    <div>
      <PageHeader
        title="Compliance Rules"
        description="Versioned statutory rules. The engine refuses to compute with unverified values unless the org explicitly opts in."
        testid="compliance-title"
        actions={can(session.data?.permissions, "compliance.manage") ? (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="add-rule-button"><Plus className="size-4" aria-hidden /> New rule version</Button>} />
            <DialogContent className="sm:max-w-lg">
              <DialogHeader><DialogTitle>Add statutory rule version</DialogTitle></DialogHeader>
              <DialogDescription>
                Enter values you have independently verified. Only tick "verified" if you have confirmed the values against the source.
              </DialogDescription>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1"><Label>Rule type</Label>
                  <Select value={form.rule_type} onValueChange={(v: string) => setForm({ ...form, rule_type: v })}>
                    <SelectTrigger data-testid="rule-type-select"><SelectValue>{(v: string) => titleCase(v.replace(/_/g, " "))}</SelectValue></SelectTrigger>
                    <SelectContent>
                      {["income_tax_old_regime", "income_tax_new_regime", "provident_fund", "employee_state_insurance", "professional_tax", "lwf", "gratuity", "bonus"].map((t) => (
                        <SelectItem key={t} value={t}>{titleCase(t.replace(/_/g, " "))}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>State (blank = national)</Label><Input data-testid="rule-state-input" value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value.toUpperCase() })} placeholder="KA" /></div>
                <div className="space-y-1"><Label>Effective from *</Label><Input type="date" data-testid="rule-effective-from" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} /></div>
                <div className="space-y-1"><Label>Source</Label><Input data-testid="rule-source-input" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder="Act / gazette reference" /></div>
                <div className="space-y-1 sm:col-span-2">
                  <Label>Params (JSON)</Label>
                  <textarea
                    data-testid="rule-params-input" rows={6}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs"
                    value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })}
                  />
                </div>
                <label className="flex items-center gap-2 text-sm sm:col-span-2">
                  <Checkbox checked={form.verified} onCheckedChange={(c) => setForm({ ...form, verified: Boolean(c) })} data-testid="rule-verified-checkbox" />
                  I have independently verified these values
                </label>
              </div>
              <DialogFooter><Button onClick={() => addRule.mutate()} disabled={addRule.isPending || !form.effective_from} data-testid="rule-save-button">Add version</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        ) : undefined}
      />

      {/* Jurisdiction registry */}
      <div className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4" data-testid="jurisdiction-cards">
        {(jurisdictions ?? []).map((j) => (
          <div key={j.code} className={`rounded-xl border p-4 ${j.status === "active" ? "border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/30" : "border-border bg-card"}`}>
            <div className="flex items-center justify-between">
              <p className="font-medium text-foreground">{j.name}</p>
              {j.status === "active"
                ? <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700"><ShieldCheck className="size-3" aria-hidden /> Active</span>
                : <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700"><ShieldAlert className="size-3" aria-hidden /> Module ready</span>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{j.currency} · tax year {j.tax_year_label}</p>
            {j.note ? <p className="mt-2 text-[11px] leading-snug text-amber-700 dark:text-amber-400">{j.note}</p> : null}
          </div>
        ))}
      </div>

      <div className="mb-3 flex items-center gap-3">
        <Input placeholder="Filter rule types (e.g. professional_tax)…" className="max-w-xs" data-testid="rules-filter-input" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span className="text-xs text-muted-foreground">{filtered.length} version(s)</span>
      </div>

      {isPending ? <div className="h-64 animate-pulse rounded-xl bg-muted" /> : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card" data-testid="statutory-rules-table">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-2.5 font-semibold">Rule</th>
                <th className="px-4 py-2.5 font-semibold">Jurisdiction</th>
                <th className="px-4 py-2.5 font-semibold">Version</th>
                <th className="px-4 py-2.5 font-semibold">Effective</th>
                <th className="px-4 py-2.5 font-semibold">Source</th>
                <th className="px-4 py-2.5 font-semibold">Verification</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-border/60 last:border-b-0">
                  <td className="px-4 py-2.5 font-medium">{titleCase(r.rule_type.replace(/_/g, " "))}{r.state ? ` · ${r.state}` : ""}</td>
                  <td className="px-4 py-2.5">{r.jurisdiction}</td>
                  <td className="px-4 py-2.5 font-mono">v{r.version}</td>
                  <td className="px-4 py-2.5 text-xs">{r.effective_from} → {r.effective_to ?? "open"}</td>
                  <td className="px-4 py-2.5 text-xs text-muted-foreground">{r.source ?? "—"}</td>
                  <td className="px-4 py-2.5"><VerificationBadge verified={r.verified} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 ? <div className="p-6"><EmptyState title="No rules match" testid="rules-empty" /></div> : null}
        </div>
      )}
    </div>
  );
}
