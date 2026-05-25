import { headers } from "next/headers";
import { requireSuperAdmin } from "@/lib/auth/require";
import { AuthTopbar } from "@/components/AuthTopbar";

export default async function SuperAdminLayout({ children }: { children: React.ReactNode }) {
  const session = await requireSuperAdmin();
  const headerStore = await headers();
  const pathname = headerStore.get("x-pathname") || "/super-admin";

  return (
    <div className="min-h-screen flex flex-col">
      <AuthTopbar role={session.role} activePath={pathname} />
      <main className="flex-1">{children}</main>
    </div>
  );
}
