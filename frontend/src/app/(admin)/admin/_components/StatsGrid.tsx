import { Car, MessageSquare, Star, Coins, ThumbsUp } from "lucide-react";
import { StatBox } from "@/components/StatBox";
import type { AdminStats } from "@/lib/api/admin";

interface StatsGridProps {
  stats: AdminStats | null;
}

export function StatsGrid({ stats }: StatsGridProps) {
  const avgRating = stats?.avg_rating != null ? stats.avg_rating.toFixed(1) : "—";

  return (
    <div>
      <h2 className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground mb-4">
        Sumar — azi
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatBox
          label="Vehicule azi"
          value={stats?.today_events ?? "—"}
          icon={<Car className="h-4 w-4" />}
        />
        <StatBox
          label="SMS trimise"
          value={stats?.sms_sent_today ?? "—"}
          icon={<MessageSquare className="h-4 w-4" />}
        />
        <StatBox
          label="Feedback primit"
          value={stats?.feedback_today ?? "—"}
          icon={<ThumbsUp className="h-4 w-4" />}
        />
        <StatBox
          label="Rating mediu"
          value={avgRating}
          subtitle={stats?.avg_rating != null ? "din 5 stele" : undefined}
          icon={<Star className="h-4 w-4" />}
        />
        <StatBox
          label="Tokeni rămași"
          value={stats?.tokens_remaining ?? "—"}
          icon={<Coins className="h-4 w-4" />}
        />
      </div>
    </div>
  );
}
