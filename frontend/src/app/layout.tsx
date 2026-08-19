import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Catalist — Recruit Screening",
  description: "Screen, review, and shortlist candidates across jobs.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full`}
    >
      <body className="min-h-full">
        <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md">
          <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-6">
            <a href="/" className="flex items-center gap-2">
              <span className="grid h-6 w-6 place-items-center rounded-md bg-ink text-[13px] font-bold text-[var(--bg)]">
                C
              </span>
              <span className="text-[15px] font-semibold tracking-tight">
                Catalist
              </span>
              <span className="text-[13px] text-muted">Recruit Screening</span>
            </a>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
