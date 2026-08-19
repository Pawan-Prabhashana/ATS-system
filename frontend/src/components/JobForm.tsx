"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  closeJob,
  createJob,
  testIntake,
  updateJob,
  type IntakeProbeResult,
  type Job,
} from "@/lib/api";
import { Button, Card, Field, Label, TextArea, TextInput } from "@/components/ui";

interface Row {
  name: string;
  description: string;
  weight: number;
}

const BLANK: Row = { name: "", description: "", weight: 1 };

export function JobForm({ initial, jobId }: { initial?: Job; jobId?: string }) {
  const router = useRouter();
  const isEdit = Boolean(jobId);

  const [title, setTitle] = useState(initial?.title ?? "");
  const [jd, setJd] = useState(initial?.job_description ?? "");
  const [rows, setRows] = useState<Row[]>(
    initial?.rubric.criteria.map((c) => ({ ...c })) ?? [{ ...BLANK }],
  );
  const [vision, setVision] = useState(initial?.rubric.requires_visual_review ?? false);
  const [sheetId, setSheetId] = useState(initial?.google_sheet_id ?? "");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [probe, setProbe] = useState<IntakeProbeResult | null>(null);
  const [testing, setTesting] = useState(false);

  const totalWeight = rows.reduce((s, r) => s + (r.weight > 0 ? r.weight : 0), 0) || 1;

  function setRow(i: number, patch: Partial<Row>) {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }
  function addRow() {
    setRows((rs) => [...rs, { ...BLANK }]);
  }
  function removeRow(i: number) {
    setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : rs));
  }

  async function onSave() {
    const criteria = rows
      .map((r) => ({ ...r, name: r.name.trim() }))
      .filter((r) => r.name);
    if (!title.trim()) return setError("Give the role a title.");
    if (criteria.length === 0) return setError("Add at least one criterion to score against.");
    if (criteria.some((r) => !(r.weight > 0))) return setError("Every criterion needs a weight above zero.");

    setSaving(true);
    setError(null);
    const payload = {
      title: title.trim(),
      job_description: jd,
      rubric: { job_title: title.trim(), criteria, requires_visual_review: vision },
      google_sheet_id: sheetId.trim() || null,
    };
    try {
      const job = isEdit ? await updateJob(jobId!, payload) : await createJob(payload);
      router.push(`/jobs/${job.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the job. Try again.");
      setSaving(false);
    }
  }

  async function onTest() {
    if (!isEdit) return;
    setTesting(true);
    setProbe(null);
    try {
      setProbe(await testIntake(jobId!, sheetId));
    } catch (e) {
      setProbe({
        connected: false,
        row_count: 0,
        detected_columns: {},
        error: e instanceof Error ? e.message : "Test failed.",
      });
    } finally {
      setTesting(false);
    }
  }

  async function onClose() {
    if (!isEdit) return;
    setSaving(true);
    try {
      const job = await closeJob(jobId!);
      router.push(`/jobs/${job.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't close the job.");
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      {error && (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
        >
          {error}
        </div>
      )}

      <Card className="space-y-4 p-5">
        <Field label="Role title">
          <TextInput value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Senior backend engineer" />
        </Field>
        <Field label="Job description" hint="What the role is and who you're looking for. The evaluator reads this.">
          <TextArea value={jd} onChange={(e) => setJd(e.target.value)} rows={6} placeholder="Describe the role, responsibilities, and must-haves." />
        </Field>
      </Card>

      {/* Criteria */}
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-display text-sm font-medium">What you're looking for</h2>
            <p className="mt-0.5 text-xs text-muted">
              Each criterion is scored 0–100; weights set how much it counts.
            </p>
          </div>
        </div>
        <div className="mt-4 space-y-2.5">
          <div className="hidden grid-cols-[1fr_1fr_auto_auto_auto] items-center gap-2 px-1 sm:grid">
            <Label>Criterion</Label>
            <Label>Description</Label>
            <Label>Weight</Label>
            <Label>Share</Label>
            <span />
          </div>
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[1fr_1fr_auto_auto_auto]">
              <TextInput value={r.name} onChange={(e) => setRow(i, { name: e.target.value })} placeholder="Python & backend depth" />
              <TextInput value={r.description} onChange={(e) => setRow(i, { description: e.target.value })} placeholder="Optional — what good looks like" />
              <TextInput
                type="number"
                min={0.1}
                step={0.1}
                value={r.weight}
                onChange={(e) => setRow(i, { weight: parseFloat(e.target.value) || 0 })}
                className="w-full sm:w-20"
                aria-label={`Weight for criterion ${i + 1}`}
              />
              <span className="px-1 font-mono text-xs tabular-nums text-muted sm:w-12 sm:text-right">
                {r.weight > 0 ? `${Math.round((r.weight / totalWeight) * 100)}%` : "—"}
              </span>
              <button
                type="button"
                onClick={() => removeRow(i)}
                aria-label={`Remove criterion ${i + 1}`}
                className="grid h-8 w-8 place-items-center justify-self-end rounded-lg text-faint hover:bg-surface-2 hover:text-[var(--tier-reject)] disabled:opacity-30"
                disabled={rows.length <= 1}
              >
                <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
                  <path d="M3.5 4.5h9M6 4.5V3.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1M5 4.5l.5 8h5l.5-8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <Button variant="secondary" size="sm" onClick={addRow}>
            + Add criterion
          </Button>
          <span className="font-mono text-xs text-faint">total weight {totalWeight}</span>
        </div>
      </Card>

      {/* Vision toggle */}
      <Card className="p-5">
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={vision}
            onChange={(e) => setVision(e.target.checked)}
            className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
          />
          <span>
            <span className="text-sm font-medium">Also score the CV's visual design</span>
            <span className="mt-0.5 block text-xs text-muted">
              On for design and brand roles, off otherwise. Off is cheaper and faster — it skips sending the page images to the model.
            </span>
          </span>
        </label>
      </Card>

      {/* Google Form connection */}
      <Card className="p-5">
        <h2 className="font-display text-sm font-medium">Where applications come from</h2>
        <p className="mt-0.5 text-xs text-muted">
          Connect this role to its Google Form by pasting the responses Sheet ID. Leave it blank to use the local sample applicants.
        </p>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Field
              label="Responses Sheet ID"
              hint={
                <>
                  From the Sheet URL:{" "}
                  <code className="font-mono">docs.google.com/spreadsheets/d/</code>
                  <strong>&lt;this&gt;</strong>
                  <code className="font-mono">/edit</code>
                </>
              }
            >
              <TextInput value={sheetId} onChange={(e) => setSheetId(e.target.value)} placeholder="1Abc…xyz" />
            </Field>
          </div>
          <Button
            variant="secondary"
            onClick={onTest}
            loading={testing}
            disabled={!isEdit}
            className="shrink-0"
          >
            Test connection
          </Button>
        </div>
        {!isEdit && (
          <p className="mt-2 text-xs text-faint">Save the role first, then test the connection from its settings.</p>
        )}
        {probe && <ProbeResult probe={probe} />}
      </Card>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button onClick={onSave} loading={saving}>
          {isEdit ? "Save changes" : "Create job"}
        </Button>
        <Button variant="ghost" onClick={() => router.back()} disabled={saving}>
          Cancel
        </Button>
        {isEdit && initial?.status === "open" && (
          <Button variant="danger" onClick={onClose} disabled={saving} className="ml-auto">
            Close job
          </Button>
        )}
      </div>
    </div>
  );
}

function ProbeResult({ probe }: { probe: IntakeProbeResult }) {
  const ok = probe.connected;
  const color = ok ? "var(--tier-shortlist)" : "var(--tier-reject)";
  const tint = ok ? "var(--tier-shortlist-tint)" : "var(--tier-reject-tint)";
  return (
    <div className="mt-3 rounded-lg px-3 py-2 text-sm" style={{ background: tint, color }}>
      {ok ? (
        <>
          <span className="font-medium">Connected.</span>{" "}
          <span className="font-mono">{probe.row_count}</span> response
          {probe.row_count === 1 ? "" : "s"} found
          {Object.values(probe.detected_columns).some(Boolean) && (
            <span className="text-muted">
              {" "}
              · columns:{" "}
              {Object.entries(probe.detected_columns)
                .filter(([, v]) => v)
                .map(([k]) => k)
                .join(", ")}
            </span>
          )}
        </>
      ) : (
        <>
          <span className="font-medium">Not connected.</span> {probe.error}
        </>
      )}
    </div>
  );
}
