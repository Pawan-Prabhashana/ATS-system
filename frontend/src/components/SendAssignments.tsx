"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEMO_MODE,
  bulkSendAssignments,
  deleteBrief,
  getJob,
  listJobCandidates,
  openAuthedFile,
  sendAssignment,
  updateJob,
  uploadBrief,
  type BulkSendResult,
  type CandidateRecord,
  type Job,
} from "@/lib/api";
import { VerdictTrack } from "@/components/verdict";
import { Button, Checkbox, Label, Spinner, TextInput } from "@/components/ui";
import { formatDate, initials } from "@/lib/format";

export function SendAssignments({
  jobId,
  onClose,
  onChanged,
}: {
  jobId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [ready, setReady] = useState<CandidateRecord[]>([]);
  const [sent, setSent] = useState<CandidateRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<BulkSendResult | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [deadline, setDeadline] = useState<string>("");
  const [resendingId, setResendingId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [j, r, s] = await Promise.all([
        getJob(jobId),
        listJobCandidates(jobId, { status: "shortlisted" }),
        listJobCandidates(jobId, { status: "assignment_sent" }),
      ]);
      setJob(j);
      setReady(r);
      setSent(s);
      setSelected(new Set(r.map((x) => x.candidate.id)));
      setDeadline(j.assignment_deadline_days != null ? String(j.assignment_deadline_days) : "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the send surface.");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void load();
  }, [load]);

  function refreshAll() {
    void load();
    onChanged();
  }

  const hasBrief = Boolean(job?.assignment_brief_filename);

  function toggle(cid: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(cid)) n.delete(cid);
      else n.add(cid);
      return n;
    });
  }
  const allSelected = ready.length > 0 && ready.every((r) => selected.has(r.candidate.id));

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBriefBusy(true);
    setError(null);
    try {
      const updated = await uploadBrief(jobId, file);
      setJob(updated);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't upload the brief.");
    } finally {
      setBriefBusy(false);
    }
  }

  async function onRemoveBrief() {
    setBriefBusy(true);
    try {
      setJob(await deleteBrief(jobId));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove the brief.");
    } finally {
      setBriefBusy(false);
    }
  }

  async function onSaveDeadline() {
    const n = deadline.trim() === "" ? null : parseInt(deadline, 10);
    if (n !== null && (Number.isNaN(n) || n < 1)) {
      setError("Deadline must be a whole number of days.");
      return;
    }
    setBriefBusy(true);
    try {
      setJob(await updateJob(jobId, { assignment_deadline_days: n }));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the deadline.");
    } finally {
      setBriefBusy(false);
    }
  }

  async function onSend() {
    setSending(true);
    setResult(null);
    setError(null);
    try {
      const res = await bulkSendAssignments(jobId, [...selected], false);
      setResult(res);
      refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed.");
    } finally {
      setSending(false);
    }
  }

  async function onResend(cid: string) {
    setResendingId(cid);
    setError(null);
    try {
      await sendAssignment(cid, true);
      refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resend failed.");
    } finally {
      setResendingId(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <h2 className="font-display text-lg font-medium tracking-tight">Send assignments</h2>
          <p className="text-sm text-muted">{job?.title ?? " "}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="grid h-8 w-8 place-items-center rounded-lg text-faint hover:bg-surface-2 hover:text-ink"
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center text-muted">
          <Spinner />
        </div>
      ) : (
        <div className="thin-scroll flex-1 overflow-y-auto px-6 py-5">
          {error && (
            <div
              className="mb-4 rounded-lg px-3 py-2 text-sm"
              style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
            >
              {error}
            </div>
          )}

          {/* Brief */}
          <input ref={fileRef} type="file" accept="application/pdf" onChange={onPickFile} className="hidden" />
          <div className="rounded-xl border border-line bg-surface p-4">
            <Label>Assignment brief</Label>
            {hasBrief ? (
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <span className="inline-flex items-center gap-2 text-sm">
                  <span aria-hidden style={{ color: "var(--tier-shortlist)" }}>●</span>
                  {job?.assignment_brief_filename}
                </span>
                <button
                  type="button"
                  onClick={() => void openAuthedFile(`/jobs/${encodeURIComponent(jobId)}/assignment-brief`)}
                  className="text-xs text-[var(--accent-ink)] hover:underline"
                >
                  Preview ↗
                </button>
                <div className="ml-auto flex gap-2">
                  <Button size="sm" variant="secondary" loading={briefBusy} onClick={() => fileRef.current?.click()}>
                    Replace
                  </Button>
                  <Button size="sm" variant="ghost" disabled={briefBusy} onClick={onRemoveBrief}>
                    Remove
                  </Button>
                </div>
              </div>
            ) : (
              <div className="mt-2">
                <p className="mb-2 text-sm text-muted">
                  Upload the PDF candidates will receive. Sending is blocked until you do.
                </p>
                <Button size="sm" loading={briefBusy} onClick={() => fileRef.current?.click()}>
                  Upload brief (PDF)
                </Button>
              </div>
            )}
            <div className="mt-4 flex items-end gap-2">
              <label className="block">
                <span className="mb-1 block text-xs text-muted">Deadline (days from send)</span>
                <TextInput
                  type="number"
                  min={1}
                  value={deadline}
                  onChange={(e) => setDeadline(e.target.value)}
                  placeholder="5"
                  className="w-28"
                />
              </label>
              <Button size="sm" variant="secondary" disabled={briefBusy} onClick={onSaveDeadline}>
                Save
              </Button>
            </div>
          </div>

          {/* Ready to send */}
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-display text-sm font-medium">Ready to send ({ready.length})</h3>
              {ready.length > 0 && (
                <button
                  onClick={() => setSelected(allSelected ? new Set() : new Set(ready.map((r) => r.candidate.id)))}
                  className="text-xs text-muted hover:text-ink"
                >
                  {allSelected ? "Deselect all" : "Select all"}
                </button>
              )}
            </div>
            {ready.length === 0 ? (
              <p className="rounded-lg border border-line bg-surface px-3 py-4 text-sm text-muted">
                No one is shortlisted yet. Shortlist candidates from the pipeline to send them an assignment.
              </p>
            ) : (
              <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
                {ready.map((r) => (
                  <label key={r.candidate.id} className="flex cursor-pointer items-center gap-3 px-3 py-2.5">
                    <Checkbox
                      checked={selected.has(r.candidate.id)}
                      onChange={() => toggle(r.candidate.id)}
                      aria-label={`Select ${r.candidate.name ?? "candidate"}`}
                    />
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-[11px] font-medium text-muted">
                      {initials(r.candidate.name)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.candidate.name ?? "Unknown"}</div>
                      <div className="truncate text-xs text-muted">{r.candidate.email ?? "—"}</div>
                    </div>
                    <VerdictTrack tier={r.evaluation?.recommendation ?? null} status={r.candidate.status} />
                  </label>
                ))}
              </div>
            )}

            <div className="mt-3 flex items-center gap-3">
              <Button loading={sending} disabled={!hasBrief || selected.size === 0} onClick={onSend}>
                Send to selected ({selected.size})
              </Button>
              {!hasBrief && <span className="text-xs" style={{ color: "var(--tier-borderline)" }}>Upload a brief first.</span>}
            </div>

            {result && <ResultSummary result={result} />}
          </div>

          {/* Already sent */}
          {sent.length > 0 && (
            <div className="mt-6">
              <h3 className="mb-2 font-display text-sm font-medium">Already sent ({sent.length})</h3>
              <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
                {sent.map((r) => (
                  <div key={r.candidate.id} className="flex items-center gap-3 px-3 py-2.5">
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-[11px] font-medium text-muted">
                      {initials(r.candidate.name)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.candidate.name ?? "Unknown"}</div>
                      <div className="truncate text-xs text-muted">
                        sent {formatDate(r.candidate.assignment_sent_at)} · due {r.candidate.assignment_deadline}
                        {r.candidate.assignment_sent_count > 1 ? ` · ${r.candidate.assignment_sent_count}×` : ""}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={resendingId === r.candidate.id}
                      disabled={!hasBrief}
                      onClick={() => onResend(r.candidate.id)}
                    >
                      Resend
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="h-4" />
        </div>
      )}
    </div>
  );
}

function ResultSummary({ result }: { result: BulkSendResult }) {
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface p-4">
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
      </div>
      {DEMO_MODE && (
        <p className="mt-2 text-xs" style={{ color: "var(--accent-ink)" }}>
          Demo build — emails are simulated, not actually sent.
        </p>
      )}
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
      {result.skipped.some((o) => o.status === "no_assignment_brief") && (
        <p className="mt-2 text-xs" style={{ color: "var(--tier-borderline)" }}>
          Some were skipped because this job has no assignment brief.
        </p>
      )}
      {result.skipped_count > 0 && (
        <p className="mt-1 text-xs text-muted">Skipped is expected — already sent, not shortlisted, or missing a brief.</p>
      )}
    </div>
  );
}
