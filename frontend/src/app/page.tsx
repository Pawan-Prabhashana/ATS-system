"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getJobSummary,
  ingestJob,
  listJobs,
  type Job,
  type JobSummary,
} from "@/lib/api";
import { TierBar, TIER_META, TIER_ORDER } from "@/components/badges";
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
      /* leave summary missing */
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const js = await listJobs();
      setJobs(js);
      js.forEach((j) => void loadSummary(j.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs.");
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
        [id]: `Ingested ${res.processed} · ${res.skipped} skipped${
          res.failed ? ` · ${res.failed} failed` : ""
        }`,
      }));
    } catch (e) {
      setFlash((f) => ({
        ...f,
        [id]: e instanceof Error ? e.message : "Ingestion failed.",
      }));
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
        <p className="mt-1 text-sm text-ink-2">
          Open roles and their candidate pipelines.
        </p>
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
          <p className="text-sm text-ink-2">No jobs yet.</p>
          <p className="mt-1 text-xs text-muted">
            Seed sample jobs from the backend:{" "}
            <code className="font-mono">python -m app.cli seed-jobs</code>
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {jobs.map((job) => {
            const s = summaries[job.id];
            const total = s?.total ?? 0;
            return (
              <Card
                key={job.id}
                onClick={() => router.push(`/jobs/${job.id}`)}
                className="group cursor-pointer p-5 transition-colors hover:border-line-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold tracking-tight group-hover:underline">
                      {job.title}
                    </h2>
                    <div className="mt-0.5 font-mono text-xs text-muted">{job.id}</div>
                  </div>
                  <span
                    className="shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize"
                    style={{
                      color: job.status === "open" ? "var(--tier-shortlist)" : "var(--muted)",
                      borderColor:
                        job.status === "open"
                          ? "color-mix(in srgb, var(--tier-shortlist) 35%, transparent)"
                          : "var(--line-2)",
                    }}
                  >
                    {job.status}
                  </span>
                </div>

                {/* Summary */}
                <div className="mt-4">
                  {s === undefined ? (
                    <div className="h-1.5 w-full animate-pulse rounded-full bg-surface-2" />
                  ) : total === 0 ? (
                    <p className="text-xs text-muted">
                      No candidates yet — run ingestion to populate.
                    </p>
                  ) : (
                    <>
                      <TierBar counts={s.by_tier} total={total} />
                      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                        {TIER_ORDER.map((t) => (
                          <span key={t} className="inline-flex items-center gap-1.5 text-ink-2">
                            <span
                              className="inline-block h-1.5 w-1.5 rounded-full"
                              style={{ background: TIER_META[t].dot }}
                            />
                            {TIER_META[t].label}
                            <span className="font-mono font-medium text-ink tabular-nums">
                              {s.by_tier[t]}
                            </span>
                          </span>
                        ))}
                        <span className="ml-auto text-muted">
                          {total} total ·{" "}
                          <span className="text-ink-2">
                            {s.by_status.shortlisted} shortlisted
                          </span>
                          {s.by_status.assignment_sent > 0 && (
                            <>
                              {" "}
                              · {s.by_status.assignment_sent} sent
                            </>
                          )}
                        </span>
                      </div>
                    </>
                  )}
                </div>

                {/* Actions */}
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
                  <span className="text-xs text-link group-hover:underline">
                    Open pipeline →
                  </span>
                  {flash[job.id] && (
                    <span className="ml-auto truncate text-xs text-muted">
                      {flash[job.id]}
                    </span>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </main>
  );
}
