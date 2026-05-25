import { requireSuperAdmin } from "@/lib/auth/require";
import {
  getSuperAdminTokens,
  getTokenHistory,
  getHealth,
  getEventsByDay,
  getCleanupConfig,
  getCleanupLog,
} from "@/lib/api/superadmin";
import { TokensSection } from "./_components/TokensSection";
import { HealthSection } from "./_components/HealthSection";
import { EventsByDaySection } from "./_components/EventsByDaySection";
import { CleanupSection } from "./_components/CleanupSection";

export const metadata = { title: "Super-Admin — Tedde Auto" };

export default async function SuperAdminPage() {
  await requireSuperAdmin();

  const [tokens, history, health, eventsByDay, cleanupConfig, cleanupLog] =
    await Promise.allSettled([
      getSuperAdminTokens(),
      getTokenHistory(100),
      getHealth(),
      getEventsByDay(),
      getCleanupConfig(),
      getCleanupLog(),
    ]);

  return (
    <div className="mx-auto max-w-screen-xl px-4 sm:px-6 py-8 space-y-10">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Super-Admin</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Gestionare sistem, tokeni și configurare avansată
        </p>
      </div>

      <TokensSection
        tokens={tokens.status === "fulfilled" ? tokens.value : null}
        history={history.status === "fulfilled" ? history.value : []}
      />

      <HealthSection
        health={health.status === "fulfilled" ? health.value : null}
      />

      <EventsByDaySection
        data={eventsByDay.status === "fulfilled" ? eventsByDay.value : null}
      />

      <CleanupSection
        config={cleanupConfig.status === "fulfilled" ? cleanupConfig.value : null}
        log={cleanupLog.status === "fulfilled" ? cleanupLog.value : ""}
      />
    </div>
  );
}
