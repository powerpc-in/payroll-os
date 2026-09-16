// Notifications: in-app inbox plus the channel architecture (email, PWA web push,
// Android/iOS push). Unconfigured channels queue honestly — nothing claims to be sent.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bell, BellRing } from "lucide-react";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type { AppNotification, NotificationChannelState } from "@/lib/types";
import { dateTimeLabel } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState, PageHeader } from "@/components/ui-kit";
import { useSession } from "@/lib/session";
import { can } from "@/lib/permissions";

export default function Notifications() {
  const queryClient = useQueryClient();
  const session = useSession();
  const canManage = can(session.data?.permissions, "settings.manage");

  const { data, isPending } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => apiGet<{ items: AppNotification[]; unread: number }>("/v1/notifications"),
  });
  const { data: channels } = useQuery({
    queryKey: ["notification-channels"],
    queryFn: () => apiGet<NotificationChannelState>("/v1/notifications/channels"),
  });

  const markAll = useMutation({
    mutationFn: () => apiPost("/v1/notifications/read-all", {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markOne = useMutation({
    mutationFn: (id: string) => apiPost(`/v1/notifications/${id}/read`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const saveChannels = useMutation({
    mutationFn: (next: Record<string, boolean>) => apiPut("/v1/notifications/channels", { channels: next }),
    onSuccess: () => {
      toast.success("Channel preferences saved");
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
    },
    onError: (err) => toast.error(String(err)),
  });

  const toggle = (key: string, value: boolean) => {
    const next = Object.fromEntries((channels?.channels ?? []).map((c) => [c.key, c.key === key ? value : c.enabled]));
    saveChannels.mutate(next);
  };

  return (
    <div>
      <PageHeader
        title="Notifications"
        description={`${data?.unread ?? 0} unread · one event feeds the inbox, the audit trail and outbound webhooks`}
        testid="notifications-title"
        actions={(data?.unread ?? 0) > 0 ? (
          <Button variant="outline" size="sm" onClick={() => markAll.mutate()} data-testid="mark-all-read-button">Mark all read</Button>
        ) : undefined}
      />

      {channels ? (
        <div className="mb-5 rounded-xl border border-border bg-card p-4" data-testid="notification-channels">
          <h2 className="font-heading text-base font-semibold">Delivery channels</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            In-app is live. The other channels are wired into the event architecture and queue
            each notification until a provider is configured — the platform never reports a
            send that did not happen.
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {channels.channels.map((c) => (
              <label key={c.key} className="flex items-start gap-2 rounded-lg border border-border px-3 py-2"
                     data-testid={`channel-${c.key}`}>
                <Checkbox className="mt-0.5" checked={c.enabled} disabled={!canManage || saveChannels.isPending}
                          data-testid={`channel-toggle-${c.key}`}
                          onCheckedChange={(v) => toggle(c.key, Boolean(v))} />
                <span className="min-w-0">
                  <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                    {c.label}
                    <span className={`rounded-full border px-1.5 py-0.5 text-[10px] ${c.configured ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                      {c.configured ? "configured" : "requires configuration"}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">{c.note}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground" data-testid="notification-events">
            Notifying events: {channels.events.map((e) => e.event).join(" · ")}
          </p>
        </div>
      ) : null}

      {isPending ? <div className="h-40 animate-pulse rounded-xl bg-muted" />
        : (data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={<Bell className="size-10" aria-hidden />} title="No notifications yet"
            description="Payroll locks, payslip-ready alerts, approvals and compliance events arrive here."
            testid="notifications-empty" />
        ) : (
          <ul className="divide-y divide-border rounded-xl border border-border bg-card" data-testid="notifications-list">
            {data!.items.map((n) => (
              <li key={n.id} className={`flex items-start justify-between gap-4 px-4 py-3 ${n.read ? "" : "bg-blue-50/40 dark:bg-blue-950/20"}`}>
                <div className="min-w-0">
                  <p className="flex items-start gap-2 text-sm text-foreground">
                    {!n.read ? <BellRing className="mt-0.5 size-3.5 shrink-0 text-blue-600" aria-hidden /> : null}
                    {n.title}
                  </p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {n.event} · {dateTimeLabel(n.created_at)}
                    {n.channels ? ` · ${Object.entries(n.channels).map(([k, v]) => `${k}: ${v}`).join(", ")}` : ""}
                  </p>
                </div>
                {!n.read ? (
                  <Button size="sm" variant="ghost" onClick={() => markOne.mutate(n.id)} data-testid={`mark-read-${n.id.slice(0, 8)}`}>Mark read</Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
