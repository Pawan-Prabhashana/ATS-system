"use client";

import { use } from "react";
import Link from "next/link";
import { CandidateDetail } from "@/components/CandidateDetail";
import { Card } from "@/components/ui";

export default function CandidatePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <Link href="/" className="text-sm text-[var(--accent-ink)] hover:underline">
        ← Jobs
      </Link>
      <Card className="mt-3 h-[calc(100dvh-8rem)] overflow-hidden">
        <CandidateDetail candidateId={id} />
      </Card>
    </div>
  );
}
