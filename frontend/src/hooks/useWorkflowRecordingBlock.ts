"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 4000;

interface WorkflowStatusResponse {
  active?: boolean;
  last_event?: {
    recording?: boolean;
    cameras?: number[];
    elapsedSeconds?: number;
    durationSeconds?: number;
  } | null;
}

/** True while workflow is actively recording this camera (blocks redundant RTSP /api/stream). */
export function useWorkflowRecordingBlock(camera: 1 | 2): {
  blocked: boolean;
  elapsedSec: number | null;
  durationSec: number | null;
} {
  const [blocked, setBlocked] = useState(false);
  const [elapsedSec, setElapsedSec] = useState<number | null>(null);
  const [durationSec, setDurationSec] = useState<number | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/workflow/status", { credentials: "include" });
      if (!res.ok) return;
      const data = (await res.json()) as WorkflowStatusResponse;
      const le = data.last_event ?? null;
      const cameras = Array.isArray(le?.cameras) ? le.cameras : [];
      const isBlocked = !!data.active && cameras.includes(camera);
      const el = typeof le?.elapsedSeconds === "number" ? le.elapsedSeconds : null;
      const dur = typeof le?.durationSeconds === "number" ? le.durationSeconds : null;
      if (mounted.current) {
        setBlocked(isBlocked);
        setElapsedSec(isBlocked ? el : null);
        setDurationSec(isBlocked ? dur : null);
      }
    } catch {
      if (mounted.current) {
        setBlocked(false);
        setElapsedSec(null);
        setDurationSec(null);
      }
    }
  }, [camera]);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, POLL_MS);
    return () => clearInterval(id);
  }, [fetchStatus]);

  return { blocked, elapsedSec, durationSec };
}
