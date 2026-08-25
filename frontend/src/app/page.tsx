"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  DEMO_MODE,
  getJobSummary,
  ingestJob,
  listJobs,
  type IngestionSummary,
  type Job,
  type JobSummary,
} from "@/lib/api";
import { TierBar, TIER_META, TIER_ORDER } from "@/components/verdict";
import { Button, Card, Spinner, StatTile } from "@/components/ui";

export default function JobsOverview() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, JobSummary>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, IngestionSummary>>({});
  const [ingestErr, setIngestErr] = useState<Record<string, string>>({});

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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load jobs. Is the backend running?");
      setJobs([]);
    }
  }, [loadSummary]);

  useEffect(() => {
    void load();
  }, [load]);

  // Aggregate readout across every job (updates as summaries stream in).
  const totals = useMemo(() => {
    const list = jobs ?? [];
    const vals = Object.values(summaries);
    return {
      openRoles: list.filter((j) => j.status === "open").length,
      roles: list.length,
      candidates: vals.reduce((n, s) => n + s.total, 0),
      shortlisted: vals.reduce((n, s) => n + s.by_status.shortlisted, 0),
      sent: vals.reduce((n, s) => n + s.by_status.assignment_sent, 0),
    };
  }, [jobs, summaries]);

  async function onIngest(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    setIngestErr((m) => ({ ...m, [id]: "" }));
    try {
      const res = await ingestJob(id);
      setResults((r) => ({ ...r, [id]: res }));
      await loadSummary(id);
    } catch (e) {
      setIngestErr((m) => ({ ...m, [id]: e instanceof Error ? e.message : "Ingestion failed." }));
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  const hasJobs = (jobs?.length ?? 0) > 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header + New job */}
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-medium tracking-tight">Jobs</h1>
          <p className="mt-1 text-sm text-muted">Open roles and their candidate pipelines.</p>
        </div>
        <Link href="/jobs/new">
          <Button size="sm">
            <IconPlus /> New job
          </Button>
        </Link>
      </div>

      {/* Overview strip — aggregate readout across all jobs */}
      {hasJobs && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Open roles" value={jobs === null ? "—" : totals.openRoles} icon={<IconBriefcase />} tone="var(--accent)" />
          <StatTile label="Candidates" value={jobs === null ? "—" : totals.candidates} icon={<IconUsers />} />
          <StatTile label="Shortlisted" value={jobs === null ? "—" : totals.shortlisted} icon={<IconStar />} tone="var(--tier-shortlist)" />
          <StatTile label="Assignments sent" value={jobs === null ? "—" : totals.sent} icon={<IconSend />} tone="var(--dec-sent)" />
        </div>
      )}

      {error && (
        <div
          className="mt-4 rounded-lg px-3 py-2 text-sm"
          style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
        >
          {error}
        </div>
      )}

      {jobs === null ? (
        <div className="mt-6 flex items-center gap-2 py-16 text-muted">
          <Spinner /> Loading jobs…
        </div>
      ) : jobs.length === 0 ? (
        <Card className="mt-6 px-6 py-16 text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[var(--accent-tint)] text-[var(--accent-ink)]">
            <IconBriefcase />
          </div>
          <h2 className="mt-4 font-display text-lg font-medium">Create your first job</h2>
          <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">
            A job holds a description, the criteria you score against, and a link to its Google Form.
            Candidates are ingested and AI-scored per role.
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
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              summary={summaries[job.id]}
              busy={!!busy[job.id]}
              result={results[job.id]}
              ingestError={ingestErr[job.id]}
              onOpen={() => router.push(`/jobs/${job.id}`)}
              onIngest={() => void onIngest(job.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function JobCard({
  job,
  summary,
  busy,
  result,
  ingestError,
  onOpen,
  onIngest,
}: {
  job: Job;
  summary: JobSummary | undefined;
  busy: boolean;
  result?: IngestionSummary;
  ingestError?: string;
  onOpen: () => void;
  onIngest: () => void;
}) {
  const total = summary?.total ?? 0;
  const connected = Boolean(job.google_sheet_id);
  const open = job.status === "open";

  return (
    <Card elevated onClick={onOpen} className="group flex cursor-pointer flex-col p-5">
      {/* Title + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-display text-[17px] font-medium tracking-tight decoration-[var(--line-2)] underline-offset-4 group-hover:underline">
            {job.title}
          </h2>
          <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs" style={{ color: connected ? "var(--tier-shortlist)" : "var(--muted)" }}>
            <IconLink muted={!connected} />
            {connected ? "Connected to a form" : "Not connected"}
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

      {/* Tier mini-dashboard */}
      <div className="mt-4 flex-1">
        {summary === undefined ? (
          <div className="space-y-2.5">
            <div className="h-2 w-full animate-pulse rounded-full bg-surface-2" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-surface-2" />
          </div>
        ) : total === 0 ? (
          <div className="rounded-lg border border-dashed border-line-2 bg-surface-2/40 px-3 py-3 text-xs text-muted">
            No candidates yet — run ingestion to pull applicants.
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

      {/* Actions */}
      <div className="mt-4 flex items-center gap-2 border-t border-line pt-3">
        <span className="text-sm font-medium text-[var(--accent-ink)] group-hover:underline">Open pipeline →</span>
        <div className="ml-auto flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            loading={busy}
            onClick={(e) => {
              e.stopPropagation();
              onIngest();
            }}
          >
            Run ingestion
          </Button>
          <Link
            href={`/jobs/${job.id}/settings`}
            onClick={(e) => e.stopPropagation()}
            aria-label="Job settings"
            title="Settings"
            className="grid h-8 w-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <IconGear />
          </Link>
        </div>
      </div>
      {ingestError && (
        <div className="mt-2 rounded-lg px-2.5 py-1.5 text-xs" style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}>
          {ingestError}
        </div>
      )}
      {result && (
        <div className="mt-2">
          <div className="flex items-center gap-3 font-mono text-[11px] tabular-nums">
            <span style={{ color: "var(--tier-shortlist)" }}>{result.processed} new</span>
            <span className="text-muted">{result.skipped} already in</span>
            <span style={{ color: result.failed ? "var(--tier-reject)" : "var(--faint)" }}>{result.failed} failed</span>
          </div>
          {DEMO_MODE && (
            <div className="mt-1 text-[11px]" style={{ color: "var(--accent-ink)" }}>
              Demo build — ingestion simulated (no fetch).
            </div>
          )}
          {result.failures.length > 0 && (
            <ul className="mt-1.5 space-y-1 text-[11px] text-muted">
              {result.failures.slice(0, 3).map((f, i) => (
                <li key={`${f.submission_ref}-${i}`} className="truncate">
                  <span style={{ color: "var(--tier-reject)" }}>•</span>{" "}
                  <span className="text-ink">{f.name || f.submission_ref}</span> — {f.reason}
                </li>
              ))}
              {result.failures.length > 3 && (
                <li className="text-faint">+{result.failures.length - 3} more — open the pipeline for details</li>
              )}
            </ul>
          )}
        </div>
      )}
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
function IconLink({ muted }: { muted?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" {...S} strokeWidth={muted ? 1.5 : 1.7}>
      <path d="M6.5 9.5l3-3M6 5.5H4.5a2.5 2.5 0 0 0 0 5H6M10 10.5h1.5a2.5 2.5 0 0 0 0-5H10" />
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
