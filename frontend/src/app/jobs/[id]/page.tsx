"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  DEMO_MODE,
  fetchMe,
  getJob,
  getJobPullProgress,
  getJobRescoreProgress,
  getJobSkipped,
  getJobSummary,
  listJobCandidates,
  listRoles,
  startJobPull,
  startJobRescore,
  type CandidateRecord,
  type Job,
  type JobSummary,
  type Recommendation,
  type SiteIngestionSummary,
} from "@/lib/api";
import { DECISION_META, TierBar, TIER_META, VerdictTrack } from "@/components/verdict";
import { Button, Card, Label, Spinner } from "@/components/ui";
import { SlideOver } from "@/components/SlideOver";
import { CandidateDetail } from "@/components/CandidateDetail";
import { SendAssignments } from "@/components/SendAssignments";
import { AddCandidate } from "@/components/AddCandidate";
import { initials } from "@/lib/format";

type Tab = "all" | "shortlist" | "borderline" | "reject";
// All first, and the default landing tab. Tabs filter PURELY by AI tier.
const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "shortlist", label: "Shortlist" },
  { key: "borderline", label: "Borderline" },
  { key: "reject", label: "Reject" },
];

const scoreOf = (r: CandidateRecord) => r.evaluation?.overall_score ?? -1;
const byScore = (a: CandidateRecord, b: CandidateRecord) => scoreOf(b) - scoreOf(a);

export default function JobPipeline({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [job, setJob] = useState<Job | null>(null);
  const [summary, setSummary] = useState<JobSummary | null>(null);
  const [all, setAll] = useState<CandidateRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jdOpen, setJdOpen] = useState(false);

  const [tab, setTab] = useState<Tab>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<SiteIngestionSummary | null>(null);
  const [progress, setProgress] = useState<{ processed: number; total: number } | null>(null);
  const [rescoring, setRescoring] = useState(false);
  const [rescoreProgress, setRescoreProgress] = useState<{ processed: number; total: number } | null>(null);
  const [roleCount, setRoleCount] = useState<number | null>(null);
  const [skippedCount, setSkippedCount] = useState(0);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    let live = true;
    fetchMe().then((m) => live && setIsAdmin(!!m.is_admin)).catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [rows, s] = await Promise.all([listJobCandidates(id), getJobSummary(id)]);
      setAll(rows);
      setSummary(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't refresh.");
    }
  }, [id]);

  useEffect(() => {
    (async () => {
      setError(null);
      try {
        const [j, s, rows] = await Promise.all([
          getJob(id),
          getJobSummary(id),
          listJobCandidates(id),
        ]);
        setJob(j);
        setSummary(s);
        setAll(rows);
        // How many applicants on the form picked this role (so the user knows the
        // size before a manual pull). Best-effort — reads the sheet, may be slow.
        listRoles()
          .then((roles) => {
            const match = roles.find((r) => r.role === j.role_key);
            setRoleCount(match ? match.applicant_count : null);
          })
          .catch(() => setRoleCount(null));
        getJobSkipped(id)
          .then((s) => setSkippedCount(s.count))
          .catch(() => setSkippedCount(0));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't load this job.");
        setAll([]);
      }
    })();
  }, [id]);

  // Tab lists are strictly by AI tier — a candidate is in exactly one tier + All.
  const lists = useMemo(() => {
    const rows = all ?? [];
    const tier = (t: Recommendation) => rows.filter((r) => r.evaluation?.recommendation === t).sort(byScore);
    return {
      all: [...rows].sort(byScore),
      shortlist: tier("shortlist"),
      borderline: tier("borderline"),
      reject: tier("reject"),
    };
  }, [all]);
  const rows = lists[tab];

  async function onIngest() {
    setIngesting(true);
    setError(null);
    setIngestResult(null);
    setProgress(null);
    try {
      // Per-job pull: only this job's applicants are downloaded + scored.
      let snap = await startJobPull(id);
      while (snap.status === "running") {
        setProgress({ processed: snap.processed ?? 0, total: snap.total ?? 0 });
        await new Promise((r) => setTimeout(r, 2000));
        snap = await getJobPullProgress(id);
      }
      if (snap.status === "error") setError(snap.error || "Pull failed. Try again.");
      else if (snap.summary) setIngestResult(snap.summary as SiteIngestionSummary);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't pull applicants.");
    } finally {
      setIngesting(false);
      setProgress(null);
    }
  }

  async function onRescoreAll() {
    setRescoring(true);
    setError(null);
    setRescoreProgress(null);
    try {
      let snap = await startJobRescore(id);
      while (snap.status === "running") {
        setRescoreProgress({ processed: snap.processed ?? 0, total: snap.total ?? 0 });
        await new Promise((r) => setTimeout(r, 2000));
        snap = await getJobRescoreProgress(id);
      }
      if (snap.status === "error") setError(snap.error || "Rescore failed. Try again.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't rescore candidates.");
    } finally {
      setRescoring(false);
      setRescoreProgress(null);
    }
  }

  const readyCount = summary?.by_status.shortlisted ?? 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="font-display text-2xl font-medium tracking-tight">{job?.title ?? "…"}</h1>
            {job && (
              <span
                className="rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize"
                style={{
                  color: job.status === "open" ? "var(--accent-ink)" : "var(--muted)",
                  borderColor: "var(--line-2)",
                }}
              >
                {job.status}
              </span>
            )}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
            {job?.role_key && (
              <span className="inline-flex items-center gap-1.5 text-muted">
                <span className="text-faint">Serves form role</span>
                <span className="rounded border border-line-2 px-1.5 py-0.5 font-medium text-ink">{job.role_key}</span>
              </span>
            )}
            <Link href={`/jobs/${id}/settings`} className="text-[var(--accent-ink)] hover:underline">
              Settings
            </Link>
          </div>
          {job && job.job_description.trim() && (
            <div className="mt-3 max-w-2xl">
              <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">
                Job description
              </div>
              <p
                className={`mt-1 whitespace-pre-line text-sm leading-relaxed text-muted ${
                  jdOpen ? "" : "line-clamp-2"
                }`}
              >
                {job.job_description}
              </p>
              {job.job_description.length > 140 && (
                <button
                  onClick={() => setJdOpen((v) => !v)}
                  className="mt-1 text-xs font-medium text-[var(--accent-ink)] hover:underline"
                >
                  {jdOpen ? "See less" : "See more"}
                </button>
              )}
            </div>
          )}
        </div>

        {summary && (
          <div className="flex shrink-0 flex-col items-stretch gap-3">
            <Button onClick={() => setSendOpen(true)}>
              Send assignments{readyCount > 0 ? ` (${readyCount} ready)` : ""}
            </Button>
            <Card className="w-72 p-4">
              <Label>Pipeline</Label>
              <div className="mt-2">
                <TierBar counts={summary.by_tier} total={summary.total} />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <Stat label="Total" value={summary.total} />
                <Stat label="Shortlisted" value={summary.by_status.shortlisted} />
                <Stat label="Sent" value={summary.by_status.assignment_sent} />
              </div>
              <div className="mt-3 space-y-2 border-t border-line pt-3">
                {isAdmin ? (
                  roleCount !== null && (() => {
                    const toPull = Math.max(0, roleCount - summary.total - skippedCount);
                    return (
                      <p className="text-[11px] leading-snug text-muted">
                        <span className="font-semibold text-ink">{roleCount}</span> applicant{roleCount === 1 ? "" : "s"} picked this role
                        {summary.total > 0 ? ` · ${summary.total} scored` : ""}
                        {skippedCount > 0 ? ` · ${skippedCount} unreadable (skipped)` : ""}.
                        {toPull > 0 ? ` Pull scores the ${toPull} new one${toPull === 1 ? "" : "s"}.` : " All caught up."}
                      </p>
                    );
                  })()
                ) : (
                  <p className="text-[11px] leading-snug text-muted">All applicants have been pulled.</p>
                )}
                <Button size="sm" variant="secondary" loading={ingesting} onClick={onIngest} className="w-full">
                  {ingesting
                    ? progress && progress.total
                      ? `Pulling ${progress.processed} of ${progress.total}…`
                      : "Starting…"
                    : isAdmin && roleCount !== null
                      ? `Pull applicants (${Math.max(0, roleCount - summary.total - skippedCount)} new)`
                      : "Pull applicants"}
                </Button>
                <Button size="sm" variant="ghost" loading={rescoring} onClick={onRescoreAll} className="w-full">
                  {rescoring
                    ? rescoreProgress && rescoreProgress.total
                      ? `Rescoring ${rescoreProgress.processed} of ${rescoreProgress.total}…`
                      : "Starting…"
                    : "Rescore all"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setAddOpen(true)} className="w-full">
                  Add candidate
                </Button>
                {(ingesting || rescoring) && (
                  <p className="text-[11px] leading-snug text-muted">
                    Runs in the background — this can take a few minutes for many applicants. You can keep working.
                  </p>
                )}
              </div>
            </Card>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-lg px-3 py-2 text-sm" style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}>
          {error}
        </div>
      )}

      {ingestResult && (
        <IngestSummary result={ingestResult} onDismiss={() => setIngestResult(null)} />
      )}

      {/* Tabs — AI tier only */}
      <div className="mt-6 flex items-center gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`relative -mb-px flex items-center gap-2 whitespace-nowrap px-3.5 py-2.5 text-sm font-medium transition-colors ${active ? "text-ink" : "text-muted hover:text-ink"}`}
            >
              {t.key !== "all" && (
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: TIER_META[t.key as Recommendation].color }} />
              )}
              {t.label}
              <span className={`font-mono text-xs tabular-nums ${active ? "text-muted" : "text-faint"}`}>
                {all === null ? "" : lists[t.key].length}
              </span>
              {active && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-ink" />}
            </button>
          );
        })}
      </div>

      {/* List */}
      <div className="mt-4">
        {all === null ? (
          <div className="flex items-center gap-2 py-16 text-muted">
            <Spinner /> Loading candidates…
          </div>
        ) : (all?.length ?? 0) === 0 ? (
          <Card className="px-6 py-14 text-center">
            <h2 className="font-display text-base font-medium">No candidates yet</h2>
            <p className="mt-1 text-sm text-muted">Pull applicants to fetch and score everyone who picked this role on the form.</p>
            <div className="mt-4">
              <Button size="sm" loading={ingesting} onClick={onIngest}>
                {ingesting
                  ? progress && progress.total
                    ? `Pulling ${progress.processed} of ${progress.total}…`
                    : "Starting…"
                  : "Pull applicants"}
              </Button>
            </div>
          </Card>
        ) : rows.length === 0 ? (
          <Card className="px-6 py-12 text-center">
            <p className="text-sm text-muted">No candidates in this tier.</p>
          </Card>
        ) : (
          <Card className="divide-y divide-line overflow-hidden">
            {rows.map((r) => (
              <Row key={r.candidate.id} r={r} onOpen={() => setOpenId(r.candidate.id)} />
            ))}
          </Card>
        )}
      </div>

      <SlideOver open={openId !== null} onClose={() => setOpenId(null)}>
        {openId && (
          <CandidateDetail
            candidateId={openId}
            onClose={() => setOpenId(null)}
            onChanged={() => void refresh()}
            onOpenSend={() => {
              setOpenId(null);
              setSendOpen(true);
            }}
          />
        )}
      </SlideOver>

      <SlideOver open={sendOpen} onClose={() => setSendOpen(false)}>
        {sendOpen && <SendAssignments jobId={id} onClose={() => setSendOpen(false)} onChanged={() => void refresh()} />}
      </SlideOver>

      <SlideOver open={addOpen} onClose={() => setAddOpen(false)}>
        {addOpen && (
          <AddCandidate
            jobId={id}
            onClose={() => setAddOpen(false)}
            onAdded={(cid) => {
              setAddOpen(false);
              void refresh();
              setOpenId(cid);
            }}
          />
        )}
      </SlideOver>
    </div>
  );
}

function IngestSummary({ result, onDismiss }: { result: SiteIngestionSummary; onDismiss: () => void }) {
  const held = Object.entries(result.held_by_role);
  const nothing = result.processed === 0 && result.skipped_duplicate === 0 && held.length === 0 && result.failed === 0;
  return (
    <div className="mt-4 rounded-xl border border-line bg-surface p-3.5 shadow-[var(--shadow-sm)]">
      <div className="flex items-center gap-4 text-sm">
        <span className="font-medium">Pulled applicants</span>
        <span className="flex items-center gap-3 font-mono text-xs tabular-nums">
          <span style={{ color: "var(--tier-shortlist)" }}>{result.processed} new</span>
          <span className="text-muted">{result.skipped_duplicate} already in</span>
          <span style={{ color: result.failed ? "var(--tier-reject)" : "var(--faint)" }}>{result.failed} failed</span>
        </span>
        <button onClick={onDismiss} aria-label="Dismiss" className="ml-auto text-faint hover:text-ink">✕</button>
      </div>
      {DEMO_MODE ? (
        <p className="mt-1.5 text-xs" style={{ color: "var(--accent-ink)" }}>
          Demo build — pulling is simulated; no applicants are fetched from a form.
        </p>
      ) : (
        nothing && (
          <p className="mt-1.5 text-xs text-muted">No new applicants — everyone on the form is already ingested.</p>
        )
      )}
      {held.length > 0 && (
        <p className="mt-1.5 text-xs" style={{ color: "var(--tier-borderline)" }}>
          {held.map(([role, count]) => `${count} for ${role}`).join(", ")} — waiting on a job (set them up from the Jobs dashboard).
        </p>
      )}
      {result.failures.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-line pt-2 text-xs text-muted">
          {result.failures.map((f, i) => (
            <li key={`${f.submission_ref}-${i}`} className="flex gap-2">
              <span aria-hidden style={{ color: "var(--tier-reject)" }}>•</span>
              <span className="min-w-0">
                <span className="font-medium text-ink">{f.name || f.submission_ref}</span>
                {" — "}
                {f.reason}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 rounded-lg bg-surface-2 px-1 py-1.5">
      <div className="font-mono text-base font-semibold tabular-nums">{value}</div>
      <div className="truncate text-[9px] font-medium uppercase leading-tight tracking-[0.02em] text-faint">
        {label}
      </div>
    </div>
  );
}

function Row({ r, onOpen }: { r: CandidateRecord; onOpen: () => void }) {
  const c = r.candidate;
  const tier = r.evaluation?.recommendation ?? null;
  const dec = DECISION_META[c.status];
  return (
    <div onClick={onOpen} className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2/50">
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-xs font-medium text-muted">
        {initials(c.name)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{c.name ?? "Unknown"}</div>
        <div className="truncate text-xs text-muted">{c.email ?? "—"}</div>
      </div>
      <div className="hidden w-12 shrink-0 text-right font-mono text-sm tabular-nums sm:block">
        {r.evaluation ? r.evaluation.overall_score.toFixed(1) : "—"}
      </div>
      <div className="flex shrink-0 items-center gap-2.5">
        <span className="hidden w-16 text-right text-xs font-medium md:inline" style={{ color: tier ? TIER_META[tier].color : "var(--faint)" }}>
          {tier ? TIER_META[tier].label : "Unscored"}
        </span>
        <VerdictTrack tier={tier} status={c.status} />
        <span className="w-28 text-xs font-medium" style={{ color: dec.kind === "undecided" ? "var(--muted)" : dec.color }}>
          {dec.label}
        </span>
      </div>
      <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-faint" fill="none">
        <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}
