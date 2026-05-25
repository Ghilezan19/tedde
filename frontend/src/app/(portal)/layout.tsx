import type { ReactNode } from "react";

interface BrandData {
  brand_name?: string;
  theme_accent?: string;
  theme_dark?: string;
}

async function getBrand(): Promise<BrandData> {
  try {
    const res = await fetch(`${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/api/customer-portal/brand`, {
      next: { revalidate: 60 },
    });
    if (res.ok) return res.json();
  } catch {}
  return {};
}

export default async function PortalLayout({ children }: { children: ReactNode }) {
  const brand = await getBrand();

  // Force all semantic tokens to light values so dark-mode ThemeProvider has no effect.
  // Portal has its own fixed palette driven by --tedde-* variables.
  const cssVars: Record<string, string> = {
    "--background": "#f0f4f7",
    "--foreground": "#111111",
    "--card": "#ffffff",
    "--card-foreground": "#111111",
    "--muted": "#f5f5f5",
    "--muted-foreground": "#888888",
    "--border": "#e0e0e0",
    // Tedde brand palette
    "--tedde-primary-dark": brand.theme_dark || "#222222",
    "--tedde-accent-cyan": brand.theme_accent || "#4fb9d3",
    "--tedde-nav-bg": "#ffffff",
    "--tedde-text-on-dark": "#ffffff",
    "--tedde-text-on-light": "#000000",
    "--tedde-muted": "#cccccc",
    // Legacy portal vars (used by VideoPlayer etc.)
    "--portal-accent": brand.theme_accent || "#4fb9d3",
    "--portal-dark": brand.theme_dark || "#222222",
  };

  return (
    <div style={cssVars as React.CSSProperties} className="min-h-screen">
      {children}
    </div>
  );
}
