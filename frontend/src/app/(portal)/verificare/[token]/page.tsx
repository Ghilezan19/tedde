import { serverFetch } from "@/lib/api/client";
import { QuizForm } from "./_components/QuizForm";
import { VideoPlayer } from "./_components/VideoPlayer";
import { PortalError } from "./_components/PortalError";
import { PreloadVideos } from "./_components/PreloadVideos";

interface PortalEvent {
  event_id?: string;
  recorded_at?: string;
  recorded_at_display?: string;
  recording_partial?: boolean;
  camera1_url?: string | null;
  camera2_url?: string | null;
}

interface PortalRecord {
  quiz_completed: boolean;
  license_plate?: string;
  owner_name?: string;
  mechanic_name?: string;
  event?: PortalEvent;
}

interface PortalData {
  portal: PortalRecord;
  event_meta: { recorded_at_long?: string; recorded_at_display?: string };
  portal_video_card_count: number;
  brand_name?: string;
  brand_subtitle?: string;
  logo_url?: string;
  footer_phone?: string;
  footer_email?: string;
  footer_address?: string;
  footer_hours?: string;
}

type ErrorKind = "not_found" | "expired" | "conflict" | "unknown";

async function getPortalData(token: string): Promise<{ data: PortalData } | { error: ErrorKind; message: string }> {
  try {
    const res = await serverFetch(`/api/customer-portal/record/${token}`, { cache: "no-store" });
    if (res.ok) return { data: await res.json() };
    const body = await res.json().catch(() => ({}));
    const kind = (
      body?.detail?.error || (res.status === 404 ? "not_found" : res.status === 410 ? "expired" : "unknown")
    ) as ErrorKind;
    return { error: kind, message: body?.detail?.message || "Linkul nu este valid." };
  } catch {
    return { error: "unknown", message: "Eroare la încărcarea paginii." };
  }
}

// ─── style constants (all inline — no Tailwind theme dependency) ──────────────

const S = {
  shell: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column" as const,
    background: "#f0f4f7",
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    color: "#111111",
    WebkitFontSmoothing: "antialiased",
  } as React.CSSProperties,

  // ── top bar ──
  topbar: {
    background: "var(--tedde-primary-dark, #222222)",
    borderBottom: "3px solid var(--tedde-accent-cyan, #4fb9d3)",
    padding: "14px clamp(16px, 4vw, 28px)",
  } as React.CSSProperties,
  topbarInner: {
    maxWidth: "56rem",
    margin: "0 auto",
    display: "flex",
    flexWrap: "wrap" as const,
    alignItems: "center",
    gap: "10px 16px",
  } as React.CSSProperties,
  topbarBrand: {
    fontWeight: 800,
    fontSize: "clamp(1.05rem, 2.5vw, 1.25rem)",
    letterSpacing: "0.02em",
    color: "#ffffff",
  } as React.CSSProperties,
  topbarTag: {
    fontSize: "0.8125rem",
    color: "rgba(255,255,255,.6)",
    fontWeight: 500,
  } as React.CSSProperties,

  // ── main ──
  main: {
    flex: 1,
    padding: "clamp(20px, 4vw, 36px) 0 clamp(40px, 6vw, 60px)",
  } as React.CSSProperties,
  inner: {
    width: "100%",
    maxWidth: "min(100%, 56rem)",
    margin: "0 auto",
    padding: "0 clamp(12px, 5vw, 24px)",
    display: "flex",
    flexDirection: "column" as const,
    gap: "clamp(16px, 3vw, 22px)",
    boxSizing: "border-box" as const,
  } as React.CSSProperties,

  // ── intro ──
  intro: {
    textAlign: "center" as const,
    padding: "clamp(8px, 2vw, 12px) 0 4px",
  } as React.CSSProperties,
  greeting: {
    margin: "0 0 6px",
    fontSize: "0.9375rem",
    color: "#888",
  } as React.CSSProperties,
  pageTitle: {
    margin: "0 0 14px",
    fontSize: "clamp(1.65rem, 4.5vw, 2.25rem)",
    fontWeight: 800,
    letterSpacing: "-0.02em",
    color: "#111111",
  } as React.CSSProperties,
  plateLine: {
    margin: 0,
    fontSize: "1rem",
    color: "#888",
  } as React.CSSProperties,
  plate: {
    display: "inline-block",
    marginLeft: 8,
    padding: "6px 14px",
    borderRadius: 999,
    fontFamily: "ui-monospace, 'Cascadia Code', 'SF Mono', Menlo, monospace",
    fontWeight: 700,
    fontSize: "clamp(1rem, 2.8vw, 1.2rem)",
    letterSpacing: "0.04em",
    background: "#ffffff",
    color: "#111111",
    border: "1px solid #e0e0e0",
    borderLeft: "4px solid var(--tedde-accent-cyan, #4fb9d3)",
    boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
  } as React.CSSProperties,

  // ── card ──
  card: {
    background: "#ffffff",
    border: "1px solid #e0e0e0",
    borderRadius: 14,
    boxShadow: "0 1px 3px rgba(15,30,60,.07), 0 4px 16px rgba(15,30,60,.05)",
    padding: "clamp(20px, 3.5vw, 26px)",
  } as React.CSSProperties,

  // ── info grid ──
  infoGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    gap: "clamp(16px, 3vw, 22px)",
  } as React.CSSProperties,
  infoLabel: {
    display: "block",
    fontSize: "0.6875rem",
    fontWeight: 700,
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    color: "#aaaaaa",
    marginBottom: 5,
  } as React.CSSProperties,
  infoValue: {
    display: "block",
    fontSize: "1.05rem",
    fontWeight: 600,
    color: "#111111",
  } as React.CSSProperties,

  // ── section header ──
  kicker: {
    display: "inline-block",
    marginBottom: 7,
    fontSize: "0.6875rem",
    fontWeight: 700,
    textTransform: "uppercase" as const,
    letterSpacing: "0.1em",
    color: "var(--tedde-accent-cyan, #4fb9d3)",
  } as React.CSSProperties,
  sectionTitle: {
    margin: "0 0 6px",
    fontSize: "clamp(1.15rem, 2.5vw, 1.35rem)",
    fontWeight: 700,
    color: "#111111",
  } as React.CSSProperties,
  sectionSub: {
    margin: 0,
    color: "#888888",
    fontSize: "0.9375rem",
  } as React.CSSProperties,

  // ── video ──
  videoCard: {
    margin: 0,
    display: "flex",
    flexDirection: "column" as const,
    gap: 12,
    background: "#ffffff",
    border: "1px solid #e0e0e0",
    borderRadius: 14,
    boxShadow: "0 1px 3px rgba(15,30,60,.07), 0 4px 16px rgba(15,30,60,.05)",
    padding: "clamp(18px, 3.5vw, 24px)",
    overflow: "hidden",
  } as React.CSSProperties,
  videoHeader: {
    display: "flex",
    flexWrap: "wrap" as const,
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: "6px 12px",
  } as React.CSSProperties,
  videoTitle: {
    margin: 0,
    fontSize: "clamp(0.95rem, 2.8vw, 1.1rem)",
    fontWeight: 700,
    color: "#111111",
    display: "flex",
    alignItems: "center",
    gap: 8,
  } as React.CSSProperties,
  videoTitleDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: "var(--tedde-accent-cyan, #4fb9d3)",
    flexShrink: 0,
  } as React.CSSProperties,
  videoDate: {
    color: "#aaaaaa",
    fontSize: "0.8125rem",
  } as React.CSSProperties,

  // ── footer ──
  footer: {
    marginTop: "auto",
    background: "var(--tedde-primary-dark, #222222)",
    color: "rgba(255,255,255,.85)",
    padding: "clamp(22px, 4vw, 32px) 0",
    borderTop: "1px solid rgba(255,255,255,.08)",
  } as React.CSSProperties,
  footerInner: {
    maxWidth: "56rem",
    margin: "0 auto",
    padding: "0 clamp(16px, 5vw, 28px)",
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: "clamp(18px, 3vw, 22px)",
  } as React.CSSProperties,
  footerLabel: {
    display: "block",
    fontSize: "0.6875rem",
    fontWeight: 700,
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    color: "rgba(255,255,255,.4)",
    marginBottom: 6,
  } as React.CSSProperties,
  footerValue: {
    display: "block",
    fontSize: "1rem",
    fontWeight: 600,
    color: "#f9fafb",
  } as React.CSSProperties,
  footerLink: {
    display: "inline-block",
    marginTop: 2,
    fontSize: "1rem",
    fontWeight: 600,
    color: "#ffffff",
    textDecoration: "none",
    wordBreak: "break-word" as const,
  } as React.CSSProperties,
};

// ─── page ─────────────────────────────────────────────────────────────────────

export default async function PortalPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const result = await getPortalData(token);

  if ("error" in result) {
    return <PortalError kind={result.error} message={result.message} />;
  }

  const { data } = result;
  const { portal, event_meta, logo_url, brand_name, brand_subtitle, footer_phone, footer_email, footer_address, footer_hours } = data;

  const cam1 = portal.event?.camera1_url ?? null;
  const cam2 = portal.event?.camera2_url ?? null;
  const hasVideos = !!(cam1 || cam2);
  const displayDate = event_meta?.recorded_at_display || event_meta?.recorded_at_long || "";

  return (
    <div style={S.shell}>

      {/* ── Top bar ── */}
      <header style={S.topbar}>
        <div style={S.topbarInner}>
          {logo_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logo_url}
              alt={brand_name || "Logo"}
              style={{ display: "block", height: "clamp(36px, 7vw, 52px)", width: "auto", maxWidth: "min(44vw, 200px)", objectFit: "contain", flexShrink: 0 }}
            />
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={S.topbarBrand}>{brand_name || "Service Auto"}</span>
            <span style={S.topbarTag}>{brand_subtitle || "Constatare video service"}</span>
          </div>
        </div>
      </header>

      {/* ── Main ── */}
      <main style={S.main}>
        <div style={S.inner}>

          {/* ── Intro ── */}
          <header style={S.intro}>
            {portal.owner_name && (
              <p style={S.greeting}>Bună ziua, <strong style={{ color: "#111", fontWeight: 600 }}>{portal.owner_name}</strong></p>
            )}
            <h1 style={S.pageTitle}>Constatare video</h1>
            {portal.license_plate && (
              <p style={S.plateLine}>
                Număr înmatriculare
                <span style={S.plate}>{portal.license_plate}</span>
              </p>
            )}
          </header>

          {/* ── Info card ── */}
          <section style={S.card} aria-label="Detalii constatare">
            <div style={S.infoGrid}>
              {portal.owner_name && (
                <div>
                  <span style={S.infoLabel}>Proprietar</span>
                  <strong style={S.infoValue}>{portal.owner_name}</strong>
                </div>
              )}
              {portal.mechanic_name && (
                <div>
                  <span style={S.infoLabel}>Mecanic</span>
                  <strong style={S.infoValue}>{portal.mechanic_name}</strong>
                </div>
              )}
              {event_meta?.recorded_at_long && (
                <div>
                  <span style={S.infoLabel}>Data și ora</span>
                  <strong style={S.infoValue}>{event_meta.recorded_at_long}</strong>
                </div>
              )}
            </div>
          </section>

          {/* ── Preload videos silently while quiz is active ── */}
          {!portal.quiz_completed && hasVideos && <PreloadVideos cam1={cam1} cam2={cam2} />}

          {portal.quiz_completed ? (
            <>
              {/* ── Success notice ── */}
              <section style={S.card}>
                <span style={S.kicker}>Feedback salvat</span>
                <h2 style={S.sectionTitle}>Constatarea video este disponibilă</h2>
                <p style={S.sectionSub}>Puteți viziona mai jos înregistrările video ale constatării.</p>
              </section>

              {/* ── Videos — stacked ── */}
              {hasVideos ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "clamp(18px, 4vw, 28px)" }}>
                  {cam1 && (
                    <figure style={S.videoCard}>
                      <figcaption style={S.videoHeader}>
                        <h3 style={S.videoTitle}>
                          <span style={S.videoTitleDot} />
                          Dedesubt
                        </h3>
                        {displayDate && <span style={S.videoDate}>{displayDate}</span>}
                      </figcaption>
                      <VideoPlayer src={cam1} label="Camera 1 — Dedesubt" />
                    </figure>
                  )}
                  {cam2 && (
                    <figure style={S.videoCard}>
                      <figcaption style={S.videoHeader}>
                        <h3 style={S.videoTitle}>
                          <span style={S.videoTitleDot} />
                          Frontal
                        </h3>
                        {displayDate && <span style={S.videoDate}>{displayDate}</span>}
                      </figcaption>
                      <VideoPlayer src={cam2} label="Camera 2 — Frontal" />
                    </figure>
                  )}
                </div>
              ) : (
                <div style={{ ...S.card, textAlign: "center", padding: "clamp(28px,5vw,40px)", color: "#888" }}>
                  Înregistrările video nu sunt disponibile momentan.
                </div>
              )}

              {portal.event?.recording_partial && (
                <div style={{ padding: "12px 16px", borderRadius: 10, background: "#fffbeb", border: "1px solid #fde68a", color: "#92400e", fontSize: "0.875rem" }}>
                  ⚠️ Înregistrarea este parțială — este posibil ca o cameră să nu fi funcționat la momentul constatării.
                </div>
              )}
            </>
          ) : (
            /* ── Quiz ── */
            <QuizForm token={token} />
          )}

        </div>
      </main>

      {/* ── Footer ── */}
      {(footer_phone || footer_email || footer_address || footer_hours) && (
        <footer style={S.footer}>
          <div style={S.footerInner}>
            {footer_address && (
              <div>
                <span style={S.footerLabel}>Adresă</span>
                <strong style={S.footerValue}>{footer_address}</strong>
              </div>
            )}
            {footer_phone && (
              <div>
                <span style={S.footerLabel}>Telefon</span>
                <a
                  href={`tel:${footer_phone.replace(/[\s\-]/g, "")}`}
                  style={S.footerLink}
                >
                  {footer_phone}
                </a>
              </div>
            )}
            {footer_email && (
              <div>
                <span style={S.footerLabel}>Email</span>
                <a href={`mailto:${footer_email.trim()}`} style={S.footerLink}>{footer_email}</a>
              </div>
            )}
            {footer_hours && (
              <div>
                <span style={S.footerLabel}>Program</span>
                <strong style={S.footerValue}>{footer_hours}</strong>
              </div>
            )}
          </div>
        </footer>
      )}

    </div>
  );
}
