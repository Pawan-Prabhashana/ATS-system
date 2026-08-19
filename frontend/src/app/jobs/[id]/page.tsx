"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  bulkSendAssignments,
  getJob,
  getJobSummary,
  ingestJob,
  listJobCandidates,
  type BulkSendResult,
  type CandidateRecord,
  type Job,
  type JobSummary,
  type Recommendation,
} from "@/lib/api";
import {
  DECISION_META,
  TierBar,
  TierChip,
  TIER_META,
  VerdictTrack,
} from "@/components/verdict";
import { Button, Card, Checkbox, Label, Spinner } from "@/components/ui";
import { SlideOver } from "@/components/SlideOver";
import { CandidateDetail } from "@/components/CandidateDetail";
import { initials } from "@/lib/format";

type Tab = "shortlist" | "borderline" | "reject" | "all";
const TABS: { key: Tab; label: string }[] = [
  { key: "shortlist", label: "Shortlist" },
  { key: "borderline", label: "Borderline" },
  { key: "reject", label: "Reject" },
  { key: "all", label: "All" },
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

  const [tab, setTab] = useState<Tab>("shortlist");
  const [openId, setOpenId] = useState<string | null>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [force, setForce] = useState(false);
  const [sending, setSending] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkSendResult | null>(null);
  const [ingesting, setIngesting] = useState(false);

  const loadCandidates = useCallback(async () => {
    const rows = await listJobCandidates(id);
    setAll(rows);
    return rows;
  }, [id]);

  const refresh = useCallback(async () => {
    try {
      const [, s] = await Promise.all([loadCandidates(), getJobSummary(id)]);
      setSummary(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't refresh.");
    }
  }, [id, loadCandidates]);

  useEffect(() => {
    (async () => {
      setError(null);
      try {
        const [j, s] = await Promise.all([getJob(id), getJobSummary(id)]);
        setJob(j);
        setSummary(s);
        await loadCandidates();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't load this job.");
        setAll([]);
      }
    })();
  }, [id, loadCandidates]);

  const lists = useMemo(() => {
    const rows = all ?? [];
    const tier = (t: Recommendation) => rows.filter((r) => r.evaluation?.recommendation === t).sort(byScore);
    // Shortlist tab = AI-shortlist ∪ anyone the human shortlisted (so an
    // AI-reject you override to shortlist is still sendable here).
    const shortlist = rows
      .filter((r) => r.evaluation?.recommendation === "shortlist" || r.candidate.status === "shortlisted")
      .sort(byScore);
    return { shortlist, borderline: tier("borderline"), reject: tier("reject"), all: [...rows].sort(byScore) };
  }, [all]);

  const rows = lists[tab];

  useEffect(() => {
    if (tab !== "shortlist") return;
    setSelected(new Set(lists.shortlist.filter((r) => r.candidate.status === "shortlisted").map((r) => r.candidate.id)));
  }, [tab, lists.shortlist]);

  function toggle(cid: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(cid)) n.delete(cid);
      else n.add(cid);
      return n;
    });
  }
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.candidate.id));
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.candidate.id)));
  }

  async function onBulkSend() {
    setSending(true);
    setBulkResult(null);
    setError(null);
    try {
      const res = await bulkSendAssignments(id, [...selected], force);
      setBulkResult(res);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk send failed.");
    } finally {
      setSending(false);
    }
  }

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
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: connected ? "var(--tier-shortlist)" : "var(--faint)" }}
              />
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
          <Card className="w-64 shrink-0 p-4">
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
        )}
      </div>

      {error && (
        <div
          className="mt-4 rounded-lg px-3 py-2 text-sm"
          style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
        >
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="mt-6 flex items-center gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => {
                setTab(t.key);
                setBulkResult(null);
              }}
              className={`relative -mb-px flex items-center gap-2 whitespace-nowrap px-3.5 py-2.5 text-sm font-medium transition-colors ${
                active ? "text-ink" : "text-muted hover:text-ink"
              }`}
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

      {/* Shortlist bulk bar */}
      {tab === "shortlist" && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
            <div className="text-sm">
              <span className="font-mono font-semibold">{selected.size}</span>
              <span className="text-muted"> selected</span>
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
              <Checkbox checked={force} onChange={setForce} aria-label="Resend already-sent" />
              Resend already-sent
            </label>
            <div className="ml-auto">
              <Button size="sm" loading={sending} disabled={selected.size === 0} onClick={onBulkSend}>
                Send assignment to selected ({selected.size})
              </Button>
            </div>
          </div>
          <p className="mt-1.5 px-1 text-xs text-faint">
            Everyone the AI shortlisted, plus anyone you shortlisted. Defaults to your shortlist — deselect to skip.
          </p>
          {bulkResult && <BulkResultPanel result={bulkResult} onDismiss={() => setBulkResult(null)} />}
        </div>
      )}

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
            {tab === "shortlist" && (
              <div className="flex items-center gap-3 bg-surface-2/50 px-4 py-2 text-xs text-muted">
                <Checkbox checked={allSelected} indeterminate={!allSelected && selected.size > 0} onChange={toggleAll} aria-label="Select all in view" />
                <span>Select all in view</span>
              </div>
            )}
            {rows.map((r) => (
              <Row
                key={r.candidate.id}
                r={r}
                selectable={tab === "shortlist"}
                selected={selected.has(r.candidate.id)}
                onToggle={() => toggle(r.candidate.id)}
                onOpen={() => setOpenId(r.candidate.id)}
              />
            ))}
          </Card>
        )}
      </div>

      <SlideOver open={openId !== null} onClose={() => setOpenId(null)}>
        {openId && <CandidateDetail candidateId={openId} onClose={() => setOpenId(null)} onChanged={() => void refresh()} />}
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

function Row({
  r,
  selectable,
  selected,
  onToggle,
  onOpen,
}: {
  r: CandidateRecord;
  selectable: boolean;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const c = r.candidate;
  const tier = r.evaluation?.recommendation ?? null;
  const dec = DECISION_META[c.status];
  return (
    <div onClick={onOpen} className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2/50">
      {selectable && (
        <div onClick={(e) => e.stopPropagation()}>
          <Checkbox checked={selected} onChange={onToggle} aria-label={`Select ${c.name ?? "candidate"}`} />
        </div>
      )}
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
      {/* the two-axis signal: AI tier word · verdict track · your decision word */}
      <div className="flex shrink-0 items-center gap-2.5">
        <span
          className="hidden w-16 text-right text-xs font-medium md:inline"
          style={{ color: tier ? TIER_META[tier].color : "var(--faint)" }}
        >
          {tier ? TIER_META[tier].label : "Unscored"}
        </span>
        <VerdictTrack tier={tier} status={c.status} />
        <span
          className="w-28 text-xs font-medium"
          style={{ color: dec.kind === "undecided" ? "var(--muted)" : dec.color }}
        >
          {dec.label}
        </span>
      </div>
      <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-faint" fill="none">
        <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}

function BulkResultPanel({ result, onDismiss }: { result: BulkSendResult; onDismiss: () => void }) {
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-sm">
          <span>
            <span className="font-mono font-semibold" style={{ color: "var(--tier-shortlist)" }}>{result.sent_count}</span> sent
          </span>
          <span className="text-muted">
            <span className="font-mono font-semibold">{result.skipped_count}</span> skipped
          </span>
          <span style={{ color: result.failed_count ? "var(--tier-reject)" : undefined }}>
            <span className="font-mono font-semibold">{result.failed_count}</span> failed
          </span>
          <span className="font-mono text-faint">· {result.requested_count} requested</span>
        </div>
        <button onClick={onDismiss} className="text-xs text-muted hover:text-ink">
          Dismiss
        </button>
      </div>
      {result.failed_count > 0 && (
        <div className="mt-3 rounded-lg p-2.5 text-xs" style={{ background: "var(--tier-reject-tint)", color: "var(--tier-reject)" }}>
          <div className="mb-1 font-medium">Failed — needs attention</div>
          <ul className="space-y-0.5">
            {result.failed.map((o) => (
              <li key={o.candidate_id} className="font-mono">{o.candidate_id.slice(0, 8)} — {o.detail ?? o.status}</li>
            ))}
          </ul>
        </div>
      )}
      {result.skipped_count > 0 && (
        <p className="mt-2 text-xs text-muted">Skipped is expected — not shortlisted, already sent, or not in this job.</p>
      )}
    </div>
  );
}
