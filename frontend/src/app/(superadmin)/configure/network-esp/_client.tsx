"use client";

import { useState } from "react";
import { Search, Zap, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";
import { SaveBar } from "../_components/SaveBar";

interface Props { config: Record<string, string>; }

interface ScanHost {
  ip: string;
  port: number;
  kind?: string;
  status?: number;
  title?: string;
  latency_ms?: number;
}

interface HeartbeatData {
  temp_c?: number;
  fan_on?: boolean;
  wifi_ssid?: string;
  countdown_seconds?: number;
  state?: string;
  fw?: string;
  uptime_s?: number;
  rssi?: number;
  received_at?: string;
  source_ip?: string;
}

export function NetworkEspClient({ config }: Props) {
  const [values, setValues] = useState({ ...config });
  const set = (key: string) => (v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  const [scanning, setScanning] = useState(false);
  const [scanResults, setScanResults] = useState<ScanHost[]>([]);
  const [scanDuration, setScanDuration] = useState<number | null>(null);

  const [reachResult, setReachResult] = useState<string | null>(null);
  const [reachLoading, setReachLoading] = useState(false);

  const [heartbeat, setHeartbeat] = useState<HeartbeatData | null>(null);
  const [heartbeatLoading, setHeartbeatLoading] = useState(false);

  const runScan = async () => {
    setScanning(true);
    setScanResults([]);
    try {
      const params = new URLSearchParams({ port: "80", timeout: "0.4", fingerprint: "true" });
      const subnet = values.SCAN_SUBNET;
      if (subnet) params.set("subnet", subnet);
      const res = await fetch(`/api/net/scan?${params}`, { credentials: "include" });
      const data = await res.json();
      setScanResults(data.hosts || []);
      setScanDuration(data.duration_ms);
    } catch {
      setScanResults([]);
    } finally {
      setScanning(false);
    }
  };

  const testReach = async () => {
    const ip = values.ESP_DEVICE_IP;
    if (!ip) return;
    setReachLoading(true);
    setReachResult(null);
    try {
      const res = await fetch(`/api/net/reach?host=${ip}&port=80&timeout=2`, { credentials: "include" });
      const data = await res.json();
      setReachResult(data.open ? `✓ Accesibil (${data.latency_ms?.toFixed(1)}ms)` : "✗ Inaccesibil");
    } catch {
      setReachResult("Eroare la testare");
    } finally {
      setReachLoading(false);
    }
  };

  const loadHeartbeat = async () => {
    setHeartbeatLoading(true);
    try {
      const res = await fetch("/api/esp/heartbeat", { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        setHeartbeat(data);
      }
    } catch {}
    setHeartbeatLoading(false);
  };

  const adoptIp = (ip: string) => {
    set("ESP_DEVICE_IP")(ip);
  };

  const kindBadge = (kind?: string) => {
    if (kind === "esp") return <StatusPill variant="success" label="ESP" />;
    if (kind === "camera") return <StatusPill variant="info" label="Cameră" />;
    if (kind === "router") return <StatusPill variant="warning" label="Router" />;
    if (kind === "server") return <StatusPill variant="idle" label="Server" />;
    return <StatusPill variant="idle" label="Unknown" />;
  };

  return (
    <div className="space-y-8 pb-20">
      <div>
        <h1 className="text-xl font-bold">Rețea & ESP</h1>
        <p className="text-sm text-muted-foreground mt-1">Status ESP, scanner rețea și setări conexiune</p>
      </div>

      {/* ESP Heartbeat */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">🔌 Heartbeat ESP</h2>
          <Button variant="outline" size="sm" onClick={loadHeartbeat} disabled={heartbeatLoading} className="gap-1.5 h-8">
            <RefreshCw className={`h-3.5 w-3.5 ${heartbeatLoading ? "animate-spin" : ""}`} />
            Reîmprospătează
          </Button>
        </div>
        {heartbeat ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-sm">
            {[
              { label: "Stare", value: heartbeat.state },
              { label: "Temperatură", value: heartbeat.temp_c != null ? `${heartbeat.temp_c}°C` : "—" },
              { label: "Ventilator", value: heartbeat.fan_on ? "ON" : "OFF" },
              { label: "WiFi SSID", value: heartbeat.wifi_ssid },
              { label: "Countdown", value: heartbeat.countdown_seconds != null ? `${heartbeat.countdown_seconds}s` : "—" },
              { label: "Firmware", value: heartbeat.fw },
              { label: "Uptime", value: heartbeat.uptime_s != null ? `${Math.floor(heartbeat.uptime_s / 60)}min` : "—" },
              { label: "RSSI", value: heartbeat.rssi != null ? `${heartbeat.rssi} dBm` : "—" },
            ].map(({ label, value }) => (
              <div key={label}>
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="font-medium font-mono text-sm">{value || "—"}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Apasă "Reîmprospătează" pentru a vedea ultimul heartbeat.</p>
        )}
      </section>

      {/* ESP settings */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">⚙ Setări ESP</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">IP ESP Device</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={values.ESP_DEVICE_IP || ""}
                onChange={(e) => set("ESP_DEVICE_IP")(e.target.value)}
                className="flex-1 h-9 rounded-md border border-input bg-background px-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="192.168.1.100"
              />
              <Button variant="outline" size="sm" onClick={testReach} disabled={reachLoading || !values.ESP_DEVICE_IP} className="h-9 shrink-0 text-xs">
                {reachLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                Test
              </Button>
            </div>
            {reachResult && <p className="text-xs font-mono">{reachResult}</p>}
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Notă ajutor ESP</label>
            <input
              type="text"
              value={values.ESP_HELP_NOTE || ""}
              onChange={(e) => set("ESP_HELP_NOTE")(e.target.value)}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="ex. Intrare principală"
            />
          </div>
        </div>
        <a href="/help-esp1" target="_blank" rel="noopener noreferrer"
          className="text-xs text-primary hover:underline">
          Deschide pagina ajutor ESP →
        </a>
      </section>

      {/* Network Scanner */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">🌐 Scanner Rețea</h2>
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={values.SCAN_SUBNET || ""}
            onChange={(e) => set("SCAN_SUBNET")(e.target.value)}
            placeholder="auto-detect /24"
            className="h-9 w-40 rounded-md border border-input bg-background px-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <Button onClick={runScan} disabled={scanning} className="gap-1.5">
            {scanning ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {scanning ? "Se scanează..." : "Scanează (254 IP-uri)"}
          </Button>
          {scanDuration != null && !scanning && (
            <span className="text-xs text-muted-foreground">{scanDuration}ms</span>
          )}
        </div>

        {scanResults.length > 0 && (
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">IP</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Tip</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Port</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Latență</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Acțiuni</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {scanResults.map((host) => (
                  <tr key={host.ip} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-2.5 font-mono text-sm">{host.ip}</td>
                    <td className="px-4 py-2.5">{kindBadge(host.kind)}</td>
                    <td className="px-4 py-2.5 text-muted-foreground font-mono text-xs">{host.port}</td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">
                      {host.latency_ms != null ? `${host.latency_ms.toFixed(1)}ms` : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      {(host.kind === "esp" || host.kind === "unknown") && (
                        <button
                          onClick={() => adoptIp(host.ip)}
                          className="text-xs text-primary hover:underline"
                        >
                          Adoptă ca ESP
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <SaveBar getValues={() => values} />
    </div>
  );
}
