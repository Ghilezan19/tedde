import { redirect } from "next/navigation";
import { getSession } from "./session";

export async function requireAdmin() {
  const session = await getSession();
  if (!session) redirect("/login");
  return session;
}

export async function requireSuperAdmin() {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.role !== "superadmin") redirect("/admin");
  return session;
}
