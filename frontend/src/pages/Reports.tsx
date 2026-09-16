// Report builder: dataset → fields → filters → grouping → aggregation → sorting →
// visualization → run → export → save. All aggregation happens server-side in the
// reporting engine; saved reports store configurations and re-run against live data.

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BarChart3, Bookmark, FileDown, Loader2, Play, Plus, Table2, Trash2, X } from "lucide-react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type { ReportCatalog, ReportResult, SavedReport } from "@/lib/types";
import { inr } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "@/lib/recharts";

interface FilterRow { field: string; op: string; value: string }

interface ReportConfig {
  dataset: string;
  fields: string[];
  filters: FilterRow[];
  period_from: string;
  period_to: string;
  department: string;
  location: string;
  group_by: string;
  aggregate: string;
  sort_by: string;
  sort_dir: string;
}

const EMPTY: ReportConfig = {
  dataset: "payroll_register", fields: [], filters: [], period_from: "", period_to: "",
  department: "", location: "", group_by: "", aggregate: "sum", sort_by: "", sort_dir: "asc",
};

const OP_LABELS: Record<string, string> = {
  eq: "is", ne: "is not", contains: "contains", gt: ">", gte: "≥", lt: "<", lte: "≤",
};

function toBody(config: ReportConfig) {
  return {
    ...config,
    fields: config.fields.length ? config.fields : null,
    filters: config.filters.filter((f) => f.field && f.value !== ""),
    limit: 500,
  };
}

async function downloadExport(config: ReportConfig, format: string) {
  const res = await fetch(`/api/v1/reports/export?format=${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toBody(config)),
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
  const [visualization, setVisualization] = useState<"table" | "bar">("table");
  const [activeSaved, setActiveSaved] = useState<string | null>(null);

  const { data: catalog } = useQuery({
    queryKey: ["report-catalog"],
    queryFn: () => apiGet<ReportCatalog>("/v1/reports/datasets"),
  });
  const { data: saved } = useQuery({
    queryKey: ["saved-reports"],
    queryFn: () => apiGet<SavedReport[]>("/v1/reports/saved"),
  });

  const datasets = catalog?.datasets ?? [];
  const current = datasets.find((d) => d.key === config.dataset);
  const set = (patch: Partial<ReportConfig>) => setConfig((c) => ({ ...c, ...patch }));

  const isNumeric = (key: string) => (result?.numeric ?? []).includes(key);
  const isCount = (key: string) => key === "headcount";
  const cell = (key: string, value: unknown) => {
    if (isCount(key)) return String(Number(value ?? 0));
    return isNumeric(key) ? inr(Number(value ?? 0), 2) : String(value ?? "—");
  };
  const label = (key: string) =>
    result?.labels[key] ?? current?.fields.find((f) => f.key === key)?.label ?? key;

  const chartData = useMemo(() => {
    if (!result || !result.group_by) return [];
    const valueKey = result.columns.find((c) => c !== "group" && c !== "headcount");
    if (!valueKey) return [];
    return result.rows.slice(0, 15).map((row) => ({
      name: String(row.group ?? "—"),
      value: Number(row[valueKey] ?? 0),
      valueKey,
    }));
  }, [result]);

  const run = async () => {
    setRunning(true);
    try {
      setResult(await apiPost<ReportResult>("/v1/reports/run", toBody(config)));
    } catch (err) {
      toast.error(String(err));
    } finally {
      setRunning(false);
    }
  };

  const save = useMutation({
    mutationFn: () =>
      activeSaved
        ? apiPut(`/v1/reports/saved/${activeSaved}`, { name: saveName, config, visualization })
        : apiPost("/v1/reports/saved", { name: saveName, config, visualization }),
    onSuccess: () => {
      toast.success(activeSaved ? "Saved report updated" : "Report saved");
      queryClient.invalidateQueries({ queryKey: ["saved-reports"] });
      setSaveName("");
    },
    onError: (err) => toast.error(String(err)),
  });

  const removeSaved = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/reports/saved/${id}`),
    onSuccess: () => {
      toast.success("Saved report deleted");
      queryClient.invalidateQueries({ queryKey: ["saved-reports"] });
      setActiveSaved(null);
    },
    onError: (err) => toast.error(String(err)),
  });

  const runSaved = useMutation({
    mutationFn: (id: string) => apiPost<ReportResult>(`/v1/reports/saved/${id}/run`, {}),
    onSuccess: (res, id) => {
      const s = saved?.find((x) => x.id === id);
      if (s) {
        setConfig({ ...EMPTY, ...(s.config as unknown as ReportConfig) });
        setSaveName(s.name);
        setVisualization(s.visualization === "bar" ? "bar" : "table");
      }
      setActiveSaved(id);
      setResult(res);
    },
    onError: (err) => toast.error(String(err)),
  });

  return (
    <div>
      <PageHeader
        title="Reports & Report Builder"
        description="One reusable engine: pick a dataset, choose fields, filter, group, aggregate, sort, visualize, export and save the configuration."
        testid="reports-title"
      />

      <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
        <div className="space-y-4 rounded-xl border border-border bg-card p-5" data-testid="report-builder">
          <div className="space-y-1">
            <Label>Dataset</Label>
            <Select value={config.dataset} onValueChange={(v: string) => { setConfig({ ...EMPTY, dataset: v }); setResult(null); setActiveSaved(null); }}>
              <SelectTrigger data-testid="report-dataset-select">
                <SelectValue>{(v: string) => datasets.find((d) => d.key === v)?.name ?? v}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {datasets.map((d) => <SelectItem key={d.key} value={d.key}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label>Fields {config.fields.length ? `(${config.fields.length} selected)` : "(all)"}</Label>
            <div className="grid max-h-36 grid-cols-1 gap-1 overflow-y-auto rounded-lg border border-border p-2" data-testid="report-field-picker">
              {(current?.fields ?? []).map((f) => (
                <label key={f.key} className="flex items-center gap-2 text-xs">
                  <Checkbox checked={config.fields.length === 0 || config.fields.includes(f.key)}
                            data-testid={`report-field-${f.key}`}
                            onCheckedChange={(c) => {
                              const base = config.fields.length ? config.fields : (current?.fields ?? []).map((x) => x.key);
                              set({ fields: c ? Array.from(new Set([...base, f.key])) : base.filter((k) => k !== f.key) });
                            }} />
                  {f.label}
                </label>
              ))}
            </div>
          </div>

          {current?.time_field ? (
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><Label>Period from</Label><Input type="month" data-testid="report-period-from" value={config.period_from} onChange={(e) => set({ period_from: e.target.value })} /></div>
              <div className="space-y-1"><Label>Period to</Label><Input type="month" data-testid="report-period-to" value={config.period_to} onChange={(e) => set({ period_to: e.target.value })} /></div>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label>Filters</Label>
              <Button size="sm" variant="ghost" data-testid="report-add-filter"
                      onClick={() => set({ filters: [...config.filters, { field: current?.fields[0]?.key ?? "", op: "eq", value: "" }] })}>
                <Plus className="size-3.5" aria-hidden /> Add
              </Button>
            </div>
            {config.filters.map((f, i) => (
              <div key={i} className="flex items-center gap-1.5" data-testid={`report-filter-${i}`}>
                <Select value={f.field} onValueChange={(v: string) => set({ filters: config.filters.map((x, j) => (j === i ? { ...x, field: v } : x)) })}>
                  <SelectTrigger className="flex-1" data-testid={`report-filter-field-${i}`}>
                    <SelectValue>{(v: string) => current?.fields.find((x) => x.key === v)?.label ?? "Field"}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>{(current?.fields ?? []).map((x) => <SelectItem key={x.key} value={x.key}>{x.label}</SelectItem>)}</SelectContent>
                </Select>
                <Select value={f.op} onValueChange={(v: string) => set({ filters: config.filters.map((x, j) => (j === i ? { ...x, op: v } : x)) })}>
                  <SelectTrigger className="w-24" data-testid={`report-filter-op-${i}`}>
                    <SelectValue>{(v: string) => OP_LABELS[v] ?? v}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>{(catalog?.filter_ops ?? []).map((op) => <SelectItem key={op} value={op}>{OP_LABELS[op] ?? op}</SelectItem>)}</SelectContent>
                </Select>
                <Input className="w-24" placeholder="value" data-testid={`report-filter-value-${i}`} value={f.value}
                       onChange={(e) => set({ filters: config.filters.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)) })} />
                <Button size="sm" variant="ghost" aria-label="Remove filter" data-testid={`report-filter-remove-${i}`}
                        onClick={() => set({ filters: config.filters.filter((_, j) => j !== i) })}><X className="size-3.5" aria-hidden /></Button>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1"><Label>Group by</Label>
              <Select value={config.group_by} onValueChange={(v: string) => set({ group_by: v })}>
                <SelectTrigger data-testid="report-group-by"><SelectValue>{(v: string) => (v ? v.replace(/_/g, " ") : "None")}</SelectValue></SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {["department", "location", "cost_centre", "employee_code", "period", "state", "status"].map((g) => (
                    <SelectItem key={g} value={g}>{g.replace(/_/g, " ")}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Aggregation</Label>
              <Select value={config.aggregate} onValueChange={(v: string) => set({ aggregate: v })}>
                <SelectTrigger data-testid="report-aggregate"><SelectValue>{(v: string) => v}</SelectValue></SelectTrigger>
                <SelectContent>{(catalog?.aggregations ?? ["sum"]).map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1"><Label>Sort by</Label>
              <Select value={config.sort_by} onValueChange={(v: string) => set({ sort_by: v })}>
                <SelectTrigger data-testid="report-sort-by"><SelectValue>{(v: string) => (v ? current?.fields.find((f) => f.key === v)?.label ?? v : "Default")}</SelectValue></SelectTrigger>
                <SelectContent>
                  <SelectItem value="">Default</SelectItem>
                  {(current?.fields ?? []).map((f) => <SelectItem key={f.key} value={f.key}>{f.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Direction</Label>
              <Select value={config.sort_dir} onValueChange={(v: string) => set({ sort_dir: v })}>
                <SelectTrigger data-testid="report-sort-dir"><SelectValue>{(v: string) => (v === "desc" ? "Descending" : "Ascending")}</SelectValue></SelectTrigger>
                <SelectContent><SelectItem value="asc">Ascending</SelectItem><SelectItem value="desc">Descending</SelectItem></SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label>Visualization</Label>
            <div className="flex gap-2">
              <Button variant={visualization === "table" ? "default" : "outline"} size="sm" className="flex-1"
                      data-testid="report-viz-table" onClick={() => setVisualization("table")}>
                <Table2 className="size-3.5" aria-hidden /> Table
              </Button>
              <Button variant={visualization === "bar" ? "default" : "outline"} size="sm" className="flex-1"
                      data-testid="report-viz-bar" onClick={() => setVisualization("bar")}>
                <BarChart3 className="size-3.5" aria-hidden /> Bar
              </Button>
            </div>
          </div>

          <Button className="w-full" onClick={run} disabled={running} data-testid="report-run-button">
            {running ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />} Run report
          </Button>

          <div className="flex gap-2">
            {["csv", "xlsx", "pdf"].map((fmt) => (
              <Button key={fmt} variant="outline" size="sm" className="flex-1" data-testid={`report-export-${fmt}`}
                      onClick={() => downloadExport(config, fmt).catch((e) => toast.error(String(e)))}>
                <FileDown className="size-3.5" aria-hidden /> {fmt.toUpperCase()}
              </Button>
            ))}
          </div>

          <div className="space-y-1 border-t border-border pt-3">
            <Label>{activeSaved ? "Update saved report" : "Save this configuration"}</Label>
            <div className="flex gap-2">
              <Input placeholder="e.g. Monthly payroll by department" data-testid="report-save-name"
                     value={saveName} onChange={(e) => setSaveName(e.target.value)} />
              <Button variant="outline" size="sm" onClick={() => save.mutate()} disabled={!saveName || save.isPending} data-testid="report-save-button">
                <Bookmark className="size-4" aria-hidden />
              </Button>
            </div>
            {activeSaved ? (
              <Button variant="ghost" size="sm" data-testid="report-save-new" onClick={() => { setActiveSaved(null); setSaveName(""); }}>
                Save as new instead
              </Button>
            ) : null}
          </div>

          {(saved?.length ?? 0) > 0 ? (
            <div className="space-y-1.5 border-t border-border pt-3" data-testid="saved-reports-list">
              <Label>Saved reports</Label>
              {saved!.map((s) => (
                <div key={s.id} className={`flex items-center gap-1 rounded-lg border px-2 py-1.5 ${activeSaved === s.id ? "border-blue-300 bg-blue-50/60" : "border-border"}`}>
                  <button className="flex-1 text-left text-sm" data-testid={`saved-report-run-${s.id.slice(0, 8)}`}
                          onClick={() => runSaved.mutate(s.id)}>{s.name}</button>
                  <Button size="sm" variant="ghost" aria-label="Delete saved report"
                          data-testid={`saved-report-delete-${s.id.slice(0, 8)}`}
                          onClick={() => removeSaved.mutate(s.id)}><Trash2 className="size-3.5" aria-hidden /></Button>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="min-w-0">
          {result ? (
            <div data-testid="report-results">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-heading text-lg font-semibold">
                  {result.name}{result.group_by ? ` · grouped by ${result.group_by.replace(/_/g, " ")} (${result.aggregate})` : ""}
                </h2>
                <span className="text-xs text-muted-foreground" data-testid="report-row-count">{result.count} row(s)</span>
              </div>

              {visualization === "bar" && chartData.length > 0 ? (
                <div className="h-72 rounded-xl border border-border bg-card p-4" data-testid="report-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="name" fontSize={11} interval={0} angle={-20} height={50} textAnchor="end" />
                      <YAxis fontSize={11} tickFormatter={(v: number) => inr(v)} />
                      <Tooltip formatter={(v: number) => inr(v, 2)} />
                      <Bar dataKey="value" fill="#2563eb" radius={[4, 4, 0, 0]} name={label(chartData[0].valueKey)} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : visualization === "bar" ? (
                <p className="rounded-xl border border-dashed border-border px-4 py-6 text-sm text-muted-foreground" data-testid="report-chart-hint">
                  Charts need a grouped report — choose a "Group by" field and run again.
                </p>
              ) : null}

              {visualization === "table" ? (
                <div className="overflow-x-auto rounded-xl border border-border bg-card">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border bg-muted/50 text-xs uppercase tracking-wider text-muted-foreground">
                        {result.columns.map((c) => (
                          <th key={c} className={`px-4 py-2.5 font-semibold ${isNumeric(c) ? "text-right" : "text-left"}`}>{label(c)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i} className="border-b border-border/60 last:border-b-0 hover:bg-muted/40">
                          {result.columns.map((c) => (
                            <td key={c} className={`px-4 py-2 ${isNumeric(c) ? "text-right font-mono tabular-nums" : ""}`}>
                              {cell(c, row[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {Object.keys(result.totals).length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-4 rounded-xl border border-border bg-muted/40 px-4 py-3" data-testid="report-totals">
                  {Object.entries(result.totals).map(([k, v]) => (
                    <span key={k} className="text-xs text-muted-foreground">
                      {label(k)}: <span className="font-mono font-medium tabular-nums text-foreground">{cell(k, v)}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title="Choose a dataset and run"
              description="Try 'Payroll Register' filtered to a month, or group 'Net Pay' by department and switch to the bar visualization."
              testid="reports-empty"
            />
          )}
        </div>
      </div>
    </div>
  );
}
