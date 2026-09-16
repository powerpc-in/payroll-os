// Settings: organisation profile, payroll config, jurisdiction (with honest
// placeholder states), users & roles.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus } from "lucide-react";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type { Jurisdiction, OrgSummary, OrgUser } from "@/lib/types";
import { titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";

interface OrgFull extends OrgSummary {
  address?: string;
  city?: string;
  state?: string;
  payroll_settings: { pay_frequency: string; pay_day: string; accept_unverified_statutory_values: boolean };
}

export default function Settings() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [userOpen, setUserOpen] = useState(false);
  const [userForm, setUserForm] = useState({ name: "", email: "", password: "", role: "EMPLOYEE", employee_id: "" });

  const { data: org } = useQuery({ queryKey: ["org"], queryFn: () => apiGet<OrgFull>("/v1/org") });
  const { data: jurisdictions } = useQuery({ queryKey: ["jurisdictions"], queryFn: () => apiGet<Jurisdiction[]>("/v1/jurisdictions") });
  const { data: users } = useQuery({ queryKey: ["org-users"], queryFn: () => apiGet<OrgUser[]>("/v1/org/users") });
  const { data: roles } = useQuery({ queryKey: ["org-roles"], queryFn: () => apiGet<{ role: string; permissions: string[] }[]>("/v1/org/roles") });

  const [form, setForm] = useState<Partial<OrgFull>>({});
  const merged = { ...org, ...form };

  const save = useMutation({
    mutationFn: () => apiPut("/v1/org", {
      name: merged.name, address: merged.address, city: merged.city, state: merged.state,
      jurisdiction: merged.jurisdiction,
      pay_frequency: merged.payroll_settings?.pay_frequency,
      pay_day: merged.payroll_settings?.pay_day,
      accept_unverified_statutory_values: merged.payroll_settings?.accept_unverified_statutory_values,
    }),
    onSuccess: () => {
      toast.success("Settings saved");
      queryClient.invalidateQueries({ queryKey: ["org"] });
      queryClient.invalidateQueries({ queryKey: ["session"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const addUser = useMutation({
    mutationFn: () => apiPost("/v1/org/users", {
      name: userForm.name, email: userForm.email, password: userForm.password,
      role: userForm.role, employee_id: userForm.employee_id || undefined,
    }),
    onSuccess: () => {
      toast.success("User added — share the password securely");
      queryClient.invalidateQueries({ queryKey: ["org-users"] });
      setUserOpen(false);
      setUserForm({ name: "", email: "", password: "", role: "EMPLOYEE", employee_id: "" });
    },
    onError: (err) => toast.error(String(err)),
  });

  const { data: employees } = useQuery({
    queryKey: ["employees", "settings-page"],
    queryFn: () => apiGet<{ items: { id: string; name: string }[] }>("/v1/employees?page=1&limit=100"),
    enabled: userOpen,
  });

  const states = jurisdictions?.find((j) => j.code === "IN")?.states ?? [];

  return (
    <div>
      <PageHeader title="Settings" description="Organisation, payroll configuration and users." testid="settings-title" />
      <Tabs defaultValue="org">
        <TabsList data-testid="settings-tabs">
          <TabsTrigger value="org">Organisation</TabsTrigger>
          <TabsTrigger value="users">Users & roles</TabsTrigger>
        </TabsList>

        <TabsContent value="org" className="mt-4 max-w-2xl space-y-5">
          <div className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
            <div className="space-y-1 sm:col-span-2"><Label>Company name</Label>
              <Input data-testid="settings-org-name" value={merged.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="space-y-1 sm:col-span-2"><Label>Address</Label>
              <Input data-testid="settings-org-address" value={merged.address ?? ""} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
            <div className="space-y-1"><Label>City</Label>
              <Input data-testid="settings-org-city" value={merged.city ?? ""} onChange={(e) => setForm({ ...form, city: e.target.value })} /></div>
            <div className="space-y-1"><Label>State</Label>
              <Select value={merged.state ?? "KA"} onValueChange={(v: string) => setForm({ ...form, state: v })}>
                <SelectTrigger data-testid="settings-org-state"><SelectValue>{(v: string) => states.find((s) => s.code === v)?.name ?? v}</SelectValue></SelectTrigger>
                <SelectContent>{states.map((s) => <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Payroll jurisdiction</Label>
              <Select value={merged.jurisdiction ?? "IN"} onValueChange={(v: string) => setForm({ ...form, jurisdiction: v })}>
                <SelectTrigger data-testid="settings-org-jurisdiction"><SelectValue>{(v: string) => jurisdictions?.find((j) => j.code === v)?.name ?? v}</SelectValue></SelectTrigger>
                <SelectContent>
                  {(jurisdictions ?? []).map((j) => (
                    <SelectItem key={j.code} value={j.code} disabled={j.status !== "active"}>
                      {j.name}{j.status !== "active" ? " — requires statutory verification" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Pay frequency</Label>
              <Select value={merged.payroll_settings?.pay_frequency ?? "monthly"}
                      onValueChange={(v: string) => setForm({ ...form, payroll_settings: { ...merged.payroll_settings!, pay_frequency: v } })}>
                <SelectTrigger data-testid="settings-pay-frequency"><SelectValue>{(v: string) => titleCase(v)}</SelectValue></SelectTrigger>
                <SelectContent><SelectItem value="monthly">Monthly</SelectItem></SelectContent>
              </Select>
            </div>
            <label className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 sm:col-span-2 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              <Checkbox
                checked={merged.payroll_settings?.accept_unverified_statutory_values ?? false}
                onCheckedChange={(c) => setForm({ ...form, payroll_settings: { ...merged.payroll_settings!, accept_unverified_statutory_values: Boolean(c) } })}
                data-testid="settings-accept-unverified"
              />
              Allow payroll to compute with statutory rules marked "Requires statutory verification" (fail-safe refuses otherwise)
            </label>
          </div>
          <Button onClick={() => save.mutate()} disabled={save.isPending} data-testid="settings-save-button">
            {save.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Save settings
          </Button>
        </TabsContent>

        <TabsContent value="users" className="mt-4 space-y-4">
          <Dialog open={userOpen} onOpenChange={setUserOpen}>
            <DialogTrigger render={<Button data-testid="add-user-button"><Plus className="size-4" aria-hidden /> Add user</Button>} />
            <DialogContent className="sm:max-w-md">
              <DialogHeader><DialogTitle>Add organisation user</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <div className="space-y-1"><Label>Name *</Label><Input data-testid="new-user-name" value={userForm.name} onChange={(e) => setUserForm({ ...userForm, name: e.target.value })} /></div>
                <div className="space-y-1"><Label>Email *</Label><Input type="email" data-testid="new-user-email" value={userForm.email} onChange={(e) => setUserForm({ ...userForm, email: e.target.value })} /></div>
                <div className="space-y-1"><Label>Initial password *</Label><Input data-testid="new-user-password" value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} /></div>
                <div className="space-y-1"><Label>Role</Label>
                  <Select value={userForm.role} onValueChange={(v: string) => setUserForm({ ...userForm, role: v })}>
                    <SelectTrigger data-testid="new-user-role"><SelectValue>{(v: string) => titleCase(v.toLowerCase().replace(/_/g, " "))}</SelectValue></SelectTrigger>
                    <SelectContent>{(roles ?? []).filter((r) => r.role !== "SUPER_ADMIN").map((r) => (
                      <SelectItem key={r.role} value={r.role}>{titleCase(r.role.toLowerCase().replace(/_/g, " "))}</SelectItem>
                    ))}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>Link to employee (for self-service logins)</Label>
                  <Select value={userForm.employee_id} onValueChange={(v: string) => setUserForm({ ...userForm, employee_id: v })}>
                    <SelectTrigger data-testid="new-user-employee-link"><SelectValue>{(v: string) => employees?.items.find((e) => e.id === v)?.name ?? "None (admin-only login)"}</SelectValue></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">None (admin-only login)</SelectItem>
                      {(employees?.items ?? []).map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter><Button onClick={() => addUser.mutate()} disabled={addUser.isPending || !userForm.name || !userForm.email || userForm.password.length < 8} data-testid="new-user-save">Add user</Button></DialogFooter>
            </DialogContent>
          </Dialog>

          <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="users-list">
            {(users ?? []).map((u) => (
              <li key={u.id} className="flex items-center justify-between px-4 py-3 text-sm">
                <div>
                  <p className="font-medium">{u.name}</p>
                  <p className="text-xs text-muted-foreground">{u.email}</p>
                </div>
                <span className="rounded-full border border-border bg-muted/60 px-2.5 py-0.5 text-xs font-medium">{titleCase(u.role.toLowerCase().replace(/_/g, " "))}</span>
              </li>
            ))}
          </ul>

          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="mb-3 text-sm font-semibold">Role permissions (backend-enforced)</h3>
            <div className="space-y-3" data-testid="roles-permissions-view">
              {(roles ?? []).map((r) => (
                <details key={r.role} className="rounded-lg border border-border/60 px-3 py-2">
                  <summary className="cursor-pointer text-sm font-medium">{titleCase(r.role.toLowerCase().replace(/_/g, " "))}</summary>
                  <p className="mt-1.5 font-mono text-[11px] leading-relaxed text-muted-foreground">{r.permissions.join(" · ")}</p>
                </details>
              ))}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
