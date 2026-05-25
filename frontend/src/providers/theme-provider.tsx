"use client";

/**
 * Avoid next-themes here: it injects a blocking script that React 19 rejects
 * during client render. Theme is toggled via document.documentElement in ThemeToggle.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
