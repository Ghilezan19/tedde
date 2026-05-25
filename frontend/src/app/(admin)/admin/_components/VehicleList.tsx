"use client";

import { useState, useTransition } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Loader2, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FilterBar } from "./FilterBar";
import { VehicleCard } from "./VehicleCard";
import type { VehiclesResponse } from "@/lib/api/admin";

interface VehicleListProps {
  initialData: VehiclesResponse | null;
  initialFilter: string;
  initialDays: number;
  initialSearch: string;
  initialPage: number;
}

export function VehicleList({
  initialData,
  initialFilter,
  initialDays,
  initialSearch,
  initialPage,
}: VehicleListProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  const [filter, setFilter] = useState(initialFilter);
  const [days, setDays] = useState(initialDays);
  const [search, setSearch] = useState(initialSearch);
  const [page, setPage] = useState(initialPage);
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());

  const data = initialData;

  const navigate = (newParams: Partial<{ filter: string; days: number; search: string; page: number }>) => {
    const merged = { filter, days, search, page, ...newParams };
    const params = new URLSearchParams();
    if (merged.filter !== "all") params.set("filter", merged.filter);
    if (merged.days !== 7) params.set("days", String(merged.days));
    if (merged.search) params.set("search", merged.search);
    if (merged.page > 1) params.set("page", String(merged.page));

    startTransition(() => {
      router.push(`${pathname}?${params}`);
    });
  };

  const handleFilterChange = (f: string) => {
    setFilter(f);
    setPage(1);
    navigate({ filter: f, page: 1 });
  };

  const handleDaysChange = (d: number) => {
    setDays(d);
    setPage(1);
    navigate({ days: d, page: 1 });
  };

  const handleSearchChange = (s: string) => {
    setSearch(s);
    setPage(1);
    navigate({ search: s, page: 1 });
  };

  const handlePageChange = (p: number) => {
    setPage(p);
    navigate({ page: p });
  };

  const vehicles = (data?.vehicles || []).filter((v) => !deletedIds.has(v.event_id));
  const totalPages = data?.pages || 1;
  const total = data?.total || 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
          Vehicule
        </h2>
        {total > 0 && (
          <span className="text-xs text-muted-foreground">
            {total} {total === 1 ? "rezultat" : "rezultate"}
          </span>
        )}
      </div>

      <FilterBar
        currentFilter={filter}
        currentDays={days}
        currentSearch={search}
        onFilterChange={handleFilterChange}
        onDaysChange={handleDaysChange}
        onSearchChange={handleSearchChange}
      />

      {/* Loading overlay */}
      {isPending && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Vehicle cards */}
      {!isPending && vehicles.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-4">
            <span className="text-2xl">🚗</span>
          </div>
          <p className="text-sm font-medium text-muted-foreground">Niciun vehicul găsit</p>
          <p className="text-xs text-muted-foreground/70 mt-1">
            Încearcă să schimbi filtrele sau perioada
          </p>
        </div>
      )}

      {!isPending && (
        <div className="space-y-2">
          {vehicles.map((v) => (
            <VehicleCard
              key={v.event_id}
              vehicle={v}
              onDeleted={(id) => setDeletedIds((prev) => new Set(prev).add(id))}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && !isPending && (
        <div className="flex items-center justify-between pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handlePageChange(page - 1)}
            disabled={page <= 1}
            className="h-8 gap-1.5 text-xs"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Anterior
          </Button>

          <span className="text-xs text-muted-foreground">
            Pagina {page} din {totalPages}
          </span>

          <Button
            variant="outline"
            size="sm"
            onClick={() => handlePageChange(page + 1)}
            disabled={page >= totalPages}
            className="h-8 gap-1.5 text-xs"
          >
            Următor
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}
