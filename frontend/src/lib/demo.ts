// Demo-mode data layer (Phase 14).
//
// When NEXT_PUBLIC_DEMO_MODE=true the api client routes every call here instead
// of hitting a backend. Reads come from a bundled snapshot of the real data;
// mutations update an IN-MEMORY session store so the UI feels live but nothing
// persists (a page refresh reloads this module and resets everything).
//
// This is a FROZEN SNAPSHOT, not a live system: real ingestion and real email
// are impossible offline, so those actions are simulated and each triggering
// component renders an honest inline "Demo build — … simulated" note.
import snapshotJson from "@/demo-data/snapshot.json";
import type {
  BulkSendResult,
  CandidateDetail,
  CandidateRecord,
  CandidateStatus,
  DecisionInput,
  IntakeStatus,
  Job,
  JobCreatePayload,
  JobSummary,
  JobUpdatePayload,
  Me,
  Recommendation,
  RoleInfo,
  SiteIngestionSummary,
} from "./api";

type Snapshot = {
  jobs: Job[];
  summaryByJob: Record<string, JobSummary>;
  candidatesByJob: Record<string, CandidateRecord[]>;
  candidateDetail: Record<string, CandidateDetail>;
  me: Me;
};

const snapshot = snapshotJson as unknown as Snapshot;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

// -- Mutable session state (resets on refresh) ------------------------------
const jobs: Job[] = clone(snapshot.jobs);
const candidatesByJob: Record<string, CandidateRecord[]> = clone(snapshot.candidatesByJob);
const candidateDetail: Record<string, CandidateDetail> = clone(snapshot.candidateDetail);

// -- helpers ----------------------------------------------------------------
function notFound(what: string): never {
  throw new Error(`404: ${what} not found.`);
}

const DECISION_STATUS: Record<DecisionInput, CandidateStatus> = {
  shortlist: "shortlisted",
  reject: "rejected",
  undecided: "scored",
};

function findRecord(candidateId: string): CandidateRecord | null {
  for (const rows of Object.values(candidatesByJob)) {
    const r = rows.find((x) => x.candidate.id === candidateId);
    if (r) return r;
  }
  return null;
}

/** Apply a change to a candidate in BOTH stores (list record + detail) so the
 *  pipeline, summary, and detail panel all stay in sync. */
function mutateCandidate(candidateId: string, fn: (c: CandidateDetail["candidate"]) => void): void {
  const rec = findRecord(candidateId);
  if (rec) fn(rec.candidate);
  const det = candidateDetail[candidateId];
  if (det) fn(det.candidate);
}

function computeSummary(jobId: string): JobSummary {
  const rows = candidatesByJob[jobId] ?? [];
  const by_tier = { shortlist: 0, borderline: 0, reject: 0 } as Record<Recommendation, number>;
  const by_status = {
    parsed: 0,
    scored: 0,
    shortlisted: 0,
    assignment_sent: 0,
    submitted: 0,
    rejected: 0,
  } as Record<CandidateStatus, number>;
  for (const r of rows) {
    const t = r.evaluation?.recommendation;
    if (t) by_tier[t] += 1;
    by_status[r.candidate.status] += 1;
  }
  return { job_id: jobId, total: rows.length, by_tier, by_status };
}

/** Media paths are already same-origin (/media/...) in the snapshot; strip any
 *  absolute host defensively so demo images always hit public/ static files. */
function toRelativeMedia(url: string | null): string | null {
  if (!url) return url;
  return url.replace(/^https?:\/\/[^/]+/, "");
}
function fixDetailMedia(d: CandidateDetail): CandidateDetail {
  d.cv_url = toRelativeMedia(d.cv_url);
  d.page_image_urls = d.page_image_urls.map((u) => toRelativeMedia(u) as string);
  return d;
}

function slugify(title: string): string {
  const base = title.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "job";
  let id = base;
  let n = 2;
  while (jobs.some((j) => j.id === id)) id = `${base}-${n++}`;
  return id;
}

// =========================================================================== //
// Reads
// =========================================================================== //
export const demoListJobs = (): Job[] => clone(jobs);

export const demoGetJob = (id: string): Job => {
  const j = jobs.find((x) => x.id === id);
  if (!j) notFound(`Job ${id}`);
  return clone(j!);
};

export const demoGetJobSummary = (id: string): JobSummary => computeSummary(id);

export const demoListJobCandidates = (
  id: string,
  opts: { tier?: Recommendation; status?: CandidateStatus } = {},
): CandidateRecord[] => {
  let rows = (candidatesByJob[id] ?? []).slice();
  if (opts.tier) rows = rows.filter((r) => r.evaluation?.recommendation === opts.tier);
  if (opts.status) rows = rows.filter((r) => r.candidate.status === opts.status);
  return clone(rows);
};

export const demoGetCandidate = (id: string): CandidateDetail => {
  const d = candidateDetail[id];
  if (!d) notFound(`Candidate ${id}`);
  return fixDetailMedia(clone(d!));
};

export const demoFetchMe = (): Me => ({
  authenticated: true,
  username: snapshot.me?.username ?? "demo",
  auth_enabled: true,
});

// =========================================================================== //
// Mutations (session-only)
// =========================================================================== //
export const demoDecideCandidate = (
  id: string,
  decision: DecisionInput,
  note: string | null,
): CandidateDetail => {
  const status = DECISION_STATUS[decision];
  if (!status) throw new Error(`Invalid decision ${decision}`);
  mutateCandidate(id, (c) => {
    c.status = status;
    if (decision === "undecided") {
      c.reviewer_note = null;
      c.decided_at = null;
    } else {
      c.reviewer_note = note;
      c.decided_at = new Date().toISOString();
    }
  });
  return demoGetCandidate(id);
};

function simulateSend(id: string): void {
  const deadline = new Date();
  deadline.setDate(deadline.getDate() + 5);
  mutateCandidate(id, (c) => {
    c.status = "assignment_sent";
    c.assignment_sent_at = new Date().toISOString();
    c.assignment_deadline = deadline.toISOString().slice(0, 10);
    c.assignment_sent_count = (c.assignment_sent_count ?? 0) + 1;
  });
}

export const demoSendAssignment = (id: string): CandidateDetail => {
  simulateSend(id);
  return demoGetCandidate(id);
};

export const demoBulkSend = (
  jobId: string,
  candidateIds: string[] | null,
): BulkSendResult => {
  const rows = candidatesByJob[jobId] ?? [];
  const targets = rows.filter(
    (r) =>
      (candidateIds ? candidateIds.includes(r.candidate.id) : r.candidate.status === "shortlisted") &&
      r.candidate.status === "shortlisted",
  );
  const sent = targets.map((r) => {
    simulateSend(r.candidate.id);
    return { candidate_id: r.candidate.id, success: true, status: "sent" as const, detail: null };
  });
  return {
    job_id: jobId,
    requested_count: candidateIds?.length ?? targets.length,
    sent,
    skipped: [],
    failed: [],
    sent_count: sent.length,
    skipped_count: 0,
    failed_count: 0,
  };
};

export const demoSiteIngest = (): SiteIngestionSummary => {
  // Frozen snapshot — everyone is already in; nothing new is fetched.
  const total = Object.values(candidatesByJob).reduce((n, rows) => n + rows.length, 0);
  return {
    processed: 0,
    processed_by_job: {},
    skipped_duplicate: total,
    held_total: 0,
    held_by_role: {},
    failed: 0,
    failures: [],
    processed_candidate_ids: [],
  };
};

export const demoListRoles = (): RoleInfo[] =>
  jobs
    .map((j) => ({
      role: j.role_key || j.title,
      applicant_count: (candidatesByJob[j.id] ?? []).length,
      has_job: true,
      job_id: j.id,
      job_title: j.title,
    }))
    .sort((a, b) => a.role.localeCompare(b.role));

export const demoIntakeStatus = (): IntakeStatus => ({
  connected: true,
  row_count: Object.values(candidatesByJob).reduce((n, rows) => n + rows.length, 0),
  role_column_detected: true,
  detected_columns: { role: "Which role?" },
  distinct_roles: jobs.map((j) => j.role_key || j.title).sort(),
  error: null,
});

export const demoCreateJob = (payload: JobCreatePayload): Job => {
  const id = slugify(payload.title);
  const job: Job = {
    id,
    title: payload.title,
    job_description: payload.job_description,
    rubric: {
      job_title: payload.rubric.job_title,
      criteria: payload.rubric.criteria,
      requires_visual_review: payload.rubric.requires_visual_review ?? false,
    },
    status: payload.status ?? "open",
    role_key: payload.role_key || payload.title,
    google_sheet_id: null,
    assignment_brief_filename: null,
    assignment_deadline_days: null,
    assignment_message: null,
    created_at: new Date().toISOString(),
  };
  jobs.push(job);
  candidatesByJob[id] = [];
  return clone(job);
};

export const demoUpdateJob = (id: string, patch: JobUpdatePayload): Job => {
  const j = jobs.find((x) => x.id === id);
  if (!j) notFound(`Job ${id}`);
  Object.assign(j!, patch);
  return clone(j!);
};

export const demoCloseJob = (id: string): Job => {
  const j = jobs.find((x) => x.id === id);
  if (!j) notFound(`Job ${id}`);
  j!.status = "closed";
  return clone(j!);
};

export const demoUploadBrief = (id: string, filename: string): Job => {
  const j = jobs.find((x) => x.id === id);
  if (!j) notFound(`Job ${id}`);
  j!.assignment_brief_filename = filename;
  return clone(j!);
};

export const demoDeleteBrief = (id: string): Job => {
  const j = jobs.find((x) => x.id === id);
  if (!j) notFound(`Job ${id}`);
  j!.assignment_brief_filename = null;
  return clone(j!);
};

export const demoOpenBrief = (): void => {
  // No-op: the assignment brief file isn't bundled in the snapshot. The Preview
  // control simply does nothing in demo mode.
};

// -- Demo auth --------------------------------------------------------------
// The gate is COSMETIC in demo mode: the data is a public snapshot, not live
// records. A configured passcode is checked purely so the branded login screen
// is part of the showcase.
export const DEMO_PASSCODE = process.env.NEXT_PUBLIC_DEMO_PASSCODE ?? "";

export function demoLoginCheck(password: string): void {
  if (DEMO_PASSCODE && password !== DEMO_PASSCODE) {
    throw new Error("Incorrect passcode.");
  }
}
