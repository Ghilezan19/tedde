type ErrorKind = "not_found" | "expired" | "conflict" | "unknown";

const ERROR_CONFIG: Record<ErrorKind, { emoji: string; title: string; description: string }> = {
  not_found: {
    emoji: "🔍",
    title: "Link invalid",
    description: "Linkul pe care l-ați accesat nu există sau a fost deja utilizat. Verificați dacă l-ați primit corect.",
  },
  expired: {
    emoji: "⏱",
    title: "Link expirat",
    description: "Linkul de acces a expirat. Contactați service-ul pentru a solicita un nou link de vizionare.",
  },
  conflict: {
    emoji: "🔒",
    title: "Acces restricționat",
    description: "Linkul a fost deja utilizat sau există o restricție de acces. Contactați service-ul pentru ajutor.",
  },
  unknown: {
    emoji: "⚠️",
    title: "Eroare neașteptată",
    description: "A apărut o problemă la încărcarea paginii. Vă rugăm să încercați din nou.",
  },
};

export function PortalError({ kind, message }: { kind: ErrorKind; message: string }) {
  const config = ERROR_CONFIG[kind] || ERROR_CONFIG.unknown;

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: "#f0f4f7", padding: "24px 16px" }}>
      <div style={{ maxWidth: 440, width: "100%" }}>
        {/* Top accent bar */}
        <div style={{ height: 4, borderRadius: "4px 4px 0 0", background: "var(--tedde-accent-cyan, #4fb9d3)" }} />
        <div style={{
          background: "#ffffff",
          borderRadius: "0 0 14px 14px",
          border: "1px solid #e0e0e0",
          borderTop: "none",
          boxShadow: "0 4px 24px rgba(0,0,0,0.07)",
          padding: "clamp(28px, 5vw, 40px)",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 16 }}>{config.emoji}</div>
          <h1 style={{ margin: "0 0 10px", fontSize: "1.4rem", fontWeight: 800, color: "#111" }}>{config.title}</h1>
          <p style={{ margin: "0 0 24px", color: "#666", fontSize: "0.9375rem", lineHeight: 1.6 }}>
            {message || config.description}
          </p>
          <div style={{
            background: "#f8fafb",
            border: "1px solid #e8eaed",
            borderRadius: 10,
            padding: "14px 18px",
            textAlign: "left",
          }}>
            <p style={{ margin: 0, fontSize: "0.875rem", color: "#555" }}>
              <strong style={{ color: "#111" }}>Aveți nevoie de ajutor?</strong>{" "}
              Contactați service-ul auto pentru a solicita un nou link de acces sau pentru orice altă problemă.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
