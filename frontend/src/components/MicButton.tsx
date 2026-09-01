"use client";

import { useRef, useState } from "react";
import { transcribeAudio } from "@/lib/api";
import { Spinner } from "@/components/ui";

type State = "idle" | "recording" | "transcribing";

function pickMime(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  if (typeof MediaRecorder === "undefined") return "";
  for (const t of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(t)) return t;
    } catch {
      /* ignore */
    }
  }
  return "";
}

/** A mic button that records, transcribes via /transcribe, and returns the text.
 *  Click to start, click again to stop; then it transcribes and calls onText. */
export function MicButton({
  onText,
  onError,
  title = "Record voice → text",
  size = 34,
  className = "",
}: {
  onText: (text: string) => void;
  onError?: (msg: string) => void;
  title?: string;
  size?: number;
  className?: string;
}) {
  const [state, setState] = useState<State>("idle");
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const mimeRef = useRef<string>("");

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      onError?.("Voice recording isn't supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = pickMime();
      mimeRef.current = mime;
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        const type = mimeRef.current || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        if (blob.size === 0) {
          setState("idle");
          return;
        }
        setState("transcribing");
        try {
          const ext = type.includes("mp4") ? "mp4" : type.includes("ogg") ? "ogg" : "webm";
          const text = await transcribeAudio(blob, `voice.${ext}`);
          if (text) onText(text);
          else onError?.("Didn't catch that — try speaking again.");
        } catch (e) {
          onError?.(e instanceof Error ? e.message : "Couldn't transcribe. Try again.");
        } finally {
          setState("idle");
        }
      };
      rec.start();
      recRef.current = rec;
      setState("recording");
    } catch {
      onError?.("Microphone access is blocked. Allow mic access in your browser and try again.");
      setState("idle");
    }
  }

  function toggle() {
    if (state === "idle") void start();
    else if (state === "recording") recRef.current?.stop();
  }

  const recording = state === "recording";
  const busy = state === "transcribing";

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      title={recording ? "Stop & transcribe" : title}
      aria-label={recording ? "Stop recording" : title}
      className={`grid shrink-0 place-items-center rounded-full transition-colors ${
        recording
          ? "animate-pulse bg-[var(--tier-reject)] text-white shadow-[var(--shadow-sm)]"
          : "text-muted hover:bg-surface-2 hover:text-ink"
      } ${busy ? "opacity-60" : ""} ${className}`}
      style={{ height: size, width: size }}
    >
      {busy ? <Spinner /> : recording ? <StopIcon /> : <MicIcon />}
    </button>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <rect x="6" y="1.5" width="4" height="8" rx="2" />
      <path d="M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2.5M6 14.5h4" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor">
      <rect x="3.5" y="3.5" width="9" height="9" rx="2" />
    </svg>
  );
}
