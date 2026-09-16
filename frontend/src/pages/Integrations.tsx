// Integration framework UI: provider registry, connections, real credential
// tests, field mappings and honest sync jobs (never a fabricated success).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Loader2, Plug, PlugZap, Trash2, XCircle } from "lucide-react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type { IntegrationConnection, IntegrationProvider, SyncLog } from "@/lib/types";
import { dateTimeLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState, PageHeader } from "@/components/ui-kit";

export default function Integrations() {
  const queryClient = useQueryClient();
  const [connectProvider, setConnectProvider] = useState<IntegrationProvider | null>(null);
  const [config, setConfig] = useState<Record<string, string>>({});
  const [mappingConn, setMappingConn] = useState<IntegrationConnection | null>(null);
  const [mappingJson, setMappingJson] = useState("{}");
  const [mappingObject, setMappingObject] = useState("Employee");
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string } | null>(null);

  const { data: providers } = useQuery({ queryKey: ["integration-providers"], queryFn: () => apiGet<IntegrationProvider[]>("/v1/integrations/providers") });
  const { data: connections, isPending } = useQuery({ queryKey: ["integration-connections"], queryFn: () => apiGet<IntegrationConnection[]>("/v1/integrations/connections") });
  const { data: logs } = useQuery({
    queryKey: ["integration-logs", mappingConn?.id],
    queryFn: () => apiGet<SyncLog[]>(`/v1/integrations/connections/${mappingConn!.id}/logs`),
    enabled: !!mappingConn,
  });

  const connect = useMutation({
    mutationFn: () => apiPost<IntegrationConnection>("/v1/integrations/connections", { provider: connectProvider!.key, config }),
    onSuccess: () => {
      toast.success("Connection saved — run a test before enabling sync");
      queryClient.invalidateQueries({ queryKey: ["integration-connections"] });
      setConnectProvider(null); setConfig({});
    },
    onError: (err) => toast.error(String(err)),
  });

  const test = useMutation({
    mutationFn: (id: string) => apiPost<{ success: boolean; message: string }>(`/v1/integrations/connections/${id}/test`, {}),
    onSuccess: (res, id) => {
      setTestResult({ id, ...res });
      toast[res.success ? "success" : "error"](res.message);
      queryClient.invalidateQueries({ queryKey: ["integration-connections"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const sync = useMutation({
    mutationFn: (id: string) => apiPost<{ status: string; reason: string }>(`/v1/integrations/connections/${id}/sync`, { object: "Employee" }),
    onSuccess: (res) => toast.warning(`${titleCase(res.status)} — ${res.reason}`),
    onError: (err) => toast.error(String(err)),
  });

  const saveMapping = useMutation({
    mutationFn: () => apiPut(`/v1/integrations/connections/${mappingConn!.id}/mapping`, {
      object: mappingObject, field_map: JSON.parse(mappingJson),
    }),
    onSuccess: () => { toast.success("Field mapping saved"); queryClient.invalidateQueries({ queryKey: ["integration-connections"] }); setMappingConn(null); },
    onError: (err) => toast.error(String(err)),
  });

  const disconnect = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/integrations/connections/${id}`),
    onSuccess: () => { toast.success("Connection removed"); queryClient.invalidateQueries({ queryKey: ["integration-connections"] }); },
    onError: (err) => toast.error(String(err)),
  });

  return (
    <div>
      <PageHeader
        title="Integrations"
        description="Provider adapters connect through the integration layer — never directly to the database."
        testid="integrations-title"
      />

      <div className="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="provider-grid">
        {(providers ?? []).map((p) => (
          <div key={p.key} className="flex flex-col rounded-xl border border-border bg-card p-5">
            <div className="flex items-center justify-between">
              <p className="font-medium text-foreground" data-testid={`provider-${p.key}`}>{p.name}</p>
              <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${p.status === "available" ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>
                {p.status === "available" ? "Available" : "Planned"}
              </span>
            </div>
            <p className="mt-1 flex-1 text-xs leading-relaxed text-muted-foreground">{p.description}</p>
            {p.status === "available" ? (
              <Button size="sm" className="mt-3 w-fit" data-testid={`connect-${p.key}`}
                      onClick={() => { setConnectProvider(p); setConfig({}); }}>
                <Plug className="size-4" aria-hidden /> Connect
              </Button>
            ) : (
              <p className="mt-3 text-[11px] italic text-muted-foreground">Connector slot reserved — requires configuration.</p>
            )}
          </div>
        ))}
      </div>

      <h2 className="mb-3 font-heading text-base font-semibold">Your connections</h2>
      {isPending ? <div className="h-32 animate-pulse rounded-xl bg-muted" />
        : (connections?.length ?? 0) === 0 ? (
          <EmptyState icon={<PlugZap className="size-10" aria-hidden />} title="No connections yet"
            description="Salesforce and Zoho connectors are available — connect with credentials to test. No sync is ever simulated." testid="integrations-empty" />
        ) : (
          <ul className="space-y-3" data-testid="connections-list">
            {connections!.map((c) => (
              <li key={c.id} className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-foreground">{c.name} <span className="text-xs font-normal text-muted-foreground">({c.provider})</span></p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {c.status === "connected"
                        ? "Connected — credentials verified with the provider"
                        : c.status === "configured_unverified"
                          ? "Credentials saved but not yet tested"
                          : "Requires configuration — add credentials, then test"}
                      {c.last_tested_at ? ` · last tested ${dateTimeLabel(c.last_tested_at)}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" data-testid={`test-connection-${c.id.slice(0, 8)}`}
                            onClick={() => test.mutate(c.id)} disabled={test.isPending}>
                      {test.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Test connection
                    </Button>
                    <Button size="sm" variant="outline" data-testid={`map-fields-${c.id.slice(0, 8)}`}
                            onClick={() => { setMappingConn(c); setMappingJson(JSON.stringify(c.mappings[0]?.field_map ?? {}, null, 2)); }}>
                      Field mapping
                    </Button>
                    <Button size="sm" variant="ghost" data-testid={`request-sync-${c.id.slice(0, 8)}`} onClick={() => sync.mutate(c.id)}>Sync</Button>
                    <Button size="sm" variant="ghost" aria-label="Disconnect" data-testid={`disconnect-${c.id.slice(0, 8)}`} onClick={() => disconnect.mutate(c.id)}>
                      <Trash2 className="size-4" aria-hidden />
                    </Button>
                  </div>
                </div>
                {testResult?.id === c.id ? (
                  <p className={`mt-2 flex items-center gap-1.5 text-xs ${testResult.success ? "text-emerald-600" : "text-red-600"}`} data-testid={`connection-test-result-${c.id.slice(0, 8)}`}>
                    {testResult.success ? <CheckCircle2 className="size-3.5" aria-hidden /> : <XCircle className="size-3.5" aria-hidden />}
                    {testResult.message}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}

      {/* Connect dialog */}
      <Dialog open={!!connectProvider} onOpenChange={(o) => !o && setConnectProvider(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>Connect {connectProvider?.name}</DialogTitle></DialogHeader>
          <DialogDescription>
            Credentials are stored server-side and never echoed back. Secrets: {connectProvider?.config_fields.filter((f) => f.secret).map((f) => f.label).join(", ") || "none"}.
          </DialogDescription>
          <div className="space-y-3">
            {(connectProvider?.config_fields ?? []).map((f) => (
              <div key={f.key} className="space-y-1">
                <Label>{f.label}</Label>
                <Input
                  type={f.secret ? "password" : "text"}
                  data-testid={`integration-config-${f.key}`}
                  value={config[f.key] ?? ""}
                  onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}
                />
              </div>
            ))}
          </div>
          <DialogFooter><Button onClick={() => connect.mutate()} disabled={connect.isPending} data-testid="integration-connect-save">Save connection</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Mapping dialog */}
      <Dialog open={!!mappingConn} onOpenChange={(o) => !o && setMappingConn(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>Field mapping — {mappingConn?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><Label>Object</Label>
              <Input value={mappingObject} data-testid="mapping-object-input" onChange={(e) => setMappingObject(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Field map (JSON: platform field → provider field)</Label>
              <textarea data-testid="mapping-json-input" rows={6}
                        className="w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs"
                        value={mappingJson} onChange={(e) => setMappingJson(e.target.value)} />
            </div>
          </div>
          {logs && logs.length > 0 ? (
            <div className="max-h-32 overflow-y-auto rounded-lg border border-border p-2 text-[11px] text-muted-foreground" data-testid="integration-logs">
              {logs.map((l) => <p key={l.id}>{dateTimeLabel(l.created_at)} · {l.kind} · {l.success ? "ok" : "failed"} — {l.message}</p>)}
            </div>
          ) : null}
          <DialogFooter><Button onClick={() => saveMapping.mutate()} disabled={saveMapping.isPending} data-testid="mapping-save-button">Save mapping</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
