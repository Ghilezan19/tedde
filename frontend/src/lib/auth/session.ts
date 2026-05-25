import { cookies } from "next/headers";
import { BACKEND_URL } from "@/lib/env";

export type Role = "admin" | "superadmin";

export interface Session {
  role: Role;
}

export async function getSession(): Promise<Session | null> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("tedde_session");

  if (!sessionCookie?.value) return null;

  try {
    const res = await fetch(`${BACKEND_URL}/api/auth/whoami`, {
      headers: { cookie: `tedde_session=${sessionCookie.value}` },
      cache: "no-store",
    });

    if (!res.ok) return null;

    const data = await res.json();
    return { role: data.role as Role };
  } catch {
    return null;
  }
}
