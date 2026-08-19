"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { getJob, type Job } from "@/lib/api";
import { JobForm } from "@/components/JobForm";
import { Spinner } from "@/components/ui";

export default function JobSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getJob(id)
      .then((j) => live && setJob(j))
      .catch((e) => live && setError(e instanceof Error ? e.message : "Couldn't load this job."));
    return () => {
      live = false;
    };
  }, [id]);

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <Link href={`/jobs/${id}`} className="text-sm text-[var(--accent-ink)] hover:underline">
        ← Pipeline
      </Link>
      <div className="mt-2 flex items-baseline gap-3">
        <h1 className="font-display text-2xl font-medium tracking-tight">Settings</h1>
        {job && <span className="font-mono text-sm text-faint">{job.id}</span>}
      </div>

      {error ? (
        <p className="mt-6 text-[var(--tier-reject)]">{error}</p>
      ) : !job ? (
        <div className="mt-10 flex items-center gap-2 text-muted">
          <Spinner /> Loading…
        </div>
      ) : (
        <div className="mt-6">
          <JobForm initial={job} jobId={id} />
        </div>
      )}
    </div>
  );
}
