"use client";

import { useState } from "react";
import { addCandidate } from "@/lib/api";
import { Button, Label } from "@/components/ui";

const inputCls =
  "mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-[var(--accent)]";

/** Manually add one candidate to a job by uploading their CV. */
export function AddCandidate({
  jobId,
  onClose,
  onAdded,
}: {
  jobId: string;
  onClose: () => void;
  onAdded: (candidateId: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [portfolio, setPortfolio] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!file) {
      setError("Choose a CV PDF to upload.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await addCandidate(jobId, file, {
        name: name.trim() || undefined,
        email: email.trim() || undefined,
        portfolio_url: portfolio.trim() || undefined,
      });
      onAdded(detail.candidate.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add the candidate. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6">
      <h2 className="font-display text-lg font-medium">Add candidate</h2>
      <p className="mt-1 text-sm text-muted">
        Upload a CV (PDF). It&apos;s scored against this job&apos;s rubric, just like a pulled applicant.
      </p>

      {error && (
        <div
          className="mt-3 rounded-lg px-3 py-2 text-sm"
          style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
        >
          {error}
        </div>
      )}

      <div className="mt-4 space-y-3">
        <div>
          <Label>CV (PDF)</Label>
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm text-muted file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-sm"
          />
        </div>
        <div>
          <Label>Name (optional)</Label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" className={inputCls} />
        </div>
        <div>
          <Label>Email (optional)</Label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@example.com" className={inputCls} />
        </div>
        <div>
          <Label>Portfolio link (optional)</Label>
          <input value={portfolio} onChange={(e) => setPortfolio(e.target.value)} placeholder="https://…" className={inputCls} />
        </div>
      </div>

      <div className="mt-5 flex gap-2">
        <Button loading={busy} onClick={() => void submit()}>
          Add &amp; score
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
      </div>
      {busy && <p className="mt-2 text-xs text-muted">Scoring the CV — this takes a few seconds.</p>}
    </div>
  );
}
