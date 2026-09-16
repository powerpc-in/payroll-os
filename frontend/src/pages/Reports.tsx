// Report builder: dataset → fields → filters → grouping → sorting → run → export.
// Saved reports persist configurations. All data comes from the reporting engine
// on the backend (server-side aggregation).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bookmark, FileDown, Loader2, Play } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { ReportDataset, ReportResult, SavedReport } from "@/lib/types";
import { inr } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageHeader } from "@/components/ui-kit";

interface ReportConfig {
  dataset: string;
  period_from: string;
  period_to: string;
  department: string;
  location: string;
  group_by: string;
  sort_by: string;
  sort_dir: string;
}

const EMPTY: ReportConfig = { dataset: "payroll_register", period_from: "", period_to: "", department: "", location: "", group_by: "", sort_by: "", sort_dir: "asc" };

async function downloadExport(config: ReportConfig, format: string) {
  const res = await fetch(`/api/v1/reports/export?format=${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...config, dataset: config.dataset }),
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${config.dataset}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Reports() {
  const queryClient = useQueryClient();
  const [config, setConfig] = useState<ReportConfig>(EMPTY);
  const [result, setResult] = useState<ReportResult | null>(null);
  const [running, setRunning] = useState(false);
  const [saveName, setSaveName] = useState("");

  const { data: datasets } = useQuery({ queryKey: ["report-datasets"], queryFn: () => apiGet<ReportDataset[]>("/v1/reports/datasets") });
  const { data: saved } = useQuery({ queryKey: ["saved-reports"], queryFn: () => apiGet<SavedReport[]>("/v1/reports/saved") });

  const current = datasets?.find((d) => d.key === config.dataset);
  const groupable = ["", "department", "location", "cost_centre", "employee_code", "period"];

  const run = async () => {
    setRunning(true);
    try {
      const res = await apiPost<ReportResult>("/v1/reports/run", { ...config, limit: 500 });
      setResult(res);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setRunning(false);
    }
  };

  const save = useMutation({
    mutationFn: () => apiPost("/v1/reports/saved", { name: saveName, config }),
    onSuccess: () => { toast.success("Report saved"); queryClient.invalidateQueries({ queryKey: ["saved-reports"] }); setSaveName(""); },
    onError: (err) => toast.error(String(err)),
  });

  const set = (patch: Partial<ReportConfig>) => setConfig({ ...config, ...patch });

  return (
    <div>
      <PageHeader title="Reports & Analytics" description="Reusable reporting engine — filter, group, aggregate and export any payroll dataset." testid="reports-title" />

      <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
        {/* Builder panel */}
        <div className="space-y-4 rounded-xl border border-border bg-card p-5" data-testid="report-builder">
          <div className="space-y-1">
            <Label>Dataset</Label>
            <Select value={config.dataset} onValueChange={(v: string) => { set({ dataset: v }); setResult(null); }}>
              <SelectTrigger data-testid="report-dataset-select"><SelectValue>{(v: string) => datasets?.find((d) => d.key === v)?.name ?? v}</SelectValue></SelectTrigger>
              <SelectContent>
                {(datasets ?? []).map((d) => <SelectItem key={d.key} value={d.key}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {current?.time_field ? (
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><Label>Period from</Label><Input type="month" data-testid="report-period-from" value={config.period_from} onChange={(e) => set({ period_from: e.target.value })} /></div>
              <div className="space-y-1"><Label>Period to</Label><Input type="month" data-testid="report-period-to" value={config.period_to} onChange={(e) => set({ period_to: e.target.value })} /></div>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1"><Label>Department</Label><Input data-testid="report-department" placeholder="exact name" value={config.department} onChange={(e) => set({ department: e.target.value })} /></div>
            <div className="space-y-1"><Label>Location</Label><Input data-testid="report-location" placeholder="exact name" value={config.location} onChange={(e) => set({ location: e.target.value })} /></div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1"><Label>Group by</Label>
              <Select value={config.group_by} onValueChange={(v: string) => set({ group_by: v })}>
                <SelectTrigger data-testid="report-group-by"><SelectValue>{(v: string) => v ? v.replace(/_/g, " ") : "None"}</SelectValue></SelectTrigger>
                <SelectContent>{groupable.map((g) => <SelectItem key={g} value={g}>{g ? g.replace(/_/g, " ") : "None"}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Sort by</Label>
              <Select value={config.sort_by} onValueChange={(v: string) => set({ sort_by: v })}>
                <SelectTrigger data-testid="report-sort-by"><SelectValue>{(v: string) => v ? current?.fields.find((f) => f.key === v)?.label ?? v : "Default"}</SelectValue></SelectTrigger>
                <SelectContent>
                  <SelectItem value="">Default</SelectItem>
                  {(current?.fields ?? []).map((f) => <SelectItem key={f.key} value={f.key}>{f.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <Button className="w-full" onClick={run} disabled={running} data-testid="report-run-button">
            {running ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />} Run report
          </Button>
          <div className="flex gap-2">
            {["csv", "xlsx", "pdf"].map((fmt) => (
              <Button key={fmt} variant="outline" size="sm" className="flex-1"
                      data-testid={`report-export-${fmt}`}
                      onClick={() => downloadExport(config, fmt).catch((e) => toast.error(String(e)))}>
                <FileDown className="size-3.5" aria-hidden /> {fmt.toUpperCase()}
              </Button>
            ))}
          </div>
          <div className="space-y-1 border-t border-border pt-3">
            <Label>Save this configuration</Label>
            <div className="flex gap-2">
              <Input placeholder="e.g. Monthly payroll by department" data-testid="report-save-name" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
              <Button variant="outline" size="sm" onClick={() => save.mutate()} disabled={!saveName || save.isPending} data-testid="report-save-button">
                <Bookmark className="size-4" aria-hidden />
              </Button>
            </div>
          </div>
          {(saved?.length ?? 0) > 0 ? (
            <div className="space-y-1.5 border-t border-border pt-3">
              <Label>Saved reports</Label>
              {saved!.map((s) => (
                <button key={s.id} data-testid={`saved-report-${s.id.slice(0, 8)}`}
                        className="w-full rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                        onClick={() => setConfig({ ...EMPTY, ...(s.config as unknown as ReportConfig) })}>
                  {s.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {/* Results */}
        <div className="min-w-0">
          {result ? (
            <div data-testid="report-results">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-heading text-lg font-semibold">{result.name}</h2>
                <span className="text-xs text-muted-foreground">{result.count} row(s)</span>
              </div>
              <div className="overflow-x-auto rounded-xl border border-border bg-card">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/50 text-xs uppercase tracking-wider text-muted-foreground">
                      {result.columns.map((c) => (
                        <th key={c} className={`px-4 py-2.5 ${result.labels[c] && (current?.fields.find((f) => f.key === c)?.numeric) ? "text-right" : "text-left"} font-semibold`}>
                          {current?.fields.find((f) => f.key === c)?.label ?? c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i} className="border-b border-border/60 last:border-b-0 hover:bg-muted/40">
                        {result.columns.map((c) => {
                          const numeric = current?.fields.find((f) => f.key === c)?.numeric;
                          return (
                            <td key={c} className={`px-4 py-2 ${numeric ? "text-right font-mono tabular-nums" : ""}`}>
                              {numeric ? inr(Number(row[c] ?? 0), 2) : String(row[c] ?? "—")}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {Object.keys(result.totals).length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-4 rounded-xl border border-border bg-muted/40 px-4 py-3" data-testid="report-totals">
                  {Object.entries(result.totals).map(([k, v]) => (
                    <span key={k} className="text-xs text-muted-foreground">
                      {current?.fields.find((f) => f.key === k)?.label ?? k}: <span className="font-mono font-medium tabular-nums text-foreground">{inr(v, 2)}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title="Choose a dataset and run"
              description="Try 'Payroll Register' filtered to a month, or group 'Net Pay' by department."
              testid="reports-empty"
            />
          )}
        </div>
      </div>
    </div>
  );
}
