// Notifications (in-app channel).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { AppNotification } from "@/lib/types";
import { dateTimeLabel } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { EmptyState, PageHeader } from "@/components/ui-kit";

export default function Notifications() {
  const queryClient = useQueryClient();
  const { data, isPending } = useQuery({ queryKey: ["notifications"], queryFn: () => apiGet<{ items: AppNotification[]; unread: number }>("/v1/notifications") });

  const markAll = useMutation({
    mutationFn: () => apiPost("/v1/notifications/read-all", {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markOne = useMutation({
    mutationFn: (id: string) => apiPost(`/v1/notifications/${id}/read`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  return (
    <div>
      <PageHeader
        title="Notifications"
        description={`${data?.unread ?? 0} unread`}
        testid="notifications-title"
        actions={(data?.unread ?? 0) > 0 ? (
          <Button variant="outline" size="sm" onClick={() => markAll.mutate()} data-testid="mark-all-read-button">Mark all read</Button>
        ) : undefined}
      />
      {isPending ? <div className="h-40 animate-pulse rounded-xl bg-muted" />
        : (data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={<Bell className="size-10" aria-hidden />} title="No notifications yet" description="Payroll events, approvals and compliance alerts arrive here." testid="notifications-empty" />
        ) : (
          <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="notifications-list">
            {data!.items.map((n) => (
              <li key={n.id} className={`flex items-start justify-between gap-4 px-4 py-3 ${n.read ? "" : "bg-blue-50/40 dark:bg-blue-950/20"}`}>
                <div>
                  <p className="text-sm text-foreground">{n.title}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{n.event} · {dateTimeLabel(n.created_at)}</p>
                </div>
                {!n.read ? <Button size="sm" variant="ghost" onClick={() => markOne.mutate(n.id)} data-testid={`mark-read-${n.id.slice(0, 8)}`}>Mark read</Button> : null}
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
