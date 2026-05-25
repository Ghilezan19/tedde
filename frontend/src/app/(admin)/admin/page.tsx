import { requireAdmin } from "@/lib/auth/require";
import { getAdminStats, getVehicles } from "@/lib/api/admin";
import { StatsGrid } from "./_components/StatsGrid";
import { VehicleList } from "./_components/VehicleList";
import { AdminLiveSection } from "./_components/AdminLiveSection";

export const metadata = { title: "Admin — Tedde Auto" };

export default async function AdminPage({
  searchParams,
}: {
  searchParams: Promise<{ filter?: string; days?: string; search?: string; page?: string }>;
}) {
  await requireAdmin();

  const params = await searchParams;
  const filter = params.filter || "all";
  const days = Number(params.days) || 7;
  const search = params.search || "";
  const page = Number(params.page) || 1;

  const [stats, vehiclesData] = await Promise.all([
    getAdminStats().catch(() => null),
    getVehicles({ filter, days, search, page, page_size: 25 }).catch(() => null),
  ]);

  return (
    <div className="mx-auto max-w-screen-xl px-4 sm:px-6 py-8 space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Dashboard Admin</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Monitorizare zilnică și gestionare vehicule
        </p>
      </div>

      {/* Stats */}
      <StatsGrid stats={stats} />

      {/* Vehicles */}
      <VehicleList
        initialData={vehiclesData}
        initialFilter={filter}
        initialDays={days}
        initialSearch={search}
        initialPage={page}
      />

      {/* Live cameras */}
      <AdminLiveSection />
    </div>
  );
}
