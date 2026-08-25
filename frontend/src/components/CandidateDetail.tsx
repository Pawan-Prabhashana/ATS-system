"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DEMO_MODE,
  decideCandidate,
  getCandidate,
  getJob,
  mediaUrl,
  sendAssignment,
  type CandidateDetail as Detail,
  type Decision,
  type Job,
} from "@/lib/api";
import { DecisionChip, TierChip, VerdictTrack } from "@/components/verdict";
import { Button, Label, Spinner, TextArea } from "@/components/ui";
import { formatDate, formatDateTime, initials } from "@/lib/format";

export function CandidateDetail({
  candidateId,
  onClose,
  onChanged,
  onOpenSend,
}: {
  candidateId: string;
  onClose?: () => void;
  onChanged?: (detail: Detail) => void;
  // Called instead of a single send when the job has no assignment brief yet,
  // so the reviewer lands in the send surface to upload one.
  onOpenSend?: () => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // A pending decision awaiting a note + confirm (from undecided, or via change).
  const [pending, setPending] = useState<Decision | null>(null);
  const [note, setNote] = useState("");
  const [changing, setChanging] = useState(false); // "Change decision" expanded
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await getCandidate(candidateId);
      setDetail(d);
      if (d.job_id) {
        // Load the job so we know whether an assignment brief exists.
        getJob(d.job_id).then(setJob).catch(() => setJob(null));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load this candidate. Try again.");
    } finally {
      setLoading(false);
    }
  }, [candidateId]);

  useEffect(() => {
    void load();
  }, [load]);

  function apply(updated: Detail) {
    setDetail(updated);
    setPending(null);
    setChanging(false);
    setNote("");
    onChanged?.(updated);
  }

  async function confirmDecide() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      apply(await decideCandidate(candidateId, pending, note.trim() || null));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your decision. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    setBusy(true);
    setError(null);
    try {
      apply(await decideCandidate(candidateId, "undecided"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't clear the decision. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function send(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      apply(await sendAssignment(candidateId, force));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the assignment. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function openDecide(d: Decision) {
    setPending(d);
    setNote(detail?.candidate.reviewer_note ?? "");
  }

  const hasBrief = Boolean(job?.assignment_brief_filename);

  // Single send needs the job's brief. Without one, open the send surface (where
  // it can be uploaded) rather than firing a request that 409s.
  function requestSend(force: boolean) {
    if (hasBrief) {
      void send(force);
    } else if (onOpenSend) {
      onOpenSend();
    } else {
      setError("Upload an assignment brief in Send assignments before sending.");
    }
  }

  const tier = detail?.evaluation?.recommendation ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-start gap-3 border-b border-line px-6 py-4">
        {detail && (
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-sm font-medium text-muted">
            {initials(detail.candidate.name)}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate font-display text-lg font-medium tracking-tight">
            {detail?.candidate.name ?? (loading ? "Loading…" : "Candidate")}
          </div>
          <div className="truncate text-sm text-muted">{detail?.candidate.email ?? " "}</div>
          {detail?.job_title && <div className="mt-0.5 text-xs text-faint">{detail.job_title}</div>}
        </div>
        {detail && (
          <div className="flex flex-col items-end gap-2">
            <VerdictTrack tier={tier} status={detail.candidate.status} size="md" />
            <div className="flex items-center gap-1.5">
              {tier && <TierChip tier={tier} />}
              <DecisionChip status={detail.candidate.status} />
            </div>
          </div>
        )}
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close"
            className="ml-1 grid h-8 w-8 place-items-center rounded-lg text-faint hover:bg-surface-2 hover:text-ink"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center text-muted">
          <Spinner />
        </div>
      ) : !detail ? (
        <div className="flex flex-1 items-center justify-center px-6 text-center text-[var(--tier-reject)]">
          {error ?? "Not found."}
        </div>
      ) : (
        <div className="thin-scroll flex-1 overflow-y-auto px-6 py-5">
          {error && <Banner>{error}</Banner>}

          {detail.evaluation && (
            <div className="mb-6">
              <Label>Overall score</Label>
              <div className="mt-1 font-mono text-4xl font-semibold tracking-tight tabular-nums">
                {detail.evaluation.overall_score.toFixed(1)}
                <span className="ml-1 text-base font-normal text-faint">/100</span>
              </div>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">{detail.evaluation.summary}</p>
              <p className="mt-1.5 font-mono text-xs text-faint">{detail.evaluation.evaluated_by}</p>
            </div>
          )}

          {/* Review panel — one state, not a permanent question */}
          <div className="rounded-xl border border-line bg-surface p-4">
            {pending !== null ? (
              <NoteConfirm
                decision={pending}
                name={detail.candidate.name}
                note={note}
                busy={busy}
                onNote={setNote}
                onConfirm={confirmDecide}
                onCancel={() => setPending(null)}
              />
            ) : (
              <ReviewState
                detail={detail}
                busy={busy}
                changing={changing}
                hasBrief={hasBrief}
                onShortlist={() => openDecide("shortlist")}
                onReject={() => openDecide("reject")}
                onUndo={undo}
                onSend={() => requestSend(false)}
                onResend={() => requestSend(true)}
                onToggleChange={() => setChanging((v) => !v)}
              />
            )}
          </div>

          {detail.evaluation && detail.evaluation.criterion_scores.length > 0 && (
            <div className="mt-6">
              <Label>Criteria</Label>
              <div className="mt-2 space-y-2.5">
                {detail.evaluation.criterion_scores.map((c) => (
                  <div key={c.criterion_name} className="rounded-xl border border-line bg-surface p-3.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <div className="text-sm font-medium">{c.criterion_name}</div>
                      <div className="shrink-0 font-mono text-sm tabular-nums">
                        <span className="font-semibold">{c.score.toFixed(0)}</span>
                        <span className="text-faint"> · w{c.weight}</span>
                      </div>
                    </div>
                    <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-surface-2">
                      <div className="h-1 rounded-full" style={{ width: `${Math.max(0, Math.min(100, c.score))}%`, background: "var(--accent)" }} />
                    </div>
                    {c.evidence && <p className="mt-2 text-[13px] leading-relaxed text-muted">{c.evidence}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-6">
            <div className="flex items-center justify-between">
              <Label>CV pages</Label>
              {detail.cv_url && (
                <a href={mediaUrl(detail.cv_url)} target="_blank" rel="noreferrer" className="text-xs text-[var(--accent-ink)] hover:underline">
                  Open PDF ↗
                </a>
              )}
            </div>
            {detail.text_extraction_quality === "low" && (
              <p className="mt-1 text-xs" style={{ color: "var(--tier-borderline)" }}>
                Little text extracted — likely a scanned CV; judged mainly from the images.
              </p>
            )}
            <div className="mt-2 space-y-3">
              {detail.page_image_urls.length === 0 ? (
                <p className="text-sm text-faint">No page images.</p>
              ) : (
                detail.page_image_urls.map((url, i) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={url} src={mediaUrl(url)} alt={`Page ${i + 1}`} className="w-full rounded-xl border border-line" />
                ))
              )}
            </div>
          </div>
          <div className="h-4" />
        </div>
      )}
    </div>
  );
}

function ReviewState({
  detail,
  busy,
  changing,
  hasBrief,
  onShortlist,
  onReject,
  onUndo,
  onSend,
  onResend,
  onToggleChange,
}: {
  detail: Detail;
  busy: boolean;
  changing: boolean;
  hasBrief: boolean;
  onShortlist: () => void;
  onReject: () => void;
  onUndo: () => void;
  onSend: () => void;
  onResend: () => void;
  onToggleChange: () => void;
}) {
  const c = detail.candidate;

  if (c.status === "scored" || c.status === "parsed") {
    return (
      <>
        <Label>Decide</Label>
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={onShortlist}>Shortlist</Button>
          <Button size="sm" variant="danger" onClick={onReject}>Reject</Button>
        </div>
      </>
    );
  }

  if (c.status === "shortlisted") {
    return (
      <>
        <Confirmed color="var(--tier-shortlist)" label="Shortlisted" at={c.decided_at} note={c.reviewer_note} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" loading={busy} onClick={onSend}>
            {hasBrief ? "Send assignment" : "Set up assignment"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onToggleChange}>Change decision</Button>
        </div>
        {!hasBrief && (
          <p className="mt-2 text-xs" style={{ color: "var(--tier-borderline)" }}>
            No assignment brief yet — you&apos;ll upload one in Send assignments.
          </p>
        )}
        {changing && (
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="danger" onClick={onReject}>Reject instead</Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={onUndo}>Set to undecided</Button>
          </div>
        )}
      </>
    );
  }

  if (c.status === "assignment_sent") {
    return (
      <>
        <Confirmed
          color="var(--dec-sent)"
          label={`Assignment sent${c.assignment_sent_count > 1 ? ` · ${c.assignment_sent_count}×` : ""}`}
          at={c.assignment_sent_at}
          note={null}
        />
        <p className="mt-1 text-xs text-muted">Due {formatDate(c.assignment_deadline)}.</p>
        {DEMO_MODE && (
          <p className="mt-1 text-xs" style={{ color: "var(--accent-ink)" }}>
            Demo build — the email is simulated, not actually sent.
          </p>
        )}
        <div className="mt-3">
          <Button size="sm" variant="ghost" loading={busy} onClick={onResend}>Resend</Button>
        </div>
      </>
    );
  }

  // rejected
  return (
    <>
      <Confirmed color="var(--tier-reject)" label="Rejected" at={c.decided_at} note={c.reviewer_note} />
      <div className="mt-3">
        <Button size="sm" variant="ghost" onClick={onToggleChange}>Change decision</Button>
      </div>
      {changing && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={onShortlist}>Shortlist instead</Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={onUndo}>Set to undecided</Button>
        </div>
      )}
    </>
  );
}

function Confirmed({
  color,
  label,
  at,
  note,
}: {
  color: string;
  label: string;
  at: string | null;
  note: string | null;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-2 text-sm font-medium" style={{ color }}>
          <span
            className="inline-grid h-4 w-4 place-items-center rounded-full"
            style={{ background: color }}
          >
            <svg viewBox="0 0 16 16" className="h-2.5 w-2.5" fill="none">
              <path d="M4 8.4l2.6 2.6L12 5.4" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          {label}
        </span>
        {at && <span className="font-mono text-xs text-faint">{formatDateTime(at)}</span>}
      </div>
      {note && <p className="mt-1.5 text-sm text-muted">“{note}”</p>}
    </div>
  );
}

function NoteConfirm({
  decision,
  name,
  note,
  busy,
  onNote,
  onConfirm,
  onCancel,
}: {
  decision: Decision;
  name: string | null;
  note: string;
  busy: boolean;
  onNote: (v: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div>
      <p className="mb-2 text-sm text-muted">
        {decision === "shortlist" ? "Shortlist" : "Reject"} {name ?? "this candidate"}?
      </p>
      <TextArea value={note} onChange={(e) => onNote(e.target.value)} rows={2} placeholder="Add a note (optional)" />
      <div className="mt-2 flex gap-2">
        <Button size="sm" loading={busy} onClick={onConfirm}>Confirm {decision}</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function Banner({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="mb-4 rounded-lg border px-3 py-2 text-sm"
      style={{
        color: "var(--tier-reject)",
        borderColor: "color-mix(in srgb, var(--tier-reject) 35%, transparent)",
        background: "var(--tier-reject-tint)",
      }}
    >
      {children}
    </div>
  );
}
