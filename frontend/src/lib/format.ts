// Formatting helpers — INR amounts always render with the en-IN digit grouping and
// tabular figures (font-mono tabular-nums is applied at the call sites).

export const inr = (n: number | null | undefined, decimals = 0): string => {
  const value = typeof n === "number" && isFinite(n) ? n : 0;
  return "₹" + value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

export const monthLabel = (period: string): string => {
  if (!period || period.length < 7) return period;
  return new Date(period + "-01T00:00:00Z").toLocaleDateString("en-IN", {
    month: "long", year: "numeric", timeZone: "UTC",
  });
};

export const dateLabel = (d?: string | null): string => {
  if (!d) return "—";
  const parsed = new Date(d.length === 10 ? d + "T00:00:00Z" : d);
  if (isNaN(parsed.getTime())) return d;
  return parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};

export const dateTimeLabel = (d?: string | null): string => {
  if (!d) return "—";
  const parsed = new Date(d);
  if (isNaN(parsed.getTime())) return d;
  return parsed.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const titleCase = (s?: string | null): string =>
  (s ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const currentPeriod = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
};
