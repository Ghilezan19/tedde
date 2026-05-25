import Link from "next/link";
import { LogOut, Camera, Settings, Shield, LayoutDashboard } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";
import type { Role } from "@/lib/auth/session";

interface AuthTopbarProps {
  role: Role;
  activePath?: string;
}

export function AuthTopbar({ role, activePath }: AuthTopbarProps) {
  const isSuperAdmin = role === "superadmin";

  const navLinks = isSuperAdmin
    ? [
        { href: "/admin", label: "Admin", icon: LayoutDashboard },
        { href: "/super-admin", label: "Super-Admin", icon: Shield },
        { href: "/configure", label: "Configure", icon: Settings },
      ]
    : [
        { href: "/admin", label: "Admin", icon: LayoutDashboard },
      ];

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-card/95 backdrop-blur-sm supports-[backdrop-filter]:bg-card/80">
      <div className="mx-auto flex h-14 max-w-screen-xl items-center gap-6 px-4 sm:px-6">
        {/* Brand */}
        <Link href="/admin" className="flex items-center gap-2 font-semibold text-foreground shrink-0">
          <Camera className="h-5 w-5 text-primary" />
          <span className="hidden sm:inline">Tedde Auto</span>
        </Link>

        {/* Nav */}
        <nav className="flex items-center gap-1">
          {navLinks.map(({ href, label, icon: Icon }) => {
            const isActive = activePath === href || activePath?.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Right side */}
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <a
            href="/logout"
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Logout</span>
          </a>
        </div>
      </div>
    </header>
  );
}
