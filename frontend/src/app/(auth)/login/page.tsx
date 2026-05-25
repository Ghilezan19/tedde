import { getSession } from "@/lib/auth/session";
import { Camera } from "lucide-react";
import { redirect } from "next/navigation";
import { PasswordInput } from "./_password-input";

interface LoginPageProps {
  searchParams: Promise<{ next?: string; error?: string }>;
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const session = await getSession();
  if (session) {
    redirect(session.role === "superadmin" ? "/super-admin" : "/admin");
  }

  const params = await searchParams;
  const nextUrl = params.next || "/admin";
  const err = params.error;
  const errorMessage =
    err === "bad_password"
      ? "Parolă incorectă. Încearcă din nou."
      : err === "backend"
        ? "Nu s-a putut contacta serverul (FastAPI). Pornește backend-ul pe portul 8000."
        : err
          ? "A apărut o problemă la autentificare."
          : null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 px-4">
      <div className="w-full max-w-sm">
        {/* Brand header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-primary/10 mb-4">
            <Camera className="h-7 w-7 text-primary" />
          </div>
          <h1 className="text-2xl font-bold text-foreground">Tedde Auto</h1>
          <p className="text-sm text-muted-foreground mt-1">Panou de administrare</p>
        </div>

        {/* Card */}
        <div className="rounded-xl border bg-card shadow-sm p-6">
          {errorMessage && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-400">
              {errorMessage}
            </div>
          )}

          <form method="POST" action="/login-submit" className="space-y-4">
            <input type="hidden" name="next" value={nextUrl} />

            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="text-sm font-medium text-foreground"
              >
                Parolă
              </label>
              <PasswordInput />
            </div>

            <button
              type="submit"
              className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 transition-colors"
            >
              Intră în cont
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Tedde Auto Camera System
        </p>
      </div>
    </div>
  );
}
