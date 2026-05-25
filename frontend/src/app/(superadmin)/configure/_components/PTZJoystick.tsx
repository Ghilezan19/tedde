"use client";

import { useState, useCallback } from "react";
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Square, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";

const DIRECTIONS = [
  { dir: "up-left", label: "", icon: null, row: 1, col: 1 },
  { dir: "up", label: "↑", icon: ArrowUp, row: 1, col: 2 },
  { dir: "up-right", label: "", icon: null, row: 1, col: 3 },
  { dir: "left", label: "←", icon: ArrowLeft, row: 2, col: 1 },
  { dir: "stop", label: "■", icon: Square, row: 2, col: 2 },
  { dir: "right", label: "→", icon: ArrowRight, row: 2, col: 3 },
  { dir: "down-left", label: "", icon: null, row: 3, col: 1 },
  { dir: "down", label: "↓", icon: ArrowDown, row: 3, col: 2 },
  { dir: "down-right", label: "", icon: null, row: 3, col: 3 },
] as const;

export function PTZJoystick() {
  const [speed, setSpeed] = useState(4);
  const [presets, setPresets] = useState<Array<{ token: string; name: string }>>([]);
  const [presetsLoaded, setPresetsLoaded] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [saving, setSaving] = useState(false);

  const move = useCallback(async (direction: string) => {
    if (direction === "stop") {
      await fetch("/api/ptz/stop", { method: "POST", credentials: "include" });
    } else {
      await fetch("/api/ptz/move", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction, speed }),
      });
    }
  }, [speed]);

  const stopMove = useCallback(async () => {
    await fetch("/api/ptz/stop", { method: "POST", credentials: "include" });
  }, []);

  const zoom = async (direction: "in" | "out") => {
    await fetch("/api/ptz/zoom", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction }),
    });
  };

  const loadPresets = async () => {
    const res = await fetch("/api/ptz/presets", { credentials: "include" });
    if (res.ok) {
      const data = await res.json();
      setPresets(data.presets || []);
    }
    setPresetsLoaded(true);
  };

  const gotoPreset = async (token: string) => {
    await fetch("/api/ptz/goto", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
  };

  const savePreset = async () => {
    if (!presetName.trim()) return;
    setSaving(true);
    const res = await fetch("/api/ptz/presets", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: presetName }),
    });
    if (res.ok) {
      setPresetName("");
      loadPresets();
    }
    setSaving(false);
  };

  const deletePreset = async (token: string) => {
    await fetch(`/api/ptz/presets/${token}`, { method: "DELETE", credentials: "include" });
    setPresets((prev) => prev.filter((p) => p.token !== token));
  };

  return (
    <div className="space-y-4 min-w-0 lg:w-72">
      {/* 3x3 Joystick grid */}
      <div className="grid grid-cols-3 gap-1 w-36 mx-auto lg:mx-0">
        {DIRECTIONS.map(({ dir, icon: Icon }) => (
          <button
            key={dir}
            className={`h-11 w-11 rounded-md border flex items-center justify-center transition-colors ${
              dir === "stop"
                ? "bg-muted hover:bg-muted/70 text-foreground"
                : Icon
                ? "bg-card hover:bg-muted border-border text-foreground cursor-pointer"
                : "invisible"
            }`}
            onPointerDown={() => Icon && move(dir)}
            onPointerUp={stopMove}
            onPointerLeave={stopMove}
            disabled={!Icon}
          >
            {Icon && <Icon className="h-4 w-4" />}
          </button>
        ))}
      </div>

      {/* Zoom */}
      <div className="flex items-center gap-2">
        <button
          className="h-9 w-9 rounded-md border flex items-center justify-center hover:bg-muted transition-colors"
          onPointerDown={() => zoom("out")}
          onPointerUp={stopMove}
          onPointerLeave={stopMove}
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <span className="text-xs text-muted-foreground">Zoom</span>
        <button
          className="h-9 w-9 rounded-md border flex items-center justify-center hover:bg-muted transition-colors"
          onPointerDown={() => zoom("in")}
          onPointerUp={stopMove}
          onPointerLeave={stopMove}
        >
          <ZoomIn className="h-4 w-4" />
        </button>
      </div>

      {/* Speed */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-muted-foreground shrink-0">Viteză: {speed}</label>
        <input
          type="range"
          min={1}
          max={7}
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          className="w-full"
        />
      </div>

      {/* Presets */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium">Preseturi PTZ</p>
          <button onClick={loadPresets} className="text-xs text-primary hover:underline">
            Încarcă
          </button>
        </div>

        {presetsLoaded && (
          <>
            <div className="space-y-1 max-h-36 overflow-y-auto">
              {presets.length === 0 && (
                <p className="text-xs text-muted-foreground">Niciun preset salvat.</p>
              )}
              {presets.map((p) => (
                <div key={p.token} className="flex items-center gap-2 text-xs">
                  <span className="font-mono bg-muted px-1.5 py-0.5 rounded text-xs shrink-0">{p.token.slice(0, 8)}</span>
                  <span className="flex-1 truncate">{p.name}</span>
                  <button onClick={() => gotoPreset(p.token)} className="text-primary hover:underline shrink-0">Goto</button>
                  <button onClick={() => deletePreset(p.token)} className="text-red-500 hover:underline shrink-0">✕</button>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <input
                type="text"
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
                placeholder="Nume preset"
                className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <Button size="sm" onClick={savePreset} disabled={saving || !presetName} className="h-8 text-xs shrink-0">
                Salvează
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
