// App shell: dark navy sidebar (desktop) + top bar + mobile bottom nav + offline
// banner + PWA install prompt. One shell for every role; nav items are
// permission-gated and the employee role gets the self-service subset.

import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Banknote, Bell, CalendarDays, Building2, ClipboardList, Download, FileSpreadsheet,
  Gauge, HandCoins, Landmark, LogOut, Menu, Plane, Receipt, RefreshCcw,
  Settings, ShieldCheck, Users, Wallet, WifiOff, Plug, Webhook,
} from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSession, endSession } from "@/lib/session";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Gauge;
  perm: string;
  section: string;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/app", label: "Dashboard", icon: Gauge, perm: "dashboards.view", section: "Operate" },
  { to: "/app/employees", label: "Employees", icon: Users, perm: "employees.view", section: "Operate" },
  { to: "/app/salary", label: "Salary", icon: Wallet, perm: "salary.view", section: "Operate" },
  { to: "/app/attendance", label: "Attendance", icon: CalendarDays, perm: "attendance.view", section: "Operate" },
  { to: "/app/leave", label: "Leave", icon: Plane, perm: "leave.view", section: "Operate" },
  { to: "/app/reimbursements", label: "Reimbursements", icon: Receipt, perm: "reimbursements.view", section: "Operate" },
  { to: "/app/loans", label: "Loans & Advances", icon: HandCoins, perm: "loans.view", section: "Operate" },
  { to: "/app/payroll", label: "Payroll Runs", icon: Banknote, perm: "payroll.view", section: "Payroll" },
  { to: "/app/reports", label: "Reports", icon: FileSpreadsheet, perm: "reports.view", section: "Payroll" },
  { to: "/app/compliance", label: "Compliance Rules", icon: ShieldCheck, perm: "compliance.view", section: "Payroll" },
  { to: "/app/integrations", label: "Integrations", icon: Plug, perm: "integrations.manage", section: "Platform" },
  { to: "/app/webhooks", label: "Webhooks", icon: Webhook, perm: "webhooks.manage", section: "Platform" },
  { to: "/app/audit", label: "Audit Trail", icon: ClipboardList, perm: "audit.view", section: "Platform" },
  { to: "/app/imports", label: "Data Import", icon: Download, perm: "imports.manage", section: "Platform" },
  { to: "/app/settings", label: "Settings", icon: Settings, perm: "settings.manage", section: "Platform" },
  { to: "/me", label: "My Workspace", icon: RefreshCcw, perm: "self.view", section: "You" },
];

const MOBILE_NAV = [
  { to: "/app", label: "Home", icon: Gauge },
  { to: "/app/payroll", label: "Payroll", icon: Banknote },
  { to: "/app/employees", label: "Team", icon: Users },
  { to: "/app/leave", label: "Leave", icon: Plane },
  { to: "/me", label: "Me", icon: RefreshCcw },
];

function BrandMark() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-8 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm">
        <Landmark className="size-4.5" aria-hidden />
      </span>
      <span className="font-heading text-lg font-bold tracking-tight text-white">Vetan</span>
      <span className="mt-0.5 hidden rounded border border-slate-600 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-300 lg:inline">
        Payroll OS
      </span>
    </div>
  );
}

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const session = useSession();
  const permissions = session.data?.permissions;
  const sections = ["Operate", "Payroll", "Platform", "You"];
  const items = NAV_ITEMS.filter((item) => can(permissions, item.perm));

  return (
    <nav data-testid="sidebar-nav" className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
      {sections.map((section) => {
        const sectionItems = items.filter((i) => i.section === section);
        if (sectionItems.length === 0) return null;
        return (
          <div key={section}>
            <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{section}</p>
            <ul className="space-y-0.5">
              {sectionItems.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/app"}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors duration-150",
                        isActive
                          ? "bg-slate-800 font-medium text-sky-400"
                          : "text-slate-300 hover:bg-slate-800/60 hover:text-white",
                      )
                    }
                  >
                    <item.icon className="size-4 shrink-0" aria-hidden />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function InstallPrompt() {
  const [deferred, setDeferred] = useState<(Event & { prompt: () => Promise<void> }) | null>(null);
  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault();
      setDeferred(e as Event & { prompt: () => Promise<void> });
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);
  if (!deferred) return null;
  return (
    <Button
      data-testid="pwa-install-button"
      variant="outline"
      size="sm"
      className="w-full border-slate-600 bg-slate-800/60 text-slate-200 hover:bg-slate-700"
      onClick={() => {
        deferred.prompt();
        setDeferred(null);
      }}
    >
      <Download className="size-4" aria-hidden /> Install app
    </Button>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [offline, setOffline] = useState(!navigator.onLine);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const org = session.data?.org;
  const role = session.data?.role ?? "";
  const email = session.data?.user.email ?? "";
  const isEmployee = role === "EMPLOYEE";

  const handleLogout = async () => {
    await endSession();
    queryClient.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-svh bg-background">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[260px] flex-col bg-[#0F172A] md:flex">
        <div className="flex h-16 items-center px-5">
          <BrandMark />
        </div>
        <SidebarNav />
        <div className="space-y-3 border-t border-slate-800 p-4">
          <InstallPrompt />
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-slate-200">
              {session.data?.user.name.slice(0, 2).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-slate-200">{session.data?.user.name}</p>
              <p className="truncate text-[10px] text-slate-400">{role.replace("_", " ")}</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="md:pl-[260px]">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/90 px-4 backdrop-blur md:h-16 md:px-6">
          <div className="flex items-center gap-3">
            <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
              <SheetTrigger
                render={
                  <Button data-testid="mobile-menu-button" variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                    <Menu className="size-5" aria-hidden />
                  </Button>
                }
              />
              <SheetContent side="left" className="w-[280px] border-slate-800 bg-[#0F172A] p-0">
                <div className="flex h-14 items-center px-5">
                  <BrandMark />
                </div>
                <SidebarNav onNavigate={() => setMenuOpen(false)} />
              </SheetContent>
            </Sheet>
            <div className="flex items-center gap-2 md:hidden">
              <span className="flex size-6 items-center justify-center rounded-md bg-blue-600 text-white">
                <Landmark className="size-3.5" aria-hidden />
              </span>
              <span className="font-heading text-base font-bold text-foreground">Vetan</span>
            </div>
            {org ? (
              <div className="hidden items-center gap-2 md:flex">
                <Building2 className="size-4 text-muted-foreground" aria-hidden />
                <span data-testid="topbar-org-name" className="text-sm font-medium text-foreground">{org.name}</span>
                <Badge variant="outline" className="text-[10px] uppercase tracking-wider">
                  {org.jurisdiction} · INR
                </Badge>
                {isEmployee ? null : (
                  <Link to="/app/compliance" className="text-xs text-blue-600 hover:underline dark:text-blue-400">
                    jurisdiction
                  </Link>
                )}
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-1.5">
            <Link
              to="/app/notifications"
              data-testid="notifications-bell-link"
              className="relative rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label="Notifications"
            >
              <Bell className="size-5" aria-hidden />
            </Link>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <button
                    data-testid="user-menu-trigger"
                    className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-muted"
                  >
                    <span className="flex size-7 items-center justify-center rounded-full bg-[#0F172A] text-xs font-semibold text-white">
                      {session.data?.user.name.slice(0, 2).toUpperCase()}
                    </span>
                    <span className="hidden max-w-[160px] truncate text-sm md:inline">{session.data?.user.name}</span>
                  </button>
                }
              />
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <p className="text-sm font-medium">{email}</p>
                  <p className="text-xs text-muted-foreground">{role.replace("_", " ")}</p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/me")}>
                  <RefreshCcw className="size-4" aria-hidden /> Self-service
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem data-testid="logout-menu-item" onClick={handleLogout} variant="destructive">
                  <LogOut className="size-4" aria-hidden /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {offline ? (
          <div data-testid="offline-banner" className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
            <WifiOff className="size-4" aria-hidden />
            You're offline — data shown may be from the last sync. Actions will retry when the connection returns.
          </div>
        ) : null}

        <main className="mx-auto w-full max-w-[1600px] p-4 pb-24 md:p-6 lg:p-8 md:pb-10">{children}</main>
      </div>

      {/* Mobile bottom nav */}
      <nav
        data-testid="mobile-bottom-nav"
        className="fixed inset-x-0 bottom-0 z-40 flex h-16 items-stretch border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {MOBILE_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/app"}
            className={({ isActive }) =>
              cn(
                "flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-medium",
                isActive ? "text-blue-600 dark:text-blue-400" : "text-muted-foreground",
              )
            }
          >
            <item.icon className="size-5" aria-hidden />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const location = useLocation();

  if (session.isPending) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-blue-600 text-white">
            <Landmark className="size-5" aria-hidden />
          </span>
          <p className="text-sm text-muted-foreground">Loading Vetan…</p>
        </div>
      </div>
    );
  }
  if (session.isError || !session.data) {
    return <NavigateToLogin />;
  }
  const { org, permissions } = session.data;
  if (org && !org.onboarded && can(permissions, "settings.manage") && location.pathname !== "/onboarding") {
    return <NavigateTo onboarding />;
  }
  return <>{children}</>;
}

function NavigateToLogin() {
  return <Navigate to="/login" replace />;
}

function NavigateTo({ onboarding }: { onboarding: boolean }) {
  return <Navigate to={onboarding ? "/onboarding" : "/login"} replace />;
}
