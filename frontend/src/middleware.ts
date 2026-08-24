import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Gate the app behind the shared login. The middleware only checks for the
// PRESENCE of the session cookie (a cheap first line); the backend is the real
// authority and returns 401 for an invalid/expired token, which the API client
// turns into a redirect back here. This just keeps logged-out users out of the
// app shell and logged-in users off the login screen.
const TOKEN_COOKIE = "catalist_token";

export function middleware(req: NextRequest) {
  // Local-dev bypass — mirror the backend's AUTH_ENABLED=false. BOTH must be
  // set to run without auth; production/hosted must leave both unset/true.
  if (process.env.NEXT_PUBLIC_AUTH_ENABLED === "false") {
    return NextResponse.next();
  }

  const { pathname } = req.nextUrl;
  const hasToken = Boolean(req.cookies.get(TOKEN_COOKIE)?.value);
  const isLogin = pathname === "/login";

  if (!hasToken && !isLogin) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + req.nextUrl.search)}`;
    return NextResponse.redirect(url);
  }

  if (hasToken && isLogin) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

// Run on all app routes, but skip Next internals and any static file (a path
// containing a dot — e.g. /Catalist-logo.jpeg, /favicon.ico) so assets load on
// the login page without being redirected.
export const config = {
  matcher: ["/((?!_next|.*\\..*).*)"],
};
