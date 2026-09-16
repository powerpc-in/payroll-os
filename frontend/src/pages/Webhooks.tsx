// Webhooks console: endpoints, event subscriptions (catalog-driven), signed test pings,
// org-wide delivery feed with attempt history, and manual re-delivery of failures.

import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Plus, RefreshCcw, Trash2, Zap } from "lucide-react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type {
  DeliveryFeed, WebhookConfig, WebhookDelivery, WebhookEventInfo,
} from "@/lib/types";
import { dateTimeLabel } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { EmptyState, PageHeader } from "@/components/ui-kit";

interface Scheme {
  header: string;
  format: string;
  timestamp_header: string;
  max_attempts: number;
  note: string;
}

export default function Webhooks() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", url: "", secret: "", events: [] as string[], active: true });

  const { data: hooks, isPending } = useQuery({ queryKey: ["webhooks"], queryFn: () => apiGet<WebhookConfig[]>("/v1/webhooks") });
  const { data: catalog } = useQuery({ queryKey: ["webhook-events"], queryFn: () => apiGet<WebhookEventInfo[]>("/v1/webhooks/events") });
  const { data: scheme } = useQuery({ queryKey: ["webhook-scheme"], queryFn: () => apiGet<Scheme>("/v1/webhooks/signature-scheme") });
  const { data: feed } = useQuery({ queryKey: ["webhook-feed"], queryFn: () => apiGet<DeliveryFeed>("/v1/webhooks/deliveries?limit=50") });
  const { data: deliveries } = useQuery({
    queryKey: ["webhook-deliveries", expanded],
    queryFn: () => apiGet<WebhookDelivery[]>(`/v1/webhooks/${expanded}/deliveries`),
    enabled: !!expanded,
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    queryClient.invalidateQueries({ queryKey: ["webhook-feed"] });
    queryClient.invalidateQueries({ queryKey: ["webhook-deliveries"] });
  };

  const reset = () => { setForm({ name: "", url: "", secret: "", events: [], active: true }); setEditing(null); };

  const create = useMutation({
    mutationFn: () => apiPost("/v1/webhooks", form),
    onSuccess: () => { toast.success("Webhook saved"); invalidateAll(); setOpen(false); reset(); },
    onError: (err) => toast.error(String(err)),
  });
  const update = useMutation({
    mutationFn: () => apiPut(`/v1/webhooks/${editing}`, form),
    onSuccess: () => { toast.success("Webhook updated"); invalidateAll(); setOpen(false); reset(); },
    onError: (err) => toast.error(String(err)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/webhooks/${id}`),
    onSuccess: () => { toast.success("Webhook deleted"); invalidateAll(); },
    onError: (err) => toast.error(String(err)),
  });
  const ping = useMutation({
    mutationFn: (id: string) => apiPost<{ ok: boolean; delivery: WebhookDelivery | null }>(`/v1/webhooks/${id}/test`, {}),
    onSuccess: (res) => {
      if (res.delivery?.success) toast.success(`Delivered — endpoint responded ${res.delivery.status_code}`);
      else toast.error(`Delivery failed after ${res.delivery?.attempts ?? 0} attempt(s): ${res.delivery?.error ?? "no response"} (logged)`);
      invalidateAll();
    },
    onError: (err) => toast.error(String(err)),
  });
  const retry = useMutation({
    mutationFn: (id: string) => apiPost<{ ok: boolean; delivery: WebhookDelivery }>(`/v1/webhooks/deliveries/${id}/retry`, {}),
    onSuccess: (res) => {
      if (res.ok) toast.success("Re-delivered successfully");
      else toast.error(`Retry failed: ${res.delivery.error ?? "no response"}`);
      invalidateAll();
    },
    onError: (err) => toast.error(String(err)),
  });

  const grouped = (catalog ?? []).reduce<Record<string, WebhookEventInfo[]>>((acc, e) => {
    (acc[e.category] ??= []).push(e);
    return acc;
  }, {});

  const deliveryRows = (rows: WebhookDelivery[], testid: string) => (
    <table className="mt-3 w-full text-xs" data-testid={testid}>
      <thead>
        <tr className="border-b border-border text-left text-muted-foreground">
          <th className="py-1">When</th><th>Event</th><th>Result</th>
          <th className="text-right">Attempts</th><th className="text-right">Action</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((d) => (
          <Fragment key={d.id}>
            <tr className="border-b border-border/40">
              <td className="py-1">{dateTimeLabel(d.created_at)}</td>
              <td className="font-mono">{d.event}</td>
              <td>
                {d.success
                  ? <span className="text-emerald-600">{d.status_code ?? "ok"}</span>
                  : <span className="text-red-600">{d.error ?? d.status ?? "failed"}</span>}
              </td>
              <td className="text-right font-mono">{d.attempts}</td>
              <td className="text-right">
                <Button size="sm" variant="ghost" data-testid={`delivery-detail-${d.id.slice(0, 8)}`}
                        onClick={() => setDetail(detail === d.id ? null : d.id)}>Attempts</Button>
                {!d.success ? (
                  <Button size="sm" variant="outline" data-testid={`delivery-retry-${d.id.slice(0, 8)}`}
                          disabled={retry.isPending} onClick={() => retry.mutate(d.id)}>
                    <RefreshCcw className="size-3" aria-hidden /> Retry
                  </Button>
                ) : null}
              </td>
            </tr>
            {detail === d.id ? (
              <tr className="border-b border-border/40 bg-muted/40">
                <td colSpan={5} className="px-2 py-1.5" data-testid={`delivery-attempts-${d.id.slice(0, 8)}`}>
                  {(d.attempt_log ?? []).length === 0 ? <span className="text-muted-foreground">No attempt history recorded.</span> : (
                    <ul className="space-y-0.5 font-mono text-[11px]">
                      {(d.attempt_log ?? []).map((a) => (
                        <li key={a.attempt}>
                          #{a.attempt} · {dateTimeLabel(a.at)} · {a.status_code ?? "no status"}
                          {a.error ? ` · ${a.error}` : ""} · {a.duration_ms}ms
                        </li>
                      ))}
                    </ul>
                  )}
                  {d.next_retry_at && !d.success ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">Retry window opens {dateTimeLabel(d.next_retry_at)} — or retry now.</p>
                  ) : null}
                </td>
              </tr>
            ) : null}
          </Fragment>
        ))}
      </tbody>
    </table>
  );

  return (
    <div>
      <PageHeader
        title="Webhooks & Event Delivery"
        description="Signed outbound events with backoff retries, attempt history and failure handling. Connectors consume the same event catalog."
        testid="webhooks-title"
        actions={
          <Dialog open={open} onOpenChange={(o: boolean) => { setOpen(o); if (!o) reset(); }}>
            <DialogTrigger render={<Button data-testid="add-webhook-button"><Plus className="size-4" aria-hidden /> New webhook</Button>} />
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
              <DialogHeader><DialogTitle>{editing ? "Edit webhook" : "New webhook"}</DialogTitle></DialogHeader>
              <DialogDescription>
                {scheme ? `${scheme.header}: ${scheme.format} · up to ${scheme.max_attempts} attempts per delivery.` : "Deliveries are HMAC-signed."}
              </DialogDescription>
              <div className="space-y-3">
                <div className="space-y-1"><Label>Name *</Label><Input data-testid="webhook-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
                <div className="space-y-1"><Label>URL *</Label><Input data-testid="webhook-url-input" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" /></div>
                <div className="space-y-1"><Label>Secret (min 8 chars) *</Label><Input data-testid="webhook-secret-input" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} /></div>
                <div className="space-y-1.5">
                  <Label>Event subscriptions</Label>
                  <div className="max-h-48 space-y-2 overflow-y-auto rounded-lg border border-border p-2">
                    {Object.entries(grouped).map(([category, list]) => (
                      <div key={category}>
                        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{category}</p>
                        <div className="grid grid-cols-2 gap-1">
                          {list.map((ev) => (
                            <label key={ev.event} className="flex items-center gap-1.5 text-xs">
                              <Checkbox checked={form.events.includes(ev.event)}
                                        data-testid={`webhook-event-${ev.event.replace(/\./g, "-")}`}
                                        onCheckedChange={(c) => setForm({ ...form, events: c ? [...form.events, ev.event] : form.events.filter((x) => x !== ev.event) })} />
                              {ev.event}
                            </label>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={form.active} onCheckedChange={(c) => setForm({ ...form, active: Boolean(c) })} data-testid="webhook-active-checkbox" /> Active
                </label>
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

      {feed ? (
        <div className="mb-4 flex flex-wrap gap-3" data-testid="delivery-counts">
          {(["success", "failed", "pending"] as const).map((k) => (
            <span key={k} className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground">
              {k}: <span className="font-mono font-medium text-foreground" data-testid={`delivery-count-${k}`}>{feed.counts[k]}</span>
            </span>
          ))}
        </div>
      ) : null}

      {isPending ? <div className="h-40 animate-pulse rounded-xl bg-muted" />
        : (hooks?.length ?? 0) === 0 ? (
          <EmptyState icon={<Zap className="size-10" aria-hidden />} title="No webhooks configured"
            description="Register an endpoint to receive signed events like payroll.locked, payslip.generated and ff.settled."
            testid="webhooks-empty" />
        ) : (
          <ul className="space-y-3" data-testid="webhooks-list">
            {hooks!.map((h) => (
              <li key={h.id} className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 font-medium text-foreground">
                      {h.name}
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${h.active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>
                        {h.active ? "active" : "inactive"}
                      </span>
                      {(h.failed_deliveries ?? 0) > 0 ? (
                        <span className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] text-red-700" data-testid={`webhook-failures-${h.id.slice(0, 8)}`}>
                          {h.failed_deliveries} failed
                        </span>
                      ) : null}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{h.url}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{h.events.join(" · ")}</p>
                    {h.last_error ? <p className="mt-1 text-[11px] text-red-600">Last error: {h.last_error}</p> : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" data-testid={`webhook-test-${h.id.slice(0, 8)}`} onClick={() => ping.mutate(h.id)} disabled={ping.isPending}>
                      {ping.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Send test
                    </Button>
                    <Button size="sm" variant="outline" data-testid={`webhook-deliveries-${h.id.slice(0, 8)}`} onClick={() => setExpanded(expanded === h.id ? null : h.id)}>Deliveries</Button>
                    <Button size="sm" variant="ghost" data-testid={`webhook-edit-${h.id.slice(0, 8)}`}
                            onClick={() => { setEditing(h.id); setForm({ name: h.name, url: h.url, secret: h.secret ?? "", events: h.events, active: h.active }); setOpen(true); }}>Edit</Button>
                    <Button size="sm" variant="ghost" aria-label="Delete" data-testid={`webhook-delete-${h.id.slice(0, 8)}`} onClick={() => remove.mutate(h.id)}>
                      <Trash2 className="size-4" aria-hidden />
                    </Button>
                  </div>
                </div>
                {expanded === h.id ? (
                  deliveries && deliveries.length > 0
                    ? deliveryRows(deliveries, `delivery-log-${h.id.slice(0, 8)}`)
                    : <p className="mt-2 text-xs text-muted-foreground">No deliveries yet — send a test ping.</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}

      {feed && feed.items.length > 0 ? (
        <div className="mt-6 rounded-xl border border-border bg-card p-4" data-testid="delivery-feed">
          <h2 className="font-heading text-base font-semibold">Recent deliveries (all endpoints)</h2>
          {deliveryRows(feed.items, "delivery-feed-table")}
        </div>
      ) : null}
    </div>
  );
}
