import { BACKEND_URL } from "@/lib/env";

// Server-side fetch with session cookie forwarding
export async function serverFetch(path: string, init?: RequestInit): Promise<Response> {
  const { cookies } = await import("next/headers");
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("tedde_session");

  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init?.headers || {}),
      ...(sessionCookie ? { cookie: `tedde_session=${sessionCookie.value}` } : {}),
    },
  });
}

// Client-side fetch (same origin via nginx/rewrites, cookie auto-included)
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path.startsWith("/") ? path : `/${path}`}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  return res.json();
}
