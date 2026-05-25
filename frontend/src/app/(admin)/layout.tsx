import { headers } from "next/headers";
import { requireAdmin } from "@/lib/auth/require";
import { AuthTopbar } from "@/components/AuthTopbar";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await requireAdmin();
  const headerStore = await headers();
  const pathname = headerStore.get("x-pathname") || "/admin";

  return (
    <div className="min-h-screen flex flex-col">
      <AuthTopbar role={session.role} activePath={pathname} />
      <main className="flex-1">{children}</main>
    </div>
  );
}
