"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getJob,
  getJobSummary,
  ingestJob,
  listJobCandidates,
  type CandidateRecord,
  type Job,
  type JobSummary,
  type Recommendation,
} from "@/lib/api";
import { DECISION_META, TierBar, TIER_META, VerdictTrack } from "@/components/verdict";
import { Button, Card, Label, Spinner } from "@/components/ui";
import { SlideOver } from "@/components/SlideOver";
import { CandidateDetail } from "@/components/CandidateDetail";
import { SendAssignments } from "@/components/SendAssignments";
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
  const [ingesting, setIngesting] = useState(false);

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
    try {
      await ingestJob(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingestion failed.");
    } finally {
      setIngesting(false);
    }
  }

  const connected = Boolean(job?.google_sheet_id);
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
            <span
              className="inline-flex items-center gap-1.5"
              style={{ color: connected ? "var(--tier-shortlist)" : "var(--muted)" }}
            >
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: connected ? "var(--tier-shortlist)" : "var(--faint)" }} />
              {connected ? "Connected to a form" : "Not connected"}
            </span>
            <Link href={`/jobs/${id}/settings`} className="text-[var(--accent-ink)] hover:underline">
              Settings
            </Link>
          </div>
          {job && (
            <div className="mt-2 max-w-2xl">
              <button onClick={() => setJdOpen((v) => !v)} className="text-sm text-muted hover:text-ink">
                {jdOpen ? "Hide description" : "Job description"} <span className="text-faint">{jdOpen ? "▲" : "▼"}</span>
              </button>
              {jdOpen && (
                <p className="mt-2 whitespace-pre-line rounded-xl border border-line bg-surface p-4 text-sm leading-relaxed text-muted">
                  {job.job_description}
                </p>
              )}
            </div>
          )}
        </div>

        {summary && (
          <div className="flex shrink-0 flex-col items-stretch gap-3">
            <Button onClick={() => setSendOpen(true)}>
              Send assignments{readyCount > 0 ? ` (${readyCount} ready)` : ""}
            </Button>
            <Card className="w-64 p-4">
              <Label>Pipeline</Label>
              <div className="mt-2">
                <TierBar counts={summary.by_tier} total={summary.total} />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <Stat label="Total" value={summary.total} />
                <Stat label="Shortlisted" value={summary.by_status.shortlisted} />
                <Stat label="Sent" value={summary.by_status.assignment_sent} />
              </div>
              <div className="mt-3 border-t border-line pt-3">
                <Button size="sm" variant="secondary" loading={ingesting} onClick={onIngest} className="w-full">
                  Run ingestion
                </Button>
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
            <p className="mt-1 text-sm text-muted">Run ingestion to pull and score applicants for this role.</p>
            <div className="mt-4">
              <Button size="sm" loading={ingesting} onClick={onIngest}>
                Run ingestion
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
        {openId && <CandidateDetail candidateId={openId} onClose={() => setOpenId(null)} onChanged={() => void refresh()} />}
      </SlideOver>

      <SlideOver open={sendOpen} onClose={() => setSendOpen(false)}>
        {sendOpen && <SendAssignments jobId={id} onClose={() => setSendOpen(false)} onChanged={() => void refresh()} />}
      </SlideOver>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-surface-2 py-1.5">
      <div className="font-mono text-base font-semibold tabular-nums">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-faint">{label}</div>
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
