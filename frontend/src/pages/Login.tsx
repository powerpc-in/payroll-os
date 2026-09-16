// Split auth portal: branded compliance hero on the left, fast credential panel
// on the right, with demo-credential pills for reviewers.

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Landmark, ShieldCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { login } from "@/lib/session";

const DEMO_ACCOUNTS = [
  { label: "Company Admin", email: "admin@kaveritextiles.example" },
  { label: "Payroll Admin", email: "payroll@kaveritextiles.example" },
  { label: "HR", email: "hr@kaveritextiles.example" },
  { label: "Finance", email: "finance@kaveritextiles.example" },
  { label: "Manager", email: "manager@kaveritextiles.example" },
  { label: "Employee", email: "employee@kaveritextiles.example" },
];
const DEMO_PASSWORD = "Demo@12345";

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      toast.success("Welcome back");
      navigate("/app", { replace: true });
    } catch (err) {
      const message = err instanceof ApiError ? String((err.body as { detail?: string })?.detail ?? "Sign-in failed") : "Sign-in failed";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-svh flex-col lg:flex-row">
      {/* Brand hero */}
      <div className="relative hidden flex-1 flex-col justify-between overflow-hidden bg-[#0F172A] p-10 lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Landmark className="size-5" aria-hidden />
          </span>
          <span className="font-heading text-xl font-bold text-white">Vetan</span>
        </div>
        <div className="max-w-md">
          <h1 className="font-heading text-4xl font-bold leading-tight text-white">
            The payroll operating system for India — and next, the world.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-300">
            One API-first engine for payroll, statutory compliance and people ops.
            Every calculation is deterministic, versioned and fully explainable —
            never guessed, never generated.
          </p>
          <ul className="mt-6 space-y-2.5 text-sm text-slate-300">
            {["Deterministic tax · PF · ESI · PT · LWF engine", "Versioned statutory rules with verification flags", "Multi-tenant isolation on every record"].map((line) => (
              <li key={line} className="flex items-center gap-2">
                <ShieldCheck className="size-4 shrink-0 text-sky-400" aria-hidden />
                {line}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-slate-500">MVP build — not statutorily certified. Fictional demo data.</p>
      </div>

      {/* Credential panel */}
      <div className="flex flex-1 items-center justify-center bg-background px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <span className="mb-4 flex size-10 items-center justify-center rounded-xl bg-blue-600 text-white">
              <Landmark className="size-5" aria-hidden />
            </span>
            <h1 className="font-heading text-2xl font-bold text-foreground">Sign in to Vetan</h1>
          </div>
          <div className="mb-8 hidden lg:block">
            <h2 className="font-heading text-2xl font-bold text-foreground">Sign in</h2>
            <p className="mt-1 text-sm text-muted-foreground">Use your work account, or a demo role below.</p>
          </div>

          <form onSubmit={submit} className="space-y-4" data-testid="login-form">
            <div className="space-y-1.5">
              <Label htmlFor="email">Work email</Label>
              <Input
                id="email" type="email" required data-testid="login-email-input"
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com" autoComplete="email"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password" type="password" required data-testid="login-password-input"
                value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••" autoComplete="current-password"
              />
            </div>
            {error ? (
              <p data-testid="login-error" className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {error}
              </p>
            ) : null}
            <Button type="submit" disabled={busy} className="w-full" data-testid="login-submit-button">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              Sign in
            </Button>
          </form>

          <div className="mt-6">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Demo roles (password {DEMO_PASSWORD})</p>
            <div className="flex flex-wrap gap-1.5">
              {DEMO_ACCOUNTS.map((acc) => (
                <button
                  key={acc.email}
                  data-testid={`demo-account-pill-${acc.label.toLowerCase().replace(/\s+/g, "-")}`}
                  className="rounded-full border border-border bg-card px-3 py-1 text-xs text-foreground transition-colors hover:bg-muted"
                  onClick={() => {
                    setEmail(acc.email);
                    setPassword(DEMO_PASSWORD);
                  }}
                >
                  {acc.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-8 flex items-center justify-between text-sm">
            <Link to="/signup" className="text-blue-600 hover:underline dark:text-blue-400">Create a company</Link>
            <Link to="/reset" className="text-muted-foreground hover:underline">Forgot password?</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
