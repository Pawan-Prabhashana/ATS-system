// Single source of truth for talking to the Catalist backend.
//
// DEMO MODE (Phase 14): when NEXT_PUBLIC_DEMO_MODE=true every call is served
// from a bundled snapshot + in-memory session store (see ./demo) — no network,
// no backend. API_BASE is forced to "" so media URLs (/media/...) resolve to the
// same-origin static files in public/. The live-backend path below is untouched.
import * as demo from "./demo";

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// Base URL is env-configurable; defaults to the local dev backend. Empty in
// demo mode so nothing points at a backend.
export const API_BASE = DEMO_MODE
  ? ""
  : process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// --- Auth (Phase 12) -------------------------------------------------------
// Session transport is a Bearer JWT (see app/auth.py for why not cookies). The
// token lives in a JS-readable cookie so the Next.js middleware can gate routes
// AND this client can send it as `Authorization: Bearer` on every call.
export const TOKEN_COOKIE = "catalist_token";

export function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)catalist_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function setToken(token: string, expiresAt?: string): void {
  if (typeof document === "undefined") return;
  const parts = [`${TOKEN_COOKIE}=${encodeURIComponent(token)}`, "path=/", "SameSite=Lax"];
  if (expiresAt) parts.push(`expires=${new Date(expiresAt).toUTCString()}`);
  document.cookie = parts.join("; ");
}

export function clearToken(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${TOKEN_COOKIE}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax`;
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** An expired/invalid session (API 401): drop the token and bounce to /login. */
function onUnauthorized(): void {
  clearToken();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
}

export interface Me {
  authenticated: boolean;
  username: string | null;
  auth_enabled: boolean;
}

/** Log in; stores the session token on success. Throws with the server's
 *  message on bad credentials (a 401 here is shown inline, NOT a redirect). */
export async function login(username: string, password: string): Promise<void> {
  if (DEMO_MODE) {
    demo.demoLoginCheck(password); // cosmetic passcode gate; throws on mismatch
    setToken("demo-session"); // cookie so the Next middleware lets the app render
    return;
  }
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let detail = "Login failed. Check your credentials and try again.";
    try {
      const b = (await res.json()) as { detail?: string };
      if (b?.detail) detail = b.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const data = (await res.json()) as { token: string; expires_at: string };
  setToken(data.token, data.expires_at);
}

export async function logout(): Promise<void> {
  if (!DEMO_MODE) {
    try {
      await fetch(`${API_BASE}/auth/logout`, { method: "POST", headers: authHeaders() });
    } catch {
      /* best-effort; the token is client-side anyway */
    }
  }
  clearToken();
}

export async function fetchMe(): Promise<Me> {
  if (DEMO_MODE) return demo.demoFetchMe();
  const res = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders(), cache: "no-store" });
  return (await res.json()) as Me;
}

/** Fetch a protected file (e.g. the assignment brief) WITH the session and open
 *  it in a new tab — plain <a href> links can't carry the Authorization header. */
export async function openAuthedFile(path: string): Promise<void> {
  if (DEMO_MODE) {
    demo.demoOpenBrief();
    return;
  }
  // Fire-and-forget from the UI — never reject (avoid unhandled rejections).
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders(), cache: "no-store" });
    if (res.status === 401) {
      onUnauthorized();
      return;
    }
    if (!res.ok) return; // brief only offered when present; a rare miss is a no-op
    const url = URL.createObjectURL(await res.blob());
    if (typeof window !== "undefined") window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch {
    /* network hiccup — silently ignore for this fire-and-forget open */
  }
}

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
  /** The exact form-dropdown value this job serves (Phase 15). */
  role_key: string;
  google_sheet_id: string | null; // deprecated; kept for back-compat, not shown in UI
  assignment_brief_filename: string | null;
  assignment_deadline_days: number | null;
  assignment_message: string | null;
  created_at: string;
}

export interface JobCreatePayload {
  title: string;
  job_description: string;
  rubric: Rubric;
  role_key: string;
  status?: JobStatus;
}

export type JobUpdatePayload = Partial<JobCreatePayload> & {
  assignment_deadline_days?: number | null;
  assignment_message?: string | null;
};

/** A role seen on the single application form (+ whether a job serves it). */
export interface RoleInfo {
  role: string;
  applicant_count: number;
  has_job: boolean;
  job_id: string | null;
  job_title: string | null;
}

/** Site-form connection status (one form for all roles). */
export interface IntakeStatus {
  connected: boolean;
  row_count: number;
  role_column_detected: boolean;
  detected_columns: Record<string, string | null>;
  distinct_roles: string[];
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

export interface IngestionFailure {
  submission_ref: string;
  name: string | null;
  reason: string;
}

/** Result of a single site-level pull, routed to jobs by role_key. */
export interface SiteIngestionSummary {
  processed: number;
  processed_by_job: Record<string, number>;
  skipped_duplicate: number;
  held_total: number;
  /** role string -> count of applicants for a role with no configured job yet. */
  held_by_role: Record<string, number>;
  failed: number;
  failures: IngestionFailure[];
  processed_candidate_ids: string[];
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

/** Prefix a backend-relative path (e.g. /media/...) with the API base. In demo
 *  mode API_BASE is "" so this returns a same-origin path served from public/. */
export function mediaUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** Wrap a synchronous demo result as a Promise so a sync throw becomes a
 *  rejection (matching the real network functions callers already await). */
function demoCall<T>(fn: () => T): Promise<T> {
  return Promise.resolve().then(fn);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (DEMO_MODE) {
    // Safety net: no request() call should be reached in demo mode (every public
    // function branches to ./demo first). If one ever is, fail loud rather than
    // silently hit a backend.
    throw new Error("Demo mode: network requests are disabled.");
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new Error("401: Your session has expired. Please sign in again.");
  }
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
  if (DEMO_MODE) return demoCall(() => demo.demoListJobs());
  return request<Job[]>("/jobs");
}

export function getJob(id: string): Promise<Job> {
  if (DEMO_MODE) return demoCall(() => demo.demoGetJob(id));
  return request<Job>(`/jobs/${encodeURIComponent(id)}`);
}

export function createJob(payload: JobCreatePayload): Promise<Job> {
  if (DEMO_MODE) return demoCall(() => demo.demoCreateJob(payload));
  return request<Job>("/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function updateJob(id: string, patch: JobUpdatePayload): Promise<Job> {
  if (DEMO_MODE) return demoCall(() => demo.demoUpdateJob(id, patch));
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function closeJob(id: string): Promise<Job> {
  if (DEMO_MODE) return demoCall(() => demo.demoCloseJob(id));
  return request<Job>(`/jobs/${encodeURIComponent(id)}/close`, { method: "POST" });
}

// -- Assignment brief -------------------------------------------------------
export function briefUrl(id: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(id)}/assignment-brief`;
}

export async function uploadBrief(id: string, file: File): Promise<Job> {
  if (DEMO_MODE) return demo.demoUploadBrief(id, file.name);
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(briefUrl(id), {
    method: "POST",
    body: fd,
    headers: authHeaders(),
    cache: "no-store",
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new Error("401: Your session has expired. Please sign in again.");
  }
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
  if (DEMO_MODE) return demoCall(() => demo.demoDeleteBrief(id));
  return request<Job>(`/jobs/${encodeURIComponent(id)}/assignment-brief`, {
    method: "DELETE",
  });
}

export function getJobSummary(id: string): Promise<JobSummary> {
  if (DEMO_MODE) return demoCall(() => demo.demoGetJobSummary(id));
  return request<JobSummary>(`/jobs/${encodeURIComponent(id)}/summary`);
}

// -- Site-level intake (Phase 15): one form, routed by role_key -------------
/** Pull ALL new applicants from the single form; routes each to a job by role. */
export function siteIngest(): Promise<SiteIngestionSummary> {
  if (DEMO_MODE) return demoCall(() => demo.demoSiteIngest());
  return request<SiteIngestionSummary>("/ingest", { method: "POST" });
}

/** Every role on the form + whether a job serves it (powers "needs setup"). */
export function listRoles(): Promise<RoleInfo[]> {
  if (DEMO_MODE) return demoCall(() => demo.demoListRoles());
  return request<RoleInfo[]>("/roles");
}

/** Is the single form readable and its role column detected? */
export function getIntakeStatus(): Promise<IntakeStatus> {
  if (DEMO_MODE) return demoCall(() => demo.demoIntakeStatus());
  return request<IntakeStatus>("/intake/status");
}

export function listJobCandidates(
  id: string,
  opts: { tier?: Recommendation; status?: CandidateStatus } = {},
): Promise<CandidateRecord[]> {
  if (DEMO_MODE) return demoCall(() => demo.demoListJobCandidates(id, opts));
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
  if (DEMO_MODE) return demoCall(() => demo.demoBulkSend(id, candidateIds));
  return request<BulkSendResult>(
    `/jobs/${encodeURIComponent(id)}/send-assignments`,
    { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, force }) },
  );
}

// -- Candidates -------------------------------------------------------------
export function getCandidate(id: string): Promise<CandidateDetail> {
  if (DEMO_MODE) return demoCall(() => demo.demoGetCandidate(id));
  return request<CandidateDetail>(`/candidates/${encodeURIComponent(id)}`);
}

export type DecisionInput = Decision | "undecided";

export function decideCandidate(
  id: string,
  decision: DecisionInput,
  note: string | null = null,
): Promise<CandidateDetail> {
  if (DEMO_MODE) return demoCall(() => demo.demoDecideCandidate(id, decision, note));
  return request<CandidateDetail>(
    `/candidates/${encodeURIComponent(id)}/decision`,
    { method: "PATCH", body: JSON.stringify({ decision, note }) },
  );
}

export function sendAssignment(
  id: string,
  force = false,
): Promise<CandidateDetail> {
  if (DEMO_MODE) return demoCall(() => demo.demoSendAssignment(id));
  return request<CandidateDetail>(
    `/candidates/${encodeURIComponent(id)}/send-assignment`,
    { method: "POST", body: JSON.stringify({ force }) },
  );
}
