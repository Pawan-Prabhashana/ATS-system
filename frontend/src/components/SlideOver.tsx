"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

export function SlideOver({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/25 backdrop-blur-[1px] animate-[fade_150ms_ease-out]"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="absolute right-0 top-0 flex h-full w-full max-w-[720px] flex-col border-l border-line bg-bg shadow-2xl animate-[slidein_200ms_cubic-bezier(0.32,0.72,0,1)]"
      >
        {children}
      </div>
      <style>{`
        @keyframes slidein { from { transform: translateX(24px); opacity: 0.4 } to { transform: translateX(0); opacity: 1 } }
        @keyframes fade { from { opacity: 0 } to { opacity: 1 } }
      `}</style>
    </div>
  );
}
