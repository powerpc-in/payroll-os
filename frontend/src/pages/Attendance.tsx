// Attendance: monthly summary (LOP view), quick marking, CSV import.

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Upload } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { AttendanceRow, Employee, ImportReport, Paged } from "@/lib/types";
import { currentPeriod, monthLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader } from "@/components/ui-kit";

interface SummaryRow {
  employee_id: string; name: string; employee_code: string;
  present: number; absent: number; half_day: number; paid_leave: number;
  unpaid_leave: number; weekly_off: number; holiday: number;
  overtime_hours: number; lop: number;
}

const STATUSES = ["present", "absent", "half_day", "paid_leave", "unpaid_leave", "weekly_off", "holiday"];

export default function Attendance() {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState(currentPeriod());
  const [empId, setEmpId] = useState("");
  const [date, setDate] = useState("");
  const [status, setStatus] = useState("present");
  const [overtime, setOvertime] = useState("0");
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: summary, isPending } = useQuery({
    queryKey: ["attendance-summary", period],
    queryFn: () => apiGet<SummaryRow[]>(`/v1/attendance/summary?period=${period}`),
  });
  const { data: employees } = useQuery({
    queryKey: ["employees", "attendance-page"],
    queryFn: () => apiGet<Paged<Employee>>("/v1/employees?page=1&limit=100"),
  });

  const mark = useMutation({
    mutationFn: () => apiPost("/v1/attendance", {
      employee_id: empId, date, status, days: status === "half_day" ? 0.5 : 1, overtime_hours: Number(overtime) || 0,
    }),
    onSuccess: () => {
      toast.success("Attendance saved");
      queryClient.invalidateQueries({ queryKey: ["attendance-summary", period] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const doImport = useMutation({
    mutationFn: async (file: File) => {
      const text = await file.text();
      const empIndex = employees?.items ?? [];
      const byCode = new Map(empIndex.map((e) => [e.employee_code, e.id]));
      const rows: { employee_id: string; date: string; status: string }[] = [];
      text.trim().split("\n").slice(1).forEach((line) => {
        const [code, d, s] = line.split(",").map((x) => x.trim());
        const employee_id = byCode.get(code);
        if (employee_id && d && s) rows.push({ employee_id, date: d, status: s });
      });
      if (rows.length === 0) throw new Error("No valid rows found — expected header employee_code,date,status");
      return apiPost<ImportReport>("/v1/attendance/import", { rows });
    },
    onSuccess: (report) => {
      toast.success(`${report.imported} rows imported, ${report.errors.length} rejected`);
      queryClient.invalidateQueries({ queryKey: ["attendance-summary"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const columns: Column<SummaryRow>[] = [
    { key: "employee_code", label: "ID" },
    { key: "name", label: "Employee", render: (r) => <span className="font-medium">{r.name}</span> },
    { key: "present", label: "Present", numeric: true },
    { key: "absent", label: "Absent", numeric: true },
    { key: "half_day", label: "Half", numeric: true },
    { key: "paid_leave", label: "Paid leave", numeric: true },
    { key: "unpaid_leave", label: "Unpaid", numeric: true },
    { key: "lop", label: "LOP", numeric: true, render: (r) => <span className={r.lop > 0 ? "text-destructive" : ""}>{r.lop}</span> },
    { key: "overtime_hours", label: "OT hrs", numeric: true },
  ];

  return (
    <div>
      <PageHeader
        title="Attendance"
        description={`${monthLabel(period)} · unpaid leave and absences become LOP in payroll`}
        testid="attendance-title"
        actions={
          <Dialog>
            <DialogTrigger render={<Button variant="outline" data-testid="attendance-import-button"><Upload className="size-4" aria-hidden /> Import CSV</Button>} />
            <DialogContent className="sm:max-w-md">
              <DialogHeader><DialogTitle>Import attendance</DialogTitle></DialogHeader>
              <DialogDescription>
                CSV with header <code className="rounded bg-muted px-1 font-mono text-xs">employee_code,date,status</code> — one row per day. Template: <a className="text-blue-600 underline" href="/api/v1/imports/employees/template" download>employee template</a> (same employee_code column).
              </DialogDescription>
              <input ref={fileRef} type="file" accept=".csv" data-testid="attendance-import-file" className="text-sm" />
              <DialogFooter>
                <Button onClick={() => { const f = fileRef.current?.files?.[0]; if (f) doImport.mutate(f); }} disabled={doImport.isPending} data-testid="attendance-import-submit">
                  {doImport.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Upload & import
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label>Month</Label>
          <Input type="month" data-testid="attendance-period-input" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-44" />
        </div>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
          <div className="space-y-1"><Label>Employee</Label>
            <Select value={empId} onValueChange={(v: string) => setEmpId(v)}>
              <SelectTrigger data-testid="attendance-employee-select" className="w-52"><SelectValue>{(v: string) => employees?.items.find((e) => e.id === v)?.name ?? "Choose…"}</SelectValue></SelectTrigger>
              <SelectContent>{employees?.items.map((e) => <SelectItem key={e.id} value={e.id}>{e.name} ({e.employee_code})</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="space-y-1"><Label>Date</Label><Input type="date" data-testid="attendance-date-input" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="space-y-1"><Label>Status</Label>
            <Select value={status} onValueChange={(v: string) => setStatus(v)}>
              <SelectTrigger data-testid="attendance-status-select" className="w-36"><SelectValue>{(v: string) => titleCase(v)}</SelectValue></SelectTrigger>
              <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{titleCase(s)}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="space-y-1"><Label>OT hours</Label><Input type="number" className="w-24" data-testid="attendance-overtime-input" value={overtime} onChange={(e) => setOvertime(e.target.value)} /></div>
          <Button onClick={() => mark.mutate()} disabled={mark.isPending || !empId || !date} data-testid="attendance-save-button">Save</Button>
        </div>
      </div>

      {isPending ? (
        <div className="h-64 animate-pulse rounded-xl bg-muted" />
      ) : (summary?.length ?? 0) === 0 ? (
        <EmptyState title={`No attendance recorded for ${monthLabel(period)}`} description="Mark attendance or import a CSV — payroll uses it for LOP." testid="attendance-empty" />
      ) : (
        <DataTable columns={columns} rows={summary ?? []} rowKey={(r) => r.employee_id} testid="attendance-table" />
      )}
    </div>
  );
}
