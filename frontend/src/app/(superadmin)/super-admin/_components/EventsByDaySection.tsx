"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { PlateBadge } from "@/components/PlateBadge";
import { StatusPill } from "@/components/StatusPill";
import type { EventsByDay } from "@/lib/api/superadmin";

interface EventsByDaySectionProps {
  data: EventsByDay | null;
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

export function EventsByDaySection({ data }: EventsByDaySectionProps) {
  const days = data?.days || [];
  const [openDays, setOpenDays] = useState<Set<string>>(new Set(days[0] ? [days[0].date] : []));

  const toggleDay = (date: string) => {
    setOpenDays((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      return next;
    });
  };

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
        🎞 Videouri salvate — per zi
      </h2>

      {days.length === 0 ? (
        <div className="rounded-xl border bg-card p-8 text-center">
          <p className="text-sm text-muted-foreground">Nicio înregistrare găsită.</p>
        </div>
      ) : (
        <div className="rounded-xl border bg-card overflow-hidden divide-y">
          {days.map((day) => (
            <div key={day.date}>
              <button
                onClick={() => toggleDay(day.date)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
              >
                <span className="font-medium text-sm">{day.date}</span>
                <span className="text-xs text-muted-foreground">
                  {day.events.length} {day.events.length === 1 ? "eveniment" : "evenimente"}
                </span>
                <ChevronDown
                  className={`h-4 w-4 text-muted-foreground ml-auto transition-transform ${openDays.has(day.date) ? "rotate-180" : ""}`}
                />
              </button>

              {openDays.has(day.date) && (
                <div className="border-t divide-y bg-muted/10">
                  {day.events.map((ev) => (
                    <div key={ev.event_id} className="flex items-center gap-3 px-6 py-2.5 text-sm">
                      <PlateBadge plate={ev.license_plate} size="sm" />
                      <span className="text-xs text-muted-foreground font-mono">
                        {formatTime(ev.recorded_at)}
                      </span>
                      <div className="ml-auto flex items-center gap-2">
                        {ev.sms_status && (
                          <StatusPill
                            variant={ev.sms_status === "sent" ? "success" : ev.sms_status === "failed" ? "error" : "idle"}
                            label={ev.sms_status === "sent" ? "SMS ✓" : "SMS"}
                          />
                        )}
                        <StatusPill
                          variant={ev.has_feedback ? "success" : "idle"}
                          label={ev.has_feedback ? "Feedback ✓" : "—"}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
