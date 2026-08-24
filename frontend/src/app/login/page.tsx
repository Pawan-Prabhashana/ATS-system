"use client";

import { useState } from "react";
import Image from "next/image";
import { login } from "@/lib/api";
import { Button } from "@/components/ui";

/** Only allow same-origin internal redirects (defend against open-redirect). */
function safeNext(): string {
  if (typeof window === "undefined") return "/";
  const raw = new URLSearchParams(window.location.search).get("next");
  if (raw && raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "/";
}

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username.trim(), password);
      // Full navigation so the middleware re-runs with the fresh cookie.
      window.location.href = safeNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-6 py-12">
      {/* Ambient depth — soft accent glow behind the card, no motion */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 0%, var(--accent-tint), transparent 70%), radial-gradient(40% 40% at 85% 90%, color-mix(in srgb, var(--dec-sent) 18%, transparent), transparent 70%)",
        }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="overflow-hidden rounded-2xl shadow-[0_8px_30px_-8px_rgba(20,27,43,0.35)] ring-1 ring-line-2">
            <Image src="/Catalist-logo.jpeg" alt="Catalist" width={72} height={72} priority className="block h-[72px] w-[72px]" />
          </div>
          <h1 className="mt-5 font-display text-2xl font-medium tracking-tight">Catalist</h1>
          <p className="mt-1 text-sm text-muted">Recruit screening — sign in to continue</p>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-6 shadow-[0_10px_40px_-16px_rgba(20,27,43,0.28)]">
          <form onSubmit={onSubmit} className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink">Username</span>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                required
                className="w-full rounded-lg border border-line-2 bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--accent-tint)]"
                placeholder="admin"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink">Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                className="w-full rounded-lg border border-line-2 bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--accent-tint)]"
                placeholder="••••••••"
              />
            </label>

            {error && (
              <div
                role="alert"
                className="rounded-lg px-3 py-2 text-sm"
                style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}
              >
                {error}
              </div>
            )}

            <Button type="submit" loading={loading} className="w-full">
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-faint">
          Authorized team access only.
        </p>
      </div>
    </div>
  );
}
