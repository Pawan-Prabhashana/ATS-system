"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchMe,
  listChatMessages,
  postChatMessage,
  type ChatMessage,
  type Me,
} from "@/lib/api";
import { MicButton } from "@/components/MicButton";

const AVATAR_COLORS = [
  "#6366f1", "#0ea5e9", "#10b981", "#f59e0b",
  "#ef4444", "#ec4899", "#8b5cf6", "#14b8a6",
];

function colorFor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function shortTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const y = new Date();
  y.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return "Today";
  if (same(d, y)) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export default function TeamChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const lastIdRef = useRef(0);
  const atBottomRef = useRef(true);

  const merge = useCallback((incoming: ChatMessage[]) => {
    if (incoming.length === 0) return;
    setMessages((prev) => {
      const seen = new Set(prev.map((m) => m.id));
      const added = incoming.filter((m) => !seen.has(m.id));
      if (added.length === 0) return prev;
      const next = [...prev, ...added].sort((a, b) => a.id - b.id);
      lastIdRef.current = next[next.length - 1].id;
      return next;
    });
  }, []);

  // Initial load.
  useEffect(() => {
    let live = true;
    fetchMe().then((m) => live && setMe(m)).catch(() => {});
    listChatMessages()
      .then((msgs) => {
        if (!live) return;
        setMessages(msgs);
        lastIdRef.current = msgs.length ? msgs[msgs.length - 1].id : 0;
        setLoaded(true);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Couldn't load chat."));
    return () => {
      live = false;
    };
  }, []);

  // Poll for new messages.
  useEffect(() => {
    const t = setInterval(() => {
      listChatMessages(lastIdRef.current).then(merge).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [merge]);

  // Auto-scroll to the newest message when we're already near the bottom.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async function send() {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    atBottomRef.current = true;
    try {
      const msg = await postChatMessage(text);
      merge([msg]);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send. Try again.");
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  // Group consecutive messages by the same author (and insert day dividers).
  const groups = useMemo(() => {
    const out: { key: string; day: string | null; author: ChatMessage; items: ChatMessage[] }[] = [];
    let prevDay = "";
    for (const m of messages) {
      const day = new Date(m.created_at).toDateString();
      const dayDivider = day !== prevDay ? dayLabel(m.created_at) : null;
      prevDay = day;
      const last = out[out.length - 1];
      if (!dayDivider && last && last.author.username === m.username) {
        last.items.push(m);
      } else {
        out.push({ key: `${m.id}`, day: dayDivider, author: m, items: [m] });
      }
    }
    return out;
  }, [messages]);

  return (
    <div className="mx-auto flex h-[calc(100dvh-3.5rem)] max-w-3xl flex-col md:h-[100dvh]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-line px-6 py-4">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent-tint)] text-[var(--accent-ink)]">
          <IconChat />
        </span>
        <div>
          <h1 className="font-display text-lg font-medium tracking-tight">Team chat</h1>
          <p className="text-xs text-muted">Recruitment team — messages are saved for everyone.</p>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} onScroll={onScroll} className="thin-scroll flex-1 space-y-4 overflow-y-auto px-6 py-5">
        {error && (
          <div className="rounded-lg px-3 py-2 text-sm" style={{ color: "var(--tier-reject)", background: "var(--tier-reject-tint)" }}>
            {error}
          </div>
        )}
        {loaded && messages.length === 0 && (
          <div className="grid h-full place-items-center text-center text-sm text-muted">
            <div>
              <div className="text-2xl">💬</div>
              No messages yet — say hi to the team.
            </div>
          </div>
        )}
        {groups.map((g) => {
          const mine = me?.username === g.author.username;
          return (
            <div key={g.key}>
              {g.day && (
                <div className="my-4 flex items-center gap-3 text-[11px] font-medium uppercase tracking-wide text-faint">
                  <span className="h-px flex-1 bg-line" />
                  {g.day}
                  <span className="h-px flex-1 bg-line" />
                </div>
              )}
              <div className={`flex gap-2.5 ${mine ? "flex-row-reverse" : ""}`}>
                <span
                  className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold text-white"
                  style={{ background: colorFor(g.author.username) }}
                  title={g.author.full_name}
                >
                  {initials(g.author.full_name)}
                </span>
                <div className={`min-w-0 max-w-[78%] ${mine ? "items-end text-right" : ""} flex flex-col`}>
                  <div className={`mb-1 flex items-baseline gap-2 ${mine ? "flex-row-reverse" : ""}`}>
                    <span className="text-sm font-semibold text-ink">{g.author.full_name}</span>
                    <span className="font-mono text-[11px] text-faint">{shortTime(g.author.created_at)}</span>
                  </div>
                  <div className="space-y-1">
                    {g.items.map((m) => (
                      <div
                        key={m.id}
                        className={`inline-block whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                          mine
                            ? "bg-[var(--accent)] text-white"
                            : "bg-surface-2 text-ink"
                        }`}
                      >
                        {m.body}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Composer */}
      <div className="border-t border-line px-4 py-3">
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-surface px-3 py-2 focus-within:border-[var(--accent)]">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Message the team…  (Enter to send, Shift+Enter for a new line)"
            className="thin-scroll max-h-32 min-h-[24px] flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-faint"
          />
          <MicButton
            onText={(t) => {
              setDraft((d) => (d.trim() ? `${d.trim()} ${t}` : t));
              setError(null);
            }}
            onError={(m) => setError(m)}
          />
          <button
            onClick={() => void send()}
            disabled={sending || !draft.trim()}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--accent)] text-white transition-opacity disabled:opacity-40"
            aria-label="Send"
          >
            <IconSend />
          </button>
        </div>
      </div>
    </div>
  );
}

function IconChat() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 4.5A1.5 1.5 0 0 1 4 3h8a1.5 1.5 0 0 1 1.5 1.5v5A1.5 1.5 0 0 1 12 11H6.5L4 13.2V11h-.5A1.5 1.5 0 0 1 2.5 9.5z" />
    </svg>
  );
}
function IconSend() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 8h9M7.5 4l4 4-4 4" />
    </svg>
  );
}
