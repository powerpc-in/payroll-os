// Webhooks console: endpoints, event selection, signed test pings, delivery log.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, Trash2, Zap } from "lucide-react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type { WebhookConfig, WebhookDelivery } from "@/lib/types";
import { dateTimeLabel } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { EmptyState, PageHeader } from "@/components/ui-kit";

export default function Webhooks() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", url: "", secret: "", events: [] as string[], active: true });

  const { data: hooks, isPending } = useQuery({ queryKey: ["webhooks"], queryFn: () => apiGet<WebhookConfig[]>("/v1/webhooks") });
  const { data: availableEvents } = useQuery({ queryKey: ["webhook-events"], queryFn: () => apiGet<string[]>("/v1/webhooks/events") });
  const { data: deliveries } = useQuery({
    queryKey: ["webhook-deliveries", editing],
    queryFn: () => apiGet<WebhookDelivery[]>(`/v1/webhooks/${editing}/deliveries`),
    enabled: !!editing,
  });

  const create = useMutation({
    mutationFn: () => apiPost("/v1/webhooks", form),
    onSuccess: () => { toast.success("Webhook saved"); queryClient.invalidateQueries({ queryKey: ["webhooks"] }); setOpen(false); reset(); },
    onError: (err) => toast.error(String(err)),
  });

  const update = useMutation({
    mutationFn: () => apiPut(`/v1/webhooks/${editing}`, form),
    onSuccess: () => { toast.success("Webhook updated"); queryClient.invalidateQueries({ queryKey: ["webhooks"] }); setEditing(null); reset(); },
    onError: (err) => toast.error(String(err)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/webhooks/${id}`),
    onSuccess: () => { toast.success("Webhook deleted"); queryClient.invalidateQueries({ queryKey: ["webhooks"] }); },
    onError: (err) => toast.error(String(err)),
  });

  const ping = useMutation({
    mutationFn: (id: string) => apiPost<{ ok: boolean; delivery: WebhookDelivery | null }>(`/v1/webhooks/${id}/test`, {}),
    onSuccess: (res, id) => {
      const d = res.delivery;
      if (d?.success) toast.success("Test delivered — endpoint responded 2xx");
      else toast.error(`Test failed: ${d?.error ?? "no response"} (logged)`);
      queryClient.invalidateQueries({ queryKey: ["webhook-deliveries", id] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const reset = () => setForm({ name: "", url: "", secret: "", events: [], active: true });

  return (
    <div>
      <PageHeader
        title="Webhooks"
        description="Signed outbound events with retries and a full delivery log. Failed endpoints never block business actions."
        testid="webhooks-title"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="add-webhook-button"><Plus className="size-4" aria-hidden /> New webhook</Button>} />
            <DialogContent className="sm:max-w-md">
              <DialogHeader><DialogTitle>{editing ? "Edit webhook" : "New webhook"}</DialogTitle></DialogHeader>
              <DialogDescription>Deliveries are signed with HMAC-SHA256 in the X-Webhook-Signature header.</DialogDescription>
              <div className="space-y-3">
                <div className="space-y-1"><Label>Name *</Label><Input data-testid="webhook-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
                <div className="space-y-1"><Label>URL *</Label><Input data-testid="webhook-url-input" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" /></div>
                <div className="space-y-1"><Label>Secret (min 8 chars) *</Label><Input data-testid="webhook-secret-input" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} /></div>
                <div className="space-y-1.5">
                  <Label>Events</Label>
                  <div className="grid max-h-40 grid-cols-2 gap-1 overflow-y-auto rounded-lg border border-border p-2">
                    {(availableEvents ?? []).map((ev) => (
                      <label key={ev} className="flex items-center gap-1.5 text-xs">
                        <Checkbox checked={form.events.includes(ev)}
                                  onCheckedChange={(c) => setForm({ ...form, events: c ? [...form.events, ev] : form.events.filter((x) => x !== ev) })}
                                  data-testid={`webhook-event-${ev.replace(/\./g, "-")}`} />
                        {ev}
                      </label>
                    ))}
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={form.active} onCheckedChange={(c) => setForm({ ...form, active: Boolean(c) })} data-testid="webhook-active-checkbox" /> Active</label>
              </div>
              <DialogFooter>
                <Button onClick={() => (editing ? update.mutate() : create.mutate())}
                        disabled={create.isPending || update.isPending || !form.name || !form.url || form.secret.length < 8 || form.events.length === 0}
                        data-testid="webhook-save-button">Save webhook</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      {isPending ? <div className="h-40 animate-pulse rounded-xl bg-muted" />
        : (hooks?.length ?? 0) === 0 ? (
          <EmptyState icon={<Zap className="size-10" aria-hidden />} title="No webhooks configured"
            description="Register an endpoint to receive signed events like payroll.locked and employee.created." testid="webhooks-empty" />
        ) : (
          <ul className="space-y-3" data-testid="webhooks-list">
            {hooks!.map((h) => (
              <li key={h.id} className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 font-medium text-foreground">
                      {h.name}
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${h.active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>{h.active ? "active" : "inactive"}</span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{h.url}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{h.events.join(" · ")}</p>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" data-testid={`webhook-test-${h.id.slice(0, 8)}`} onClick={() => ping.mutate(h.id)} disabled={ping.isPending}>
                      {ping.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Send test
                    </Button>
                    <Button size="sm" variant="outline" data-testid={`webhook-deliveries-${h.id.slice(0, 8)}`} onClick={() => setEditing(editing === h.id ? null : h.id)}>Deliveries</Button>
                    <Button size="sm" variant="ghost" aria-label="Edit" data-testid={`webhook-edit-${h.id.slice(0, 8)}`} onClick={() => { setEditing(h.id); setForm({ name: h.name, url: h.url, secret: h.secret ?? "", events: h.events, active: h.active }); setOpen(true); }}>Edit</Button>
                    <Button size="sm" variant="ghost" aria-label="Delete" data-testid={`webhook-delete-${h.id.slice(0, 8)}`} onClick={() => remove.mutate(h.id)}><Trash2 className="size-4" aria-hidden /></Button>
                  </div>
                </div>
                {editing === h.id ? (
                  deliveries && deliveries.length > 0 ? (
                    <table className="mt-3 w-full text-xs" data-testid={`delivery-log-${h.id.slice(0, 8)}`}>
                      <thead><tr className="border-b border-border text-left text-muted-foreground"><th className="py-1">When</th><th>Event</th><th>Status</th><th className="text-right">Attempts</th></tr></thead>
                      <tbody>
                        {deliveries.map((d) => (
                          <tr key={d.id} className="border-b border-border/40 last:border-b-0">
                            <td className="py-1">{dateTimeLabel(d.created_at)}</td>
                            <td className="font-mono">{d.event}</td>
                            <td>{d.success ? <span className="text-emerald-600">{d.status_code ?? "ok"}</span> : <span className="text-red-600">{d.error ?? "failed"}</span>}</td>
                            <td className="text-right font-mono">{d.attempts}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : <p className="mt-2 text-xs text-muted-foreground">No deliveries yet.</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
