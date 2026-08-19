"use client";

import { useCallback, useEffect, useState } from "react";
import {
  decideCandidate,
  getCandidate,
  mediaUrl,
  sendAssignment,
  type CandidateDetail as Detail,
  type Decision,
} from "@/lib/api";
import { DecisionChip, TierChip, VerdictTrack } from "@/components/verdict";
import { Button, Label, Spinner, TextArea } from "@/components/ui";
import { formatDate, formatDateTime, initials } from "@/lib/format";

export function CandidateDetail({
  candidateId,
  onClose,
  onChanged,
}: {
  candidateId: string;
  onClose?: () => void;
  onChanged?: (detail: Detail) => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pending, setPending] = useState<Decision | null>(null);
  const [note, setNote] = useState("");
  const [savingDecision, setSavingDecision] = useState(false);

  const [assignConfirm, setAssignConfirm] = useState(false);
  const [assignForce, setAssignForce] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await getCandidate(candidateId));
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
    onChanged?.(updated);
  }

  async function confirmDecision() {
    if (!pending) return;
    setSavingDecision(true);
    setError(null);
    try {
      apply(await decideCandidate(candidateId, pending, note.trim() || null));
      setPending(null);
      setNote("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your decision. Try again.");
    } finally {
      setSavingDecision(false);
    }
  }

  async function confirmSend() {
    setAssignBusy(true);
    setAssignError(null);
    try {
      apply(await sendAssignment(candidateId, assignForce));
      setAssignConfirm(false);
      setAssignForce(false);
    } catch (e) {
      setAssignError(e instanceof Error ? e.message : "Couldn't send the assignment. Try again.");
    } finally {
      setAssignBusy(false);
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
          {detail?.job_title && (
            <div className="mt-0.5 text-xs text-faint">{detail.job_title}</div>
          )}
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
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <Label>Overall score</Label>
                <div className="mt-1 font-mono text-4xl font-semibold tracking-tight tabular-nums">
                  {detail.evaluation.overall_score.toFixed(1)}
                  <span className="ml-1 text-base font-normal text-faint">/100</span>
                </div>
                <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
                  {detail.evaluation.summary}
                </p>
                <p className="mt-1.5 font-mono text-xs text-faint">
                  {detail.evaluation.evaluated_by}
                </p>
              </div>
            </div>
          )}

          <DecisionGate
            detail={detail}
            pending={pending}
            note={note}
            saving={savingDecision}
            onOpen={(d) => {
              setPending(d);
              setNote(detail.candidate.reviewer_note ?? "");
            }}
            onNote={setNote}
            onConfirm={confirmDecision}
            onCancel={() => {
              setPending(null);
              setNote("");
            }}
          />

          {(detail.candidate.status === "shortlisted" ||
            detail.candidate.status === "assignment_sent") && (
            <div className="mt-4 rounded-xl border border-line bg-surface p-4">
              <div className="flex items-center justify-between">
                <Label>Assignment · one-off</Label>
                {detail.candidate.status === "assignment_sent" && (
                  <span className="font-mono text-xs text-faint">
                    sent{" "}
                    {detail.candidate.assignment_sent_count > 1
                      ? `${detail.candidate.assignment_sent_count}×`
                      : ""}{" "}
                    · due {detail.candidate.assignment_deadline}
                  </span>
                )}
              </div>
              <p className="mt-1 mb-3 text-xs text-muted">
                Send in a batch from the pipeline. Use this only for a single resend — a bounced email, say.
              </p>
              {assignError && <Banner>{assignError}</Banner>}
              {!assignConfirm ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setAssignForce(detail.candidate.status === "assignment_sent");
                    setAssignConfirm(true);
                    setAssignError(null);
                  }}
                >
                  {detail.candidate.status === "assignment_sent" ? "Resend assignment" : "Send assignment"}
                </Button>
              ) : (
                <div className="flex items-center gap-2">
                  <Button size="sm" loading={assignBusy} onClick={confirmSend}>
                    Confirm {assignForce ? "resend" : "send"}
                  </Button>
                  <Button variant="ghost" size="sm" disabled={assignBusy} onClick={() => setAssignConfirm(false)}>
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          )}

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
                      <div
                        className="h-1 rounded-full"
                        style={{ width: `${Math.max(0, Math.min(100, c.score))}%`, background: "var(--accent)" }}
                      />
                    </div>
                    {c.evidence && (
                      <p className="mt-2 text-[13px] leading-relaxed text-muted">{c.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-6">
            <div className="flex items-center justify-between">
              <Label>CV pages</Label>
              {detail.cv_url && (
                <a
                  href={mediaUrl(detail.cv_url)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-[var(--accent-ink)] hover:underline"
                >
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
                  <img
                    key={url}
                    src={mediaUrl(url)}
                    alt={`Page ${i + 1}`}
                    className="w-full rounded-xl border border-line"
                  />
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

function DecisionGate({
  detail,
  pending,
  note,
  saving,
  onOpen,
  onNote,
  onConfirm,
  onCancel,
}: {
  detail: Detail;
  pending: Decision | null;
  note: string;
  saving: boolean;
  onOpen: (d: Decision) => void;
  onNote: (v: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const decided = detail.candidate.decided_at !== null;
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <Label>{decided ? "Your decision" : "Decide"}</Label>
        {decided && detail.candidate.decided_at && (
          <span className="font-mono text-xs text-faint">
            {formatDateTime(detail.candidate.decided_at)}
          </span>
        )}
      </div>

      {decided && detail.candidate.reviewer_note && (
        <p className="mt-2 text-sm text-muted">“{detail.candidate.reviewer_note}”</p>
      )}

      {pending === null ? (
        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            variant={detail.candidate.status === "shortlisted" ? "primary" : "secondary"}
            onClick={() => onOpen("shortlist")}
          >
            Shortlist
          </Button>
          <Button size="sm" variant="danger" onClick={() => onOpen("reject")}>
            Reject
          </Button>
          {detail.candidate.status === "assignment_sent" && (
            <span className="ml-auto self-center font-mono text-xs text-faint">
              due {formatDate(detail.candidate.assignment_deadline)}
            </span>
          )}
        </div>
      ) : (
        <div className="mt-3">
          <p className="mb-2 text-sm text-muted">
            {pending === "shortlist" ? "Shortlist" : "Reject"}{" "}
            {detail.candidate.name ?? "this candidate"}?
          </p>
          <TextArea value={note} onChange={(e) => onNote(e.target.value)} rows={2} placeholder="Add a note (optional)" />
          <div className="mt-2 flex gap-2">
            <Button size="sm" loading={saving} onClick={onConfirm}>
              Confirm {pending}
            </Button>
            <Button variant="ghost" size="sm" disabled={saving} onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
