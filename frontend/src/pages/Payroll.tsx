// Payroll runs list + creation. The run detail (workflow + calculation drawer)
// lives in PayrollRun.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Banknote, Loader2, Plus } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Paged, PayrollRun } from "@/lib/types";
import { currentPeriod, inr, monthLabel } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader, RunStatusBadge } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

export default function Payroll() {
  const session = useSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [period, setPeriod] = useState(currentPeriod());

  const { data, isPending } = useQuery({
    queryKey: ["runs"],
    queryFn: () => apiGet<Paged<PayrollRun>>("/v1/payroll/runs?page=1&limit=12"),
  });

  const create = useMutation({
    mutationFn: () => apiPost<PayrollRun>("/v1/payroll/runs", { period }),
    onSuccess: (run) => {
      toast.success(`Run created for ${monthLabel(period)} — calculate next`);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      setOpen(false);
      navigate(`/app/payroll/${run.id}`);
    },
    onError: (err) => toast.error(String(err)),
  });

  const columns: Column<PayrollRun>[] = [
    { key: "period", label: "Period", render: (r) => <span className="font-medium text-foreground">{monthLabel(r.period)}</span> },
    { key: "status", label: "Status", render: (r) => <RunStatusBadge status={r.status} /> },
    { key: "headcount", label: "Employees", numeric: true, render: (r) => r.totals?.headcount ?? 0 },
    { key: "gross", label: "Gross", numeric: true, render: (r) => inr(r.totals?.gross ?? 0) },
    { key: "net", label: "Net", numeric: true, render: (r) => inr(r.totals?.net ?? 0) },
    { key: "employer_cost", label: "Employer cost", numeric: true, render: (r) => inr(r.totals?.employer_cost ?? 0) },
    { key: "errors", label: "Errors", numeric: true, render: (r) => (r.totals?.errors ?? 0) > 0 ? <span className="text-destructive">{r.totals?.errors}</span> : "0" },
  ];

  return (
    <div>
      <PageHeader
        title="Payroll Runs"
        description="DRAFT → CALCULATED → REVIEW → APPROVED → LOCKED — every number computed server-side."
        testid="payroll-title"
        actions={can(session.data?.permissions, "payroll.calculate") ? (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger render={<Button data-testid="create-run-button"><Plus className="size-4" aria-hidden /> New run</Button>} />
            <DialogContent className="sm:max-w-sm">
              <DialogHeader><DialogTitle>Create payroll run</DialogTitle></DialogHeader>
              <DialogDescription>One run per month. Employees with an active salary assignment are included.</DialogDescription>
              <div className="space-y-1"><Label>Period *</Label><Input type="month" data-testid="run-period-input" value={period} onChange={(e) => setPeriod(e.target.value)} /></div>
              <DialogFooter><Button onClick={() => create.mutate()} disabled={create.isPending} data-testid="run-create-confirm">{create.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Create run</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        ) : undefined}
      />

      {isPending ? <div className="h-64 animate-pulse rounded-xl bg-muted" />
        : (data?.total ?? 0) === 0 ? (
          <EmptyState
            icon={<Banknote className="size-10" aria-hidden />}
            title="No payroll runs yet"
            description="Create a run for the current month, add inputs like bonuses, then calculate."
            testid="payroll-empty"
            action={can(session.data?.permissions, "payroll.calculate") ? (
              <Button onClick={() => setOpen(true)} data-testid="payroll-empty-create">Create first run</Button>
            ) : undefined}
          />
        ) : (
          <DataTable columns={columns} rows={data?.items ?? []} rowKey={(r) => r.id} testid="payroll-runs-table" onRowClick={(r) => navigate(`/app/payroll/${r.id}`)} />
        )}
    </div>
  );
}
