// Single source of truth for talking to the Catalist backend.
// Base URL is env-configurable; defaults to the local dev backend.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Recommendation = "shortlist" | "borderline" | "reject";

export type CandidateStatus =
  | "parsed"
  | "scored"
  | "shortlisted"
  | "assignment_sent"
  | "submitted"
  | "rejected";

export type Decision = "shortlist" | "reject";
export type JobStatus = "open" | "closed";

export interface RubricCriterion {
  name: string;
  description: string;
  weight: number;
}

export interface Rubric {
  job_title: string;
  criteria: RubricCriterion[];
  requires_visual_review: boolean;
}

export interface Job {
  id: string;
  title: string;
  job_description: string;
  rubric: Rubric;
  status: JobStatus;
  google_sheet_id: string | null;
  assignment_brief_filename: string | null;
  assignment_deadline_days: number | null;
  assignment_message: string | null;
  created_at: string;
}

export interface JobCreatePayload {
  title: string;
  job_description: string;
  rubric: Rubric;
  google_sheet_id?: string | null;
  status?: JobStatus;
}

export type JobUpdatePayload = Partial<JobCreatePayload> & {
  assignment_deadline_days?: number | null;
  assignment_message?: string | null;
};

export interface IntakeProbeResult {
  connected: boolean;
  row_count: number;
  detected_columns: Record<string, string | null>;
  error: string | null;
}

export interface JobSummary {
  job_id: string;
  total: number;
  by_tier: Record<Recommendation, number>;
  by_status: Record<CandidateStatus, number>;
}

export interface Candidate {
  id: string;
  job_id: string;
  name: string | null;
  email: string | null;
  cv_filename: string;
  file_hash: string;
  created_at: string;
  status: CandidateStatus;
  reviewer_note: string | null;
  decided_at: string | null;
  assignment_sent_at: string | null;
  assignment_deadline: string | null;
  assignment_sent_count: number;
}

export interface CriterionScore {
  criterion_name: string;
  score: number;
  weight: number;
  evidence: string;
}

export interface Evaluation {
  candidate_id: string;
  criterion_scores: CriterionScore[];
  overall_score: number;
  recommendation: Recommendation;
  summary: string;
  evaluated_by: string;
}

export interface CandidateRecord {
  candidate: Candidate;
  evaluation: Evaluation | null;
  page_count: number;
  text_extraction_quality: string | null;
  artifact_dir: string | null;
  cv_file: string | null;
  page_image_files: string[];
}

export interface CandidateDetail {
  candidate: Candidate;
  evaluation: Evaluation | null;
  page_count: number;
  text_extraction_quality: string | null;
  cv_url: string | null;
  page_image_urls: string[];
  job_id: string | null;
  job_title: string | null;
}

export interface IngestionSummary {
  processed: number;
  skipped: number;
  failed: number;
  processed_candidate_ids: string[];
  skipped_candidate_ids: string[];
  failures: { submission_ref: string; name: string | null; reason: string }[];
}

export type SendOutcomeStatus =
  | "sent"
  | "skipped_not_shortlisted"
  | "skipped_already_sent"
  | "skipped_wrong_job"
  | "no_assignment_brief"
  | "not_found"
  | "failed"
  | "config_error";

export interface SendOutcome {
  candidate_id: string;
  success: boolean;
  status: SendOutcomeStatus;
  detail: string | null;
}

export interface BulkSendResult {
  job_id: string;
  requested_count: number;
  sent: SendOutcome[];
  skipped: SendOutcome[];
  failed: SendOutcome[];
  sent_count: number;
  skipped_count: number;
  failed_count: number;
}

/** Prefix a backend-relative path (e.g. /media/...) with the API base. */
export function mediaUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

// -- Jobs -------------------------------------------------------------------
export function listJobs(): Promise<Job[]> {
  return request<Job[]>("/jobs");
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`);
}

export function createJob(payload: JobCreatePayload): Promise<Job> {
  return request<Job>("/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function updateJob(id: string, patch: JobUpdatePayload): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function closeJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/close`, { method: "POST" });
}

// -- Assignment brief -------------------------------------------------------
export function briefUrl(id: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(id)}/assignment-brief`;
}

export async function uploadBrief(id: string, file: File): Promise<Job> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(briefUrl(id), { method: "POST", body: fd, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = (await res.json()) as { detail?: string };
      if (b?.detail) detail = b.detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as Job;
}

export function deleteBrief(id: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/assignment-brief`, {
    method: "DELETE",
  });
}

export function testIntake(
  id: string,
  googleSheetId?: string | null,
): Promise<IntakeProbeResult> {
  return request<IntakeProbeResult>(`/jobs/${encodeURIComponent(id)}/test-intake`, {
    method: "POST",
    body: JSON.stringify({ google_sheet_id: googleSheetId?.trim() || null }),
  });
}

export function getJobSummary(id: string): Promise<JobSummary> {
  return request<JobSummary>(`/jobs/${encodeURIComponent(id)}/summary`);
}

export function ingestJob(id: string): Promise<IngestionSummary> {
  return request<IngestionSummary>(`/jobs/${encodeURIComponent(id)}/ingest`, {
    method: "POST",
  });
}

export function listJobCandidates(
  id: string,
  opts: { tier?: Recommendation; status?: CandidateStatus } = {},
): Promise<CandidateRecord[]> {
  const params = new URLSearchParams();
  if (opts.tier) params.set("tier", opts.tier);
  if (opts.status) params.set("status", opts.status);
  const qs = params.toString();
  return request<CandidateRecord[]>(
    `/jobs/${encodeURIComponent(id)}/candidates${qs ? `?${qs}` : ""}`,
  );
}

export function bulkSendAssignments(
  id: string,
  candidateIds: string[] | null,
  force = false,
): Promise<BulkSendResult> {
  return request<BulkSendResult>(
    `/jobs/${encodeURIComponent(id)}/send-assignments`,
    { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, force }) },
  );
}

// -- Candidates -------------------------------------------------------------
export function getCandidate(id: string): Promise<CandidateDetail> {
  return request<CandidateDetail>(`/candidates/${encodeURIComponent(id)}`);
}

export type DecisionInput = Decision | "undecided";

export function decideCandidate(
  id: string,
  decision: DecisionInput,
  note: string | null = null,
): Promise<CandidateDetail> {
  return request<CandidateDetail>(
    `/candidates/${encodeURIComponent(id)}/decision`,
    { method: "PATCH", body: JSON.stringify({ decision, note }) },
  );
}

export function sendAssignment(
  id: string,
  force = false,
): Promise<CandidateDetail> {
  return request<CandidateDetail>(
    `/candidates/${encodeURIComponent(id)}/send-assignment`,
    { method: "POST", body: JSON.stringify({ force }) },
  );
}
