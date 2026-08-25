"use client";

import { use } from "react";
import { JobForm } from "@/components/JobForm";

export default function NewJobPage({
  searchParams,
}: {
  searchParams: Promise<{ role?: string }>;
}) {
  const { role } = use(searchParams);
  const presetRole = role ? decodeURIComponent(role) : undefined;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="font-display text-2xl font-medium tracking-tight">
        {presetRole ? "Set up this role" : "New job"}
      </h1>
      <p className="mt-1 text-sm text-muted">
        {presetRole
          ? `Configure the job that scores applicants for “${presetRole}”. The role is locked to the form dropdown value.`
          : "Define the role, what you're scoring for, and which application-form role it serves."}
      </p>
      <div className="mt-6">
        <JobForm presetRoleKey={presetRole} />
      </div>
    </div>
  );
}
