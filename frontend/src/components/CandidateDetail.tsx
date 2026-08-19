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
import { StatusBadge, TierChip } from "@/components/badges";
import { Button, Label, Spinner } from "@/components/ui";
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
      setError(e instanceof Error ? e.message : "Failed to load candidate.");
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
      setError(e instanceof Error ? e.message : "Failed to record decision.");
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
      setAssignError(e instanceof Error ? e.message : "Failed to send assignment.");
    } finally {
      setAssignBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-start gap-3 border-b border-line px-6 py-4">
        {detail && (
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-surface-2 text-sm font-semibold text-ink-2">
            {initials(detail.candidate.name)}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-lg font-semibold tracking-tight">
            {detail?.candidate.name ?? (loading ? "Loading…" : "Candidate")}
          </div>
          <div className="truncate text-sm text-ink-2">
            {detail?.candidate.email ?? " "}
          </div>
          {detail?.job_title && (
            <div className="mt-0.5 text-xs text-muted">{detail.job_title}</div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5">
          {detail?.evaluation && <TierChip tier={detail.evaluation.recommendation} />}
          {detail && <StatusBadge status={detail.candidate.status} />}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close"
            className="ml-1 grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
              <path
                d="M4 4l8 8M12 4l-8 8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
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
          {error && (
            <div
              className="mb-4 rounded-lg border px-3 py-2 text-sm"
              style={{
                color: "var(--tier-reject)",
                borderColor: "color-mix(in srgb, var(--tier-reject) 35%, transparent)",
                background: "var(--tier-reject-tint)",
              }}
            >
              {error}
            </div>
          )}

          {/* Score */}
          {detail.evaluation && (
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <Label>Overall score</Label>
                <div className="mt-1 font-mono text-4xl font-semibold tabular-nums tracking-tight">
                  {detail.evaluation.overall_score.toFixed(1)}
                  <span className="ml-1 text-base font-normal text-muted">/100</span>
                </div>
                <p className="mt-2 max-w-md text-sm leading-relaxed text-ink-2">
                  {detail.evaluation.summary}
                </p>
                <p className="mt-1.5 text-xs text-muted">
                  Evaluated by {detail.evaluation.evaluated_by}
                </p>
              </div>
              <TierChip tier={detail.evaluation.recommendation} size="md" />
            </div>
          )}

          {/* Decision gate */}
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

          {/* Single-candidate send (secondary to bulk send). */}
          {(detail.candidate.status === "shortlisted" ||
            detail.candidate.status === "assignment_sent") && (
            <div className="mt-4 rounded-lg border border-line bg-surface p-4">
              <div className="flex items-center justify-between">
                <Label>Assignment · one-off</Label>
                {detail.candidate.status === "assignment_sent" && (
                  <span className="text-xs text-muted">
                    sent{" "}
                    {detail.candidate.assignment_sent_count > 1
                      ? `${detail.candidate.assignment_sent_count}×`
                      : ""}{" "}
                    · due {detail.candidate.assignment_deadline}
                  </span>
                )}
              </div>
              <p className="mt-1 mb-3 text-xs text-muted">
                Prefer <span className="text-ink-2">Send to Selected</span> on the
                pipeline for batches. Use this for a single resend (e.g. bounced).
              </p>
              {assignError && (
                <div
                  className="mb-2 rounded-md px-2.5 py-1.5 text-xs"
                  style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
                >
                  {assignError}
                </div>
              )}
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
                  {detail.candidate.status === "assignment_sent"
                    ? "Resend assignment"
                    : "Send assignment"}
                </Button>
              ) : (
                <div className="flex items-center gap-2">
                  <Button size="sm" loading={assignBusy} onClick={confirmSend}>
                    Confirm {assignForce ? "resend" : "send"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={assignBusy}
                    onClick={() => setAssignConfirm(false)}
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Criteria */}
          {detail.evaluation && detail.evaluation.criterion_scores.length > 0 && (
            <div className="mt-6">
              <Label>Criteria</Label>
              <div className="mt-2 space-y-2.5">
                {detail.evaluation.criterion_scores.map((c) => (
                  <div
                    key={c.criterion_name}
                    className="rounded-lg border border-line bg-surface p-3.5"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <div className="text-sm font-medium">{c.criterion_name}</div>
                      <div className="shrink-0 font-mono text-sm tabular-nums">
                        <span className="font-semibold">{c.score.toFixed(0)}</span>
                        <span className="text-muted"> · w{c.weight}</span>
                      </div>
                    </div>
                    <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-surface-2">
                      <div
                        className="h-1 rounded-full bg-ink/70"
                        style={{ width: `${Math.max(0, Math.min(100, c.score))}%` }}
                      />
                    </div>
                    {c.evidence && (
                      <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
                        {c.evidence}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* CV pages */}
          <div className="mt-6">
            <div className="flex items-center justify-between">
              <Label>CV pages</Label>
              {detail.cv_url && (
                <a
                  href={mediaUrl(detail.cv_url)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-link hover:underline"
                >
                  Open PDF ↗
                </a>
              )}
            </div>
            {detail.text_extraction_quality === "low" && (
              <p className="mt-1 text-xs" style={{ color: "var(--tier-borderline)" }}>
                Low text extraction — likely a scanned CV; judged mainly from images.
              </p>
            )}
            <div className="mt-2 space-y-3">
              {detail.page_image_urls.length === 0 ? (
                <p className="text-sm text-muted">No page images.</p>
              ) : (
                detail.page_image_urls.map((url, i) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={url}
                    src={mediaUrl(url)}
                    alt={`Page ${i + 1}`}
                    className="w-full rounded-lg border border-line"
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
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <Label>{decided ? "Decision" : "Your decision"}</Label>
        {decided && detail.candidate.decided_at && (
          <span className="text-xs text-muted">
            {formatDateTime(detail.candidate.decided_at)}
          </span>
        )}
      </div>

      {decided && detail.candidate.reviewer_note && (
        <p className="mt-2 text-sm text-ink-2">“{detail.candidate.reviewer_note}”</p>
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
            <span className="ml-auto self-center text-xs text-muted">
              due {formatDate(detail.candidate.assignment_deadline)}
            </span>
          )}
        </div>
      ) : (
        <div className="mt-3">
          <p className="mb-2 text-sm text-ink-2">
            Confirm <span className="font-semibold text-ink">{pending}</span> for{" "}
            {detail.candidate.name ?? "this candidate"}?
          </p>
          <textarea
            value={note}
            onChange={(e) => onNote(e.target.value)}
            rows={2}
            placeholder="Optional note…"
            className="w-full resize-none rounded-md border border-line-2 bg-bg px-2.5 py-1.5 text-sm text-ink placeholder:text-muted focus:border-ink focus:outline-none"
          />
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
