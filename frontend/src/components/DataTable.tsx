// Dense data table (desktop) that transforms into stacked key-value cards on
// mobile (<md) — payroll data stays readable on phones without a squeezed table.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  label: string;
  numeric?: boolean;
  render?: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  testid: string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
}

export function DataTable<T>({ columns, rows, rowKey, testid, onRowClick, empty }: DataTableProps<T>) {
  if (rows.length === 0 && empty) {
    return <>{empty}</>;
  }
  return (
    <>
      {/* Desktop table */}
      <div data-testid={testid} className="hidden overflow-x-auto rounded-xl border border-border bg-card shadow-sm md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50 text-xs uppercase tracking-wider text-muted-foreground">
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={cn("px-4 py-2.5 text-left font-semibold", c.numeric && "text-right")}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  "border-b border-border/60 transition-colors last:border-b-0 hover:bg-muted/40",
                  onRowClick && "cursor-pointer",
                )}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn("px-4 py-2.5", c.numeric && "text-right font-mono tabular-nums")}
                  >
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile stacked cards */}
      <div className="md:hidden">
        {rows.map((row) => (
          <div
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            data-testid={`${testid}-card`}
            className="mb-3 space-y-1 rounded-xl border border-border bg-card p-4 shadow-sm"
          >
            {columns.map((c) => (
              <div key={c.key} className="flex items-center justify-between gap-3 border-b border-border/30 py-1 text-xs last:border-b-0">
                <span className="text-muted-foreground">{c.label}</span>
                <span className={cn("text-right", c.numeric && "font-mono tabular-nums")}>
                  {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
