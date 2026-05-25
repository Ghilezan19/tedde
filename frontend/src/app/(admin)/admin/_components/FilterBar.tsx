"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const FILTERS = [
  { value: "all", label: "Toate" },
  { value: "sms_pending", label: "SMS netrimis" },
  { value: "sms_sent", label: "SMS trimis" },
  { value: "feedback", label: "Cu feedback" },
  { value: "no_feedback", label: "Fără feedback" },
];

const DAYS_OPTIONS = [
  { value: "1", label: "Azi" },
  { value: "7", label: "7 zile" },
  { value: "30", label: "30 zile" },
  { value: "90", label: "90 zile" },
];

interface FilterBarProps {
  currentFilter: string;
  currentDays: number;
  currentSearch: string;
  onFilterChange: (filter: string) => void;
  onDaysChange: (days: number) => void;
  onSearchChange: (search: string) => void;
}

export function FilterBar({
  currentFilter,
  currentDays,
  currentSearch,
  onFilterChange,
  onDaysChange,
  onSearchChange,
}: FilterBarProps) {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearch = (value: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onSearchChange(value), 350);
  };

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:flex-wrap">
      {/* Filter buttons */}
      <div className="flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={currentFilter === f.value ? "default" : "outline"}
            size="sm"
            onClick={() => onFilterChange(f.value)}
            className="h-8 text-xs"
          >
            {f.label}
          </Button>
        ))}
      </div>

      <div className="flex items-center gap-2 sm:ml-auto">
        {/* Days select */}
        <Select value={String(currentDays)} onValueChange={(v) => onDaysChange(Number(v))}>
          <SelectTrigger className="h-8 w-28 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DAYS_OPTIONS.map((d) => (
              <SelectItem key={d.value} value={d.value} className="text-xs">
                {d.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Caută plăcuță, proprietar..."
            defaultValue={currentSearch}
            onChange={(e) => handleSearch(e.target.value)}
            className="h-8 w-48 rounded-md border border-input bg-background pl-8 pr-3 text-xs shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
      </div>
    </div>
  );
}
