// Sign-up → creates the tenant + first admin, then the onboarding wizard takes over.

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Landmark, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { signup } from "@/lib/session";

export default function Signup() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signup({ name, email, password, org_name: orgName });
      toast.success("Company created — let's set up payroll");
      navigate("/onboarding", { replace: true });
    } catch (err) {
      const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
      setError(detail ?? "Could not create the account");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-svh items-center justify-center bg-background px-6 py-12">
      <div className="w-full max-w-sm">
        <Link to="/login" className="mb-8 flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Landmark className="size-5" aria-hidden />
          </span>
          <span className="font-heading text-xl font-bold text-foreground">Vetan</span>
        </Link>
        <h1 className="font-heading text-2xl font-bold text-foreground">Create your company workspace</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          You become the company admin. Onboarding configures payroll in 8 guided steps.
        </p>

        <form onSubmit={submit} className="mt-8 space-y-4" data-testid="signup-form">
          <div className="space-y-1.5">
            <Label htmlFor="name">Your name</Label>
            <Input id="name" required data-testid="signup-name-input" value={name}
                   onChange={(e) => setName(e.target.value)} placeholder="Full name" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="org">Company name</Label>
            <Input id="org" required data-testid="signup-org-input" value={orgName}
                   onChange={(e) => setOrgName(e.target.value)} placeholder="Acme Pvt Ltd" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Work email</Label>
            <Input id="email" type="email" required data-testid="signup-email-input" value={email}
                   onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" required minLength={8} data-testid="signup-password-input"
                   value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />
          </div>
          {error ? (
            <p data-testid="signup-error" className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={busy} className="w-full" data-testid="signup-submit-button">
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            Create company
          </Button>
        </form>
        <p className="mt-6 text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link to="/login" className="text-blue-600 hover:underline dark:text-blue-400">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
