// Audit trail viewer.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList } from "lucide-react";
import { apiGet } from "@/lib/api";
import type { AuditLog, Paged } from "@/lib/types";
import { dateTimeLabel, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState, PageHeader } from "@/components/ui-kit";

export default function Audit() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [entity, setEntity] = useState("");

  const { data, isPending } = useQuery({
    queryKey: ["audit", page, q, entity],
    queryFn: () => apiGet<Paged<AuditLog>>(
      `/v1/audit?page=${page}&limit=30${q ? `&q=${encodeURIComponent(q)}` : ""}${entity ? `&entity=${entity}` : ""}`,
    ),
  });

  const columns: Column<AuditLog>[] = [
    { key: "created_at", label: "When", render: (r) => dateTimeLabel(r.created_at) },
    { key: "action", label: "Action", render: (r) => <span className="font-mono text-xs">{r.action}</span> },
    { key: "user_email", label: "User" },
    { key: "entity", label: "Entity", render: (r) => titleCase(r.entity ?? "") },
    { key: "summary", label: "Summary" },
  ];

  return (
    <div>
      <PageHeader title="Audit Trail" description="Every sensitive action — who, what, old value, new value, when." testid="audit-title" />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input placeholder="Search summaries…" className="max-w-xs" data-testid="audit-search-input" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Input placeholder="Entity (employee, payroll_run…)" className="max-w-xs" data-testid="audit-entity-input" value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }} />
      </div>
      {isPending ? <div className="h-64 animate-pulse rounded-xl bg-muted" />
        : (data?.total ?? 0) === 0 ? (
          <EmptyState icon={<ClipboardList className="size-10" aria-hidden />} title="No audit entries yet" description="Actions like employee edits, payroll approvals and lock events are recorded here." testid="audit-empty" />
        ) : (
          <>
            <DataTable columns={columns} rows={data?.items ?? []} rowKey={(r) => r.id} testid="audit-table" />
            <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
              <span>Page {page} of {Math.max(1, Math.ceil((data?.total ?? 0) / 30))}</span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="audit-prev-page">Previous</Button>
                <Button variant="outline" size="sm" disabled={page >= Math.max(1, Math.ceil((data?.total ?? 0) / 30))} onClick={() => setPage(page + 1)} data-testid="audit-next-page">Next</Button>
              </div>
            </div>
          </>
        )}
    </div>
  );
}
