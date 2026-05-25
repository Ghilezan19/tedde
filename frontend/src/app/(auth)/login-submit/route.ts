import { NextRequest, NextResponse } from "next/server";

const BACKEND = () => process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** Forward Set-Cookie from upstream (FastAPI) to the browser response. */
function appendSetCookies(from: Headers, to: NextResponse) {
  const ext = from as Headers & { getSetCookie?: () => string[] };
  if (typeof ext.getSetCookie === "function") {
    for (const c of ext.getSetCookie()) {
      to.headers.append("Set-Cookie", c);
    }
    return;
  }
  const single = from.get("set-cookie");
  if (single) {
    to.headers.append("Set-Cookie", single);
  }
}

/**
 * POST proxy to FastAPI /login (cannot live in /login alongside page.tsx — Next conflict).
 * Form on /login posts here with action="/login-submit".
 */
export async function POST(request: NextRequest) {
  const backend = BACKEND().replace(/\/$/, "");
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json({ error: "Invalid form" }, { status: 400 });
  }

  const params = new URLSearchParams();
  for (const [key, value] of formData.entries()) {
    if (typeof value === "string") {
      params.append(key, value);
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params.toString(),
      redirect: "manual",
    });
  } catch {
    // Relative redirect — browser resolves against current origin
    const loc = `/login?error=backend&next=${encodeURIComponent(params.get("next") || "/admin")}`;
    return new NextResponse(null, { status: 302, headers: { Location: loc } });
  }

  const loc = upstream.headers.get("location");
  if (upstream.status >= 300 && upstream.status < 400 && loc) {
    // If backend returns an absolute URL to its own host (127.0.0.1:8000 or localhost),
    // strip the host so the browser resolves against the public origin (video.tedde-auto.ro).
    let redirectLocation = loc;
    if (loc.startsWith("http://") || loc.startsWith("https://")) {
      try {
        const u = new URL(loc);
        redirectLocation = u.pathname + u.search + u.hash;
      } catch {
        // leave as-is
      }
    }
    const res = new NextResponse(null, {
      status: upstream.status,
      headers: { Location: redirectLocation },
    });
    appendSetCookies(upstream.headers, res);
    return res;
  }

  if (upstream.status === 200) {
    const html = await upstream.text();
    return new NextResponse(html, {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }

  const body = await upstream.text();
  return new NextResponse(body, { status: upstream.status });
}
