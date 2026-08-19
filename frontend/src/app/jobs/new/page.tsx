import { JobForm } from "@/components/JobForm";

export default function NewJobPage() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="font-display text-2xl font-medium tracking-tight">New job</h1>
      <p className="mt-1 text-sm text-muted">
        Define the role, what you&apos;re scoring for, and where applications come from.
      </p>
      <div className="mt-6">
        <JobForm />
      </div>
    </div>
  );
}
