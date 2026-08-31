"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  DEMO_MODE,
  getIngestProgress,
  getIntakeStatus,
  getJobSummary,
  listJobs,
  listRoles,
  startIngest,
  type IntakeStatus,
  type Job,
  type JobSummary,
  type RoleInfo,
  type SiteIngestionSummary,
} from "@/lib/api";
import { TierBar, TIER_META, TIER_ORDER } from "@/components/verdict";
import { Button, Card, Spinner, StatTile } from "@/components/ui";

export default function JobsOverview() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, JobSummary>>({});
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [rolesLoading, setRolesLoading] = useState(true);
  const [status, setStatus] = useState<IntakeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [pulling, setPulling] = useState(false);
  const [pullResult, setPullResult] = useState<SiteIngestionSummary | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);
  const [pullProgress, setPullProgress] = useState<{ processed: number; total: number } | null>(null);

  const loadSummary = useCallback(async (id: string) => {
    try {
      const s = await getJobSummary(id);
      setSummaries((m) => ({ ...m, [id]: s }));
    } catch {
      /* leave missing */
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const js = await listJobs();
      setJobs(js);
      js.forEach((j) => void loadSummary(j.id));
      setRolesLoading(true);
      listRoles()
        .then(setRoles)
        .catch(() => setRoles([]))
        .finally(() => setRolesLoading(false));
      getIntakeStatus().then(setStatus).catch(() => setStatus(null));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load jobs. Is the backend running?");
      setJobs([]);
    }
  }, [loadSummary]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onPull() {
    setPulling(true);
    setPullError(null);
    setPullResult(null);
    setPullProgress(null);
    try {
      // Start a background pull, then poll for live "X of Y" progress. This
      // avoids the request timing out on hundreds of applicants and shows the
      // user it's working (not stuck). Safe if one is already running.
      let snap = await startIngest();
      while (snap.status === "running") {
        setPullProgress({ processed: snap.processed ?? 0, total: snap.total ?? 0 });
        await new Promise((r) => setTimeout(r, 2000));
        snap = await getIngestProgress();
      }
      if (snap.status === "error") {
        setPullError(snap.error || "Pull failed. Try again.");
      } else if (snap.summary) {
        setPullResult(snap.summary as SiteIngestionSummary);
      }
      await load();
    } catch (e) {
      setPullError(e instanceof Error ? e.message : "Couldn't pull applicants.");
    } finally {
      setPulling(false);
      setPullProgress(null);
    }
  }

  const totals = useMemo(() => {
    const list = jobs ?? [];
    const vals = Object.values(summaries);
    return {
      openRoles: list.filter((j) => j.status === "open").length,
      candidates: vals.reduce((n, s) => n + s.total, 0),
      shortlisted: vals.reduce((n, s) => n + s.by_status.shortlisted, 0),
      sent: vals.reduce((n, s) => n + s.by_status.assignment_sent, 0),
    };
  }, [jobs, summaries]);

  const needsSetup = roles.filter((r) => !r.has_job);
  const hasJobs = (jobs?.length ?? 0) > 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-medium tracking-tight">Jobs</h1>
          <p className="mt-1 text-sm text-muted">One application form, routed to roles automatically.</p>
          {status && <IntakeStatusLine status={status} />}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={onPull} loading={pulling}>
            {!pulling && <IconPull />}{" "}
            {pulling
              ? pullProgress && pullProgress.total
                ? `Pulling ${pullProgress.processed} of ${pullProgress.total}…`
                : "Starting…"
              : "Pull applicants"}
          </Button>
          <Link href="/jobs/new">
            <Button size="sm" variant="secondary">
              <IconPlus /> New job
            </Button>
          </Link>
        </div>
      </div>

      {pulling && (
        <p className="mt-3 text-xs text-muted">
          Pulling &amp; scoring applicants — this can take a few minutes for a large form.
          It runs in the background, so you can keep working; the count updates as each is scored.
        </p>
      )}

      {/* Overview strip */}
      {hasJobs && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Open roles" value={jobs === null ? "—" : totals.openRoles} icon={<IconBriefcase />} tone="var(--accent)" />
          <StatTile label="Candidates" value={jobs === null ? "—" : totals.candidates} icon={<IconUsers />} />
          <StatTile label="Shortlisted" value={jobs === null ? "—" : totals.shortlisted} icon={<IconStar />} tone="var(--tier-shortlist)" />
          <StatTile label="Assignments sent" value={jobs === null ? "—" : totals.sent} icon={<IconSend />} tone="var(--dec-sent)" />
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-lg px-3 py-2 text-sm" style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}>
          {error}
        </div>
      )}
      {pullError && (
        <div className="mt-4 rounded-lg px-3 py-2 text-sm" style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}>
          {pullError}
        </div>
      )}
      {pullResult && <PullSummary result={pullResult} onDismiss={() => setPullResult(null)} />}

      {/* Roles from the application form */}
      {(rolesLoading || roles.length > 0) && (
        <section className="mt-8">
          <div className="flex items-baseline gap-2">
            <h2 className="font-display text-base font-medium">Roles from the application form</h2>
            {rolesLoading ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-faint">
                <Spinner className="h-3 w-3" /> reading the form…
              </span>
            ) : (
              needsSetup.length > 0 && (
                <span className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: "var(--tier-borderline-tint)", color: "var(--tier-borderline)" }}>
                  {needsSetup.length} need{needsSetup.length === 1 ? "s" : ""} setup
                </span>
              )
            )}
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {rolesLoading
              ? Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-[68px] animate-pulse rounded-2xl border border-line bg-surface-2/60" />
                ))
              : roles.map((r) => (
                  <RoleCard key={r.role} role={r} onSetup={() => router.push(`/jobs/new?role=${encodeURIComponent(r.role)}`)} onOpen={(id) => router.push(`/jobs/${id}`)} />
                ))}
          </div>
        </section>
      )}

      {/* Configured jobs */}
      <section className="mt-8">
        {hasJobs && <h2 className="font-display text-base font-medium">Configured jobs</h2>}
        {jobs === null ? (
          <div className="mt-3 flex items-center gap-2 py-16 text-muted">
            <Spinner /> Loading jobs…
          </div>
        ) : jobs.length === 0 ? (
          <Card className="mt-3 px-6 py-16 text-center">
            <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[var(--accent-tint)] text-[var(--accent-ink)]">
              <IconBriefcase />
            </div>
            <h2 className="mt-4 font-display text-lg font-medium">No jobs yet</h2>
            <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">
              {needsSetup.length > 0
                ? "You have applicants for roles above — click “Set up this role” to create the job that scores them."
                : "Create a job for each role on your application form, then Pull applicants."}
            </p>
            <div className="mt-5">
              <Link href="/jobs/new">
                <Button>
                  <IconPlus /> New job
                </Button>
              </Link>
            </div>
          </Card>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} summary={summaries[job.id]} onOpen={() => router.push(`/jobs/${job.id}`)} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function IntakeStatusLine({ status }: { status: IntakeStatus }) {
  const ok = status.connected && status.role_column_detected;
  const color = ok ? "var(--tier-shortlist)" : status.connected ? "var(--tier-borderline)" : "var(--tier-reject)";
  const text = !status.connected
    ? `Application form not connected${status.error ? ` — ${status.error}` : ""}`
    : !status.role_column_detected
      ? "Form connected, but the role column wasn't detected"
      : `Form connected · ${status.row_count} responses · ${status.distinct_roles.length} roles`;
  return (
    <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs" style={{ color }}>
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {text}
    </div>
  );
}

function RoleCard({ role, onSetup, onOpen }: { role: RoleInfo; onSetup: () => void; onOpen: (id: string) => void }) {
  const needs = !role.has_job;
  return (
    <Card
      className="flex items-center gap-3 p-3.5"
      style={needs ? { borderColor: "color-mix(in srgb, var(--tier-borderline) 45%, transparent)" } : undefined}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{role.role}</div>
        <div className="mt-0.5 font-mono text-[11px] text-faint tabular-nums">
          {role.applicant_count} applicant{role.applicant_count === 1 ? "" : "s"}
        </div>
      </div>
      {needs ? (
        <Button size="sm" onClick={onSetup}>
          Set up this role
        </Button>
      ) : (
        <button onClick={() => role.job_id && onOpen(role.job_id)} className="shrink-0 text-xs font-medium text-[var(--accent-ink)] hover:underline">
          Open pipeline →
        </button>
      )}
    </Card>
  );
}

function PullSummary({ result, onDismiss }: { result: SiteIngestionSummary; onDismiss: () => void }) {
  const held = Object.entries(result.held_by_role);
  const nothing = result.processed === 0 && result.skipped_duplicate === 0 && held.length === 0;
  return (
    <div className="mt-4 rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-sm)]">
      <div className="flex items-center gap-4">
        <span className="text-sm font-medium">Pulled applicants</span>
        <span className="flex items-center gap-3 font-mono text-xs tabular-nums">
          <span style={{ color: "var(--tier-shortlist)" }}>{result.processed} new</span>
          <span className="text-muted">{result.skipped_duplicate} already in</span>
          <span style={{ color: result.failed ? "var(--tier-reject)" : "var(--faint)" }}>{result.failed} failed</span>
        </span>
        <button onClick={onDismiss} aria-label="Dismiss" className="ml-auto text-faint hover:text-ink">✕</button>
      </div>

      {DEMO_MODE && (
        <p className="mt-1.5 text-xs" style={{ color: "var(--accent-ink)" }}>
          Demo build — pulling is simulated; no applicants are fetched from a form.
        </p>
      )}
      {nothing && !DEMO_MODE && (
        <p className="mt-1.5 text-xs text-muted">No new applicants — everyone on the form is already ingested.</p>
      )}

      {held.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <div className="text-xs font-medium" style={{ color: "var(--tier-borderline)" }}>
            Applicants waiting for a job to be set up
          </div>
          <ul className="mt-2 space-y-1.5">
            {held.map(([role, count]) => (
              <li key={role} className="flex items-center gap-3 text-sm">
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-mono tabular-nums" style={{ color: "var(--tier-borderline)" }}>{count}</span>{" "}
                  applicant{count === 1 ? "" : "s"} for <span className="font-medium">{role}</span>
                </span>
                <Link href={`/jobs/new?role=${encodeURIComponent(role)}`}>
                  <Button size="sm" variant="secondary">Set up this role</Button>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.failures.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-line pt-2 text-xs text-muted">
          {result.failures.slice(0, 5).map((f, i) => (
            <li key={`${f.submission_ref}-${i}`} className="truncate">
              <span style={{ color: "var(--tier-reject)" }}>•</span>{" "}
              <span className="text-ink">{f.name || f.submission_ref}</span> — {f.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function JobCard({ job, summary, onOpen }: { job: Job; summary: JobSummary | undefined; onOpen: () => void }) {
  const total = summary?.total ?? 0;
  const open = job.status === "open";

  return (
    <Card elevated onClick={onOpen} className="group flex cursor-pointer flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-display text-[17px] font-medium tracking-tight decoration-[var(--line-2)] underline-offset-4 group-hover:underline">
            {job.title}
          </h3>
          <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-muted">
            <IconTag />
            <span className="truncate">{job.role_key || "—"}</span>
          </div>
        </div>
        <span
          className="shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize"
          style={{
            color: open ? "var(--accent-ink)" : "var(--muted)",
            borderColor: open ? "var(--accent)" : "var(--line-2)",
            background: open ? "var(--accent-tint)" : "transparent",
          }}
        >
          {job.status}
        </span>
      </div>

      <div className="mt-4 flex-1">
        {summary === undefined ? (
          <div className="space-y-2.5">
            <div className="h-2 w-full animate-pulse rounded-full bg-surface-2" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-surface-2" />
          </div>
        ) : total === 0 ? (
          <div className="rounded-lg border border-dashed border-line-2 bg-surface-2/40 px-3 py-3 text-xs text-muted">
            No candidates yet — Pull applicants to fetch and score them.
          </div>
        ) : (
          <>
            <TierBar counts={summary.by_tier} total={total} />
            <div className="mt-3 grid grid-cols-3 gap-2">
              {TIER_ORDER.map((t) => (
                <div key={t} className="rounded-lg bg-surface-2/60 px-2 py-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: TIER_META[t].color }} />
                    <span className="truncate text-[10px] font-medium uppercase tracking-[0.04em] text-faint">{TIER_META[t].label}</span>
                  </div>
                  <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums">{summary.by_tier[t]}</div>
                </div>
              ))}
            </div>
            <div className="mt-2.5 flex items-center gap-3 font-mono text-[11px] text-faint tabular-nums">
              <span>{total} total</span>
              <span>· {summary.by_status.shortlisted} shortlisted</span>
              {summary.by_status.assignment_sent > 0 && <span>· {summary.by_status.assignment_sent} sent</span>}
            </div>
          </>
        )}
      </div>

      <div className="mt-4 flex items-center gap-2 border-t border-line pt-3">
        <span className="text-sm font-medium text-[var(--accent-ink)] group-hover:underline">Open pipeline →</span>
        <Link
          href={`/jobs/${job.id}/settings`}
          onClick={(e) => e.stopPropagation()}
          aria-label="Job settings"
          title="Settings"
          className="ml-auto grid h-8 w-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <IconGear />
        </Link>
      </div>
    </Card>
  );
}

// -- tiny inline icons ------------------------------------------------------
const S = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
function IconPlus() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" {...S}>
      <path d="M8 3.5v9M3.5 8h9" />
    </svg>
  );
}
function IconPull() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" {...S}>
      <path d="M8 2.5v7M5 6.5 8 9.5l3-3M3 12.5h10" />
    </svg>
  );
}
function IconBriefcase() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <rect x="2.5" y="4.5" width="11" height="8" rx="1.5" />
      <path d="M6 4.5V3.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1M2.5 8h11" />
    </svg>
  );
}
function IconUsers() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <circle cx="6" cy="6" r="2.2" />
      <path d="M2.5 13c0-2 1.6-3.2 3.5-3.2S9.5 11 9.5 13M10.5 4.2a2 2 0 0 1 0 3.6M11 13c0-1.5-.6-2.6-1.6-3.2" />
    </svg>
  );
}
function IconStar() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <path d="M8 2.5l1.6 3.3 3.6.5-2.6 2.5.6 3.6L8 11.2 4.8 12.9l.6-3.6L2.8 6.8l3.6-.5z" />
    </svg>
  );
}
function IconSend() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" {...S}>
      <path d="M13.5 2.5l-6 6M13.5 2.5l-4 11-2.5-4.5L2.5 6.5z" />
    </svg>
  );
}
function IconTag() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" {...S}>
      <path d="M2.5 7.5v-4a1 1 0 0 1 1-1h4l6 6-5 5-6-6z" />
      <circle cx="5.5" cy="5.5" r=".9" fill="currentColor" stroke="none" />
    </svg>
  );
}
function IconGear() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" {...S} strokeWidth={1.9}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
