"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { fetchMe, getJob, logout, type Me } from "@/lib/api";

function deriveJobId(pathname: string): string | null {
  const m = pathname.match(/^\/jobs\/([^/]+)/);
  if (!m) return null;
  const id = decodeURIComponent(m[1]);
  return id === "new" ? null : id;
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 px-2">
      <span className="block overflow-hidden rounded-[7px] ring-1 ring-line-2">
        <Image src="/Catalist-logo.jpeg" alt="Catalist" width={26} height={26} className="block h-[26px] w-[26px]" />
      </span>
      <span className="font-display text-[15px] font-medium tracking-tight">Catalist</span>
    </Link>
  );
}

function AccountFooter() {
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    fetchMe()
      .then((m) => live && setMe(m))
      .catch(() => live && setMe(null));
    return () => {
      live = false;
    };
  }, []);

  async function onLogout() {
    setBusy(true);
    await logout();
    window.location.href = "/login";
  }

  const name = me?.username ?? "Account";
  const initial = (name.trim()[0] ?? "A").toUpperCase();

  return (
    <div className="border-t border-line p-3">
      <div className="flex items-center gap-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-xs font-semibold text-muted">
          {initial}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">{name}</div>
          <div className="truncate text-[11px] text-faint">
            {me?.auth_enabled === false ? "Auth disabled (dev)" : "Signed in"}
          </div>
        </div>
        <button
          onClick={onLogout}
          disabled={busy}
          aria-label="Sign out"
          title="Sign out"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-[var(--tier-reject)] disabled:opacity-50"
        >
          <IconLogout />
        </button>
      </div>
    </div>
  );
}

function NavItem({
  href,
  active,
  icon,
  children,
  onNavigate,
}: {
  href: string;
  active: boolean;
  icon: React.ReactNode;
  children: React.ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
        active
          ? "bg-[var(--accent-tint)] font-medium text-[var(--accent-ink)]"
          : "text-muted hover:bg-surface-2 hover:text-ink"
      }`}
    >
      <span className="grid h-4 w-4 shrink-0 place-items-center text-current">{icon}</span>
      <span className="truncate">{children}</span>
    </Link>
  );
}

function NavContent({
  jobId,
  pathname,
  onNavigate,
}: {
  jobId: string | null;
  pathname: string;
  onNavigate?: () => void;
}) {
  const [jobTitle, setJobTitle] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    if (!jobId) {
      setJobTitle(null);
      return;
    }
    getJob(jobId)
      .then((j) => live && setJobTitle(j.title))
      .catch(() => live && setJobTitle(jobId));
    return () => {
      live = false;
    };
  }, [jobId]);

  return (
    <div className="space-y-1">
      <NavItem href="/" active={pathname === "/"} onNavigate={onNavigate} icon={<IconJobs />}>
        Jobs
      </NavItem>
      <NavItem
        href="/jobs/new"
        active={pathname === "/jobs/new"}
        onNavigate={onNavigate}
        icon={<IconPlus />}
      >
        New job
      </NavItem>

      {jobId && (
        <div className="pt-4">
          <div className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-faint">
            Current job
          </div>
          <div className="ml-2 border-l border-line pl-2">
            <div className="truncate px-2 py-1 font-display text-sm font-medium text-ink">
              {jobTitle ?? jobId}
            </div>
            <div className="space-y-0.5">
              <NavItem
                href={`/jobs/${jobId}`}
                active={pathname === `/jobs/${jobId}`}
                onNavigate={onNavigate}
                icon={<IconPipeline />}
              >
                Pipeline
              </NavItem>
              <NavItem
                href={`/jobs/${jobId}/settings`}
                active={pathname === `/jobs/${jobId}/settings`}
                onNavigate={onNavigate}
                icon={<IconSettings />}
              >
                Settings
              </NavItem>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const jobId = deriveJobId(pathname);
  const close = useCallback(() => setOpen(false), []);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // The login screen is its own full-bleed surface — no app chrome.
  if (pathname === "/login") return <>{children}</>;

  return (
    <div className="md:flex md:min-h-dvh">
      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex h-14 items-center border-b border-line px-3">
          <Brand />
        </div>
        <nav className="thin-scroll flex-1 overflow-y-auto p-3">
          <NavContent jobId={jobId} pathname={pathname} />
        </nav>
        <AccountFooter />
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-line bg-[var(--surface)]/90 px-4 backdrop-blur md:hidden">
        <Brand />
        <button
          onClick={() => setOpen(true)}
          aria-label="Open menu"
          className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
        >
          <IconMenu />
        </button>
      </header>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={close} />
          <div className="absolute left-0 top-0 flex h-full w-72 max-w-[82%] flex-col border-r border-line bg-surface">
            <div className="flex h-14 items-center justify-between border-b border-line px-3">
              <Brand />
              <button
                onClick={close}
                aria-label="Close menu"
                className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
              >
                <IconClose />
              </button>
            </div>
            <nav className="thin-scroll flex-1 overflow-y-auto p-3">
              <NavContent jobId={jobId} pathname={pathname} onNavigate={close} />
            </nav>
            <AccountFooter />
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

// -- icons (small, inline) --------------------------------------------------
const S = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
function IconJobs() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <rect x="2.5" y="4" width="11" height="9" rx="1.5" />
      <path d="M6 4V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1" />
    </svg>
  );
}
function IconPlus() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <path d="M8 3.5v9M3.5 8h9" />
    </svg>
  );
}
function IconPipeline() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <path d="M3 4.5h10M3 8h10M3 11.5h6" />
    </svg>
  );
}
function IconSettings() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7 3.6 3.6" />
    </svg>
  );
}
function IconLogout() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <path d="M10 11.5V13a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1H9a1 1 0 0 1 1 1v1.5" />
      <path d="M6.5 8h7M11 5.5 13.5 8 11 10.5" />
    </svg>
  );
}
function IconMenu() {
  return (
    <svg viewBox="0 0 16 16" className="h-5 w-5" {...S}>
      <path d="M3 4.5h10M3 8h10M3 11.5h10" />
    </svg>
  );
}
function IconClose() {
  return (
    <svg viewBox="0 0 16 16" className="h-5 w-5" {...S}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}
