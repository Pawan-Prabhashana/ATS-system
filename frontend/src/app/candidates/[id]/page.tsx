"use client";

import { use } from "react";
import { CandidateDetail } from "@/components/CandidateDetail";
import { Card } from "@/components/ui";

export default function CandidatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <a href="/" className="text-sm text-link hover:underline">
        ← Jobs
      </a>
      <Card className="mt-3 h-[calc(100vh-8rem)] overflow-hidden">
        <CandidateDetail candidateId={id} />
      </Card>
    </main>
  );
}
