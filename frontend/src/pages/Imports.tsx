// Data import center: employee and salary CSV imports with validation reports.

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileUp, Loader2 } from "lucide-react";
import { apiPost } from "@/lib/api";
import type { ImportReport } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui-kit";

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split("\n");
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).filter((l) => l.trim()).map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    return Object.fromEntries(headers.map((h, i) => [h, cells[i] ?? ""]));
  });
}

function ImportPanel({ title, kind, template }: { title: string; kind: "employees" | "salaries"; template: string }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [report, setReport] = useState<ImportReport | null>(null);

  const doImport = useMutation({
    mutationFn: async (file: File) => {
      const text = await file.text();
      const rows = parseCsv(text);
      if (rows.length === 0) throw new Error("No data rows found");
      if (kind === "employees") {
        const payload = rows.map((r) => ({
          name: r.name, joining_date: r.joining_date, gross_monthly: Number(r.gross_monthly),
          email: r.email || undefined, phone: r.phone || undefined,
          department: r.department || undefined, designation: r.designation || undefined,
          state: r.state || undefined, tax_regime: r.tax_regime || "new",
          pf_applicable: (r.pf_applicable ?? "true").toLowerCase() !== "false",
          esi_applicable: (r.esi_applicable ?? "true").toLowerCase() !== "false",
        }));
        return apiPost<ImportReport>("/v1/imports/employees", { rows: payload });
      }
      const payload = rows.map((r) => ({
        employee_code: r.employee_code, gross_monthly: Number(r.gross_monthly),
      }));
      return apiPost<ImportReport>("/v1/imports/salaries", { rows: payload });
    },
    onSuccess: (res) => {
      setReport(res);
      toast.success(`${res.imported} imported, ${res.errors.length} rejected`);
      queryClient.invalidateQueries({ queryKey: ["employees"] });
      queryClient.invalidateQueries({ queryKey: ["assignments"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid={`import-panel-${kind}`}>
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-base font-semibold">{title}</h2>
        <a href={template} download className="text-xs text-blue-600 hover:underline dark:text-blue-400">Download template</a>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Upload a CSV. Every row is validated — invalid rows are rejected with reasons, never silently dropped.
      </p>
      <label className="mt-3 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border px-4 py-2.5 text-sm hover:bg-muted/50">
        {doImport.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FileUp className="size-4" aria-hidden />}
        Choose CSV & import
        <input type="file" accept=".csv" className="hidden" data-testid={`import-file-${kind}`}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport.mutate(f); }} />
      </label>
      {report ? (
        <div className="mt-3 rounded-lg border border-border bg-muted/40 p-3 text-xs" data-testid={`import-report-${kind}`}>
          <p>{report.imported} of {report.total} rows imported.</p>
          {report.errors.length > 0 ? (
            <ul className="mt-1 list-disc pl-4 text-red-600">
              {report.errors.slice(0, 10).map((e, i) => (
                <li key={i}>Row {e.row}{e.name ? ` (${e.name})` : ""}: {e.errors.join("; ")}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function Imports() {
  return (
    <div>
      <PageHeader title="Data Import" description="Bulk-create employees and salary assignments from CSV." testid="imports-title" />
      <div className="grid gap-5 lg:grid-cols-2">
        <ImportPanel kind="employees" title="Employee import" template="/api/v1/imports/employees/template" />
        <ImportPanel kind="salaries" title="Salary import" template="/api/v1/imports/salaries/template" />
      </div>
    </div>
  );
}
