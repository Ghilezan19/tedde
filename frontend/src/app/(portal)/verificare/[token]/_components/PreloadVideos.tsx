"use client";

import { useEffect } from "react";

interface Props {
  cam1: string | null;
  cam2: string | null;
}

export function PreloadVideos({ cam1, cam2 }: Props) {
  useEffect(() => {
    [cam1, cam2].filter(Boolean).forEach((url) => {
      try {
        fetch(url!, { credentials: "same-origin", cache: "force-cache" }).catch(() => {});
      } catch {}
    });
  }, [cam1, cam2]);

  return (
    <div aria-hidden="true" style={{ position: "absolute", left: "-9999px", top: "-9999px", width: 1, height: 1, overflow: "hidden" }}>
      {cam1 && <video preload="auto" muted src={cam1} />}
      {cam2 && <video preload="auto" muted src={cam2} />}
    </div>
  );
}
