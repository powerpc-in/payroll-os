// Shared UI atoms for the payroll domain: status badges, verification badges,
// stat cards, empty states, page headers, money text.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { inr } from "@/lib/format";
import type { RunStatus } from "@/lib/types";
import { AlertTriangle, ShieldCheck } from "lucide-react";

export const RUN_STATUS_STYLES: Record<RunStatus, string> = {
  draft: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
  calculated: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-800",
  review: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800",
  approved: "bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800",
  locked: "bg-purple-50 text-purple-800 border-purple-200 dark:bg-purple-950/60 dark:text-purple-300 dark:border-purple-800",
};

export function RunStatusBadge({ status }: { status: string }) {
  const style = RUN_STATUS_STYLES[status as RunStatus] ?? RUN_STATUS_STYLES.draft;
  return (
    <span
      data-testid={`payroll-status-badge-${status}`}
      aria-label={`Payroll status: ${status}`}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}
    >
      {status}
    </span>
  );
}

export function VerificationBadge({ verified, compact = false }: { verified: boolean; compact?: boolean }) {
  if (verified) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
        <ShieldCheck className="size-3" aria-hidden />
        Verified
      </span>
    );
  }
  return (
    <span
      data-testid="verification-required-badge"
      title="This value has not been independently verified — do not treat as statutory"
      className={`inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 font-medium text-amber-800 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-300 ${compact ? "text-[11px]" : "text-xs"}`}
    >
      <AlertTriangle className="size-3" aria-hidden />
      Requires statutory verification
    </span>
  );
}

export function StatCard({
  label, value, sub, testid, className,
}: { label: string; value: ReactNode; sub?: ReactNode; testid: string; className?: string }) {
  return (
    <div
      data-testid={testid}
      className={cn(
        "rounded-xl border border-border bg-card p-5 shadow-sm transition-transform duration-150 ease-in-out hover:-translate-y-0.5 motion-reduce:transform-none",
        className,
      )}
    >
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-2 font-mono text-2xl font-medium tabular-nums text-foreground">{value}</p>
      {sub ? <p className="mt-1 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

export function Money({ value, className }: { value: number | null | undefined; className?: string }) {
  return <span className={cn("font-mono tabular-nums", className)}>{inr(value)}</span>;
}

export function EmptyState({
  icon, title, description, action, testid,
}: { icon?: ReactNode; title: string; description?: string; action?: ReactNode; testid: string }) {
  return (
    <div
      data-testid={testid}
      className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/50 px-6 py-14 text-center"
    >
      {icon ? <div className="mb-3 text-muted-foreground">{icon}</div> : null}
      <p className="font-heading text-base font-semibold text-foreground">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function PageHeader({
  title, description, actions, testid,
}: { title: string; description?: string; actions?: ReactNode; testid: string }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 data-testid={testid} className="font-heading text-2xl font-bold tracking-tight text-foreground">
          {title}
        </h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function ErrorState({ message, testid }: { message: string; testid: string }) {
  return (
    <div data-testid={testid} className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
      {message}
    </div>
  );
}
