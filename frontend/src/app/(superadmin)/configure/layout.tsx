import Link from "next/link";
import { headers } from "next/headers";
import { Camera, Cpu, Smartphone, Globe, BarChart } from "lucide-react";

const NAV = [
  { href: "/configure/cameras-streaming", label: "Camere & Streaming", icon: Camera },
  { href: "/configure/automation", label: "Automatizare", icon: Cpu },
  { href: "/configure/portal-sms", label: "Portal & SMS", icon: Smartphone },
  { href: "/configure/network-esp", label: "Rețea & ESP", icon: Globe },
  { href: "/configure/system-gallery", label: "Sistem & Galerie", icon: BarChart },
];

export default async function ConfigureLayout({ children }: { children: React.ReactNode }) {
  const headerStore = await headers();
  const pathname = headerStore.get("x-pathname") || "";

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)]">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r bg-sidebar hidden md:flex flex-col py-4">
        <p className="px-4 mb-2 text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
          Configurare
        </p>
        <nav className="flex flex-col gap-0.5 px-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const isActive = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Mobile nav */}
      <div className="md:hidden border-b w-full flex overflow-x-auto py-2 px-4 gap-2 bg-card">
        {NAV.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shrink-0 transition-colors ${
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </Link>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">{children}</div>
      </div>
    </div>
  );
}
