"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getJobSummary, ingestJob, listJobs, type Job, type JobSummary } from "@/lib/api";
import { TierBar, TIER_META, TIER_ORDER } from "@/components/verdict";
import { Button, Card, Spinner } from "@/components/ui";

export default function JobsOverview() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, JobSummary>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [flash, setFlash] = useState<Record<string, string>>({});

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

  async function onIngest(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    setFlash((f) => ({ ...f, [id]: "" }));
    try {
      const res = await ingestJob(id);
      await loadSummary(id);
      setFlash((f) => ({
        ...f,
        [id]: `Added ${res.processed} · ${res.skipped} already in${res.failed ? ` · ${res.failed} failed` : ""}`,
      }));
    } catch (e) {
      setFlash((f) => ({ ...f, [id]: e instanceof Error ? e.message : "Ingestion failed." }));
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-medium tracking-tight">Jobs</h1>
          <p className="mt-1 text-sm text-muted">Open roles and their candidate pipelines.</p>
        </div>
        <Link href="/jobs/new">
          <Button size="sm">+ New job</Button>
        </Link>
      </div>

      {error && (
        <div
          className="mb-4 rounded-lg px-3 py-2 text-sm"
          style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
        >
          {error}
        </div>
      )}

      {jobs === null ? (
        <div className="flex items-center gap-2 py-16 text-muted">
          <Spinner /> Loading jobs…
        </div>
      ) : jobs.length === 0 ? (
        <Card className="px-6 py-14 text-center">
          <h2 className="font-display text-base font-medium">Create your first job</h2>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted">
            A job holds a description, the criteria you score against, and a link to its Google Form.
          </p>
          <div className="mt-4">
            <Link href="/jobs/new">
              <Button size="sm">+ New job</Button>
            </Link>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {jobs.map((job) => {
            const s = summaries[job.id];
            const total = s?.total ?? 0;
            const connected = Boolean(job.google_sheet_id);
            return (
              <Card
                key={job.id}
                onClick={() => router.push(`/jobs/${job.id}`)}
                className="group cursor-pointer p-5 transition-colors hover:border-line-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate font-display text-base font-medium tracking-tight group-hover:underline">
                      {job.title}
                    </h2>
                    <div className="mt-1 flex items-center gap-2 text-xs">
                      <span
                        className="inline-flex items-center gap-1.5"
                        style={{ color: connected ? "var(--tier-shortlist)" : "var(--muted)" }}
                      >
                        <span
                          className="inline-block h-1.5 w-1.5 rounded-full"
                          style={{ background: connected ? "var(--tier-shortlist)" : "var(--faint)" }}
                        />
                        {connected ? "Connected to a form" : "Not connected"}
                      </span>
                    </div>
                  </div>
                  <span
                    className="shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize"
                    style={{
                      color: job.status === "open" ? "var(--accent-ink)" : "var(--muted)",
                      borderColor: job.status === "open" ? "var(--accent)" : "var(--line-2)",
                    }}
                  >
                    {job.status}
                  </span>
                </div>

                <div className="mt-4">
                  {s === undefined ? (
                    <div className="h-1.5 w-full animate-pulse rounded-full bg-surface-2" />
                  ) : total === 0 ? (
                    <p className="text-xs text-muted">No candidates yet — run ingestion to pull applicants.</p>
                  ) : (
                    <>
                      <TierBar counts={s.by_tier} total={total} />
                      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                        {TIER_ORDER.map((t) => (
                          <span key={t} className="inline-flex items-center gap-1.5 text-muted">
                            <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: TIER_META[t].color }} />
                            {TIER_META[t].label}
                            <span className="font-mono font-medium text-ink tabular-nums">{s.by_tier[t]}</span>
                          </span>
                        ))}
                        <span className="ml-auto font-mono text-faint tabular-nums">
                          {total} total · {s.by_status.shortlisted} shortlisted
                          {s.by_status.assignment_sent > 0 && <> · {s.by_status.assignment_sent} sent</>}
                        </span>
                      </div>
                    </>
                  )}
                </div>

                <div className="mt-4 flex items-center gap-3 border-t border-line pt-3">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={!!busy[job.id]}
                    onClick={(e) => {
                      e.stopPropagation();
                      void onIngest(job.id);
                    }}
                  >
                    Run ingestion
                  </Button>
                  <span className="text-xs text-[var(--accent-ink)] group-hover:underline">Open pipeline →</span>
                  <Link
                    href={`/jobs/${job.id}/settings`}
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs text-muted hover:text-ink hover:underline"
                  >
                    Settings
                  </Link>
                  {flash[job.id] && (
                    <span className="ml-auto truncate font-mono text-xs text-faint">{flash[job.id]}</span>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
