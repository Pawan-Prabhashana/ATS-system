"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { closeJob, createJob, listRoles, updateJob, type Job } from "@/lib/api";
import { Button, Card, Field, Label, TextArea, TextInput } from "@/components/ui";

interface Row {
  name: string;
  description: string;
  weight: number;
}

const BLANK: Row = { name: "", description: "", weight: 1 };

export function JobForm({
  initial,
  jobId,
  presetRoleKey,
}: {
  initial?: Job;
  jobId?: string;
  /** From "Set up this role": the exact detected dropdown value, locked. */
  presetRoleKey?: string;
}) {
  const router = useRouter();
  const isEdit = Boolean(jobId);

  const [title, setTitle] = useState(initial?.title ?? presetRoleKey ?? "");
  const [jd, setJd] = useState(initial?.job_description ?? "");
  const [rows, setRows] = useState<Row[]>(
    initial?.rubric.criteria.map((c) => ({ ...c })) ?? [{ ...BLANK }],
  );
  const [vision, setVision] = useState(initial?.rubric.requires_visual_review ?? false);

  // The exact form dropdown value this job serves. Locked when setting up a
  // detected role — the admin never types or maps it.
  const [roleKey, setRoleKey] = useState(initial?.role_key ?? presetRoleKey ?? "");
  const locked = Boolean(presetRoleKey) && !isEdit;
  const [roles, setRoles] = useState<string[]>([]);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (locked) return;
    listRoles()
      .then((rs) => setRoles(rs.map((r) => r.role)))
      .catch(() => setRoles([]));
  }, [locked]);

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
    const criteria = rows.map((r) => ({ ...r, name: r.name.trim() })).filter((r) => r.name);
    if (!title.trim()) return setError("Give the role a title.");
    if (!roleKey.trim()) return setError("Pick the application-form role this job serves.");
    if (criteria.length === 0) return setError("Add at least one criterion to score against.");
    if (criteria.some((r) => !(r.weight > 0))) return setError("Every criterion needs a weight above zero.");

    setSaving(true);
    setError(null);
    const payload = {
      title: title.trim(),
      job_description: jd,
      role_key: roleKey.trim(),
      rubric: { job_title: title.trim(), criteria, requires_visual_review: vision },
    };
    try {
      const job = isEdit ? await updateJob(jobId!, payload) : await createJob(payload);
      // Prompt to pull applicants so any held rows for this role flow in.
      router.push(`/jobs/${job.id}?created=1`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the job. Try again.");
      setSaving(false);
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

  // Options = detected roles + the current value (so editing shows it selected).
  const roleOptions = Array.from(new Set([roleKey, ...roles].filter(Boolean)));

  return (
    <div className="space-y-5">
      {error && (
        <div className="rounded-lg px-3 py-2 text-sm" style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}>
          {error}
        </div>
      )}

      {/* Which application-form role this job serves */}
      <Card className="p-5">
        <h2 className="font-display text-sm font-medium">Application-form role</h2>
        <p className="mt-0.5 text-xs text-muted">
          The exact option applicants choose on the form. Applicants who picked this role route to this
          job automatically — no manual mapping.
        </p>
        <div className="mt-3">
          {locked ? (
            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium"
                style={{ borderColor: "var(--accent)", background: "var(--accent-tint)", color: "var(--accent-ink)" }}
              >
                {roleKey}
              </span>
              <span className="text-xs text-faint">locked — from the form dropdown</span>
            </div>
          ) : roleOptions.length > 0 ? (
            <Field label="Role" hint="Chosen from the roles detected on the application form.">
              <select
                value={roleKey}
                onChange={(e) => setRoleKey(e.target.value)}
                className="w-full rounded-lg border border-line-2 bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--accent-tint)]"
              >
                <option value="" disabled>
                  Select a role…
                </option>
                {roleOptions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label="Role key" hint="No roles detected from the form yet — enter the exact dropdown value this job serves.">
              <TextInput value={roleKey} onChange={(e) => setRoleKey(e.target.value)} placeholder="e.g. Graphic Design Intern" />
            </Field>
          )}
        </div>
      </Card>

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
            <p className="mt-0.5 text-xs text-muted">Each criterion is scored 0–100; weights set how much it counts.</p>
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
          <input type="checkbox" checked={vision} onChange={(e) => setVision(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
          <span>
            <span className="text-sm font-medium">Also score the CV's visual design</span>
            <span className="mt-0.5 block text-xs text-muted">
              On for design and brand roles, off otherwise. Off is cheaper and faster — it skips sending the page images to the model.
            </span>
          </span>
        </label>
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
