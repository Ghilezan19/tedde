"use client";

import { useState, useTransition } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { submitQuiz } from "../actions";

const RATING_OPTIONS: [number, string][] = [
  [5, "Foarte satisfăcut"],
  [4, "Satisfăcut"],
  [3, "Acceptabil"],
  [2, "Nesatisfăcut"],
  [1, "Foarte nesatisfăcut"],
];

const S = {
  card: {
    background: "#ffffff",
    border: "1px solid #e0e0e0",
    borderRadius: 14,
    boxShadow: "0 1px 3px rgba(15,30,60,.07), 0 4px 16px rgba(15,30,60,.05)",
    padding: "clamp(20px, 3.5vw, 28px)",
  } as React.CSSProperties,
  kicker: {
    display: "inline-block",
    marginBottom: 8,
    fontSize: "0.6875rem",
    fontWeight: 700,
    textTransform: "uppercase" as const,
    letterSpacing: "0.1em",
    color: "var(--tedde-accent-cyan, #4fb9d3)",
  } as React.CSSProperties,
  label: {
    display: "block",
    fontSize: "0.6875rem",
    fontWeight: 700,
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    color: "#888888",
    marginBottom: 6,
  } as React.CSSProperties,
};

function RadioGroup({
  name,
  value,
  onChange,
}: {
  name: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {RATING_OPTIONS.map(([val, lbl]) => (
        <label
          key={val}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            minHeight: 46,
            padding: "10px 14px",
            border: `1px solid ${value === val ? "var(--tedde-accent-cyan, #4fb9d3)" : "#e0e0e0"}`,
            borderRadius: 10,
            background: value === val ? "rgba(79,185,211,0.06)" : "#f8fafb",
            cursor: "pointer",
            transition: "border-color .15s, background .15s",
          }}
        >
          <input
            type="radio"
            name={name}
            value={val}
            checked={value === val}
            onChange={() => onChange(val)}
            style={{ width: 18, height: 18, flexShrink: 0, accentColor: "var(--tedde-accent-cyan, #4fb9d3)" }}
          />
          <span style={{ fontSize: "0.9375rem", fontWeight: value === val ? 600 : 400, color: "#111111" }}>
            {val} — {lbl}
          </span>
        </label>
      ))}
    </div>
  );
}

export function QuizForm({ token }: { token: string }) {
  const [ratingOverall, setRatingOverall] = useState(0);
  const [ratingExplanation, setRatingExplanation] = useState(0);
  const [freeText, setFreeText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [isPending, startTransition] = useTransition();

  const canSubmit = ratingOverall > 0 && ratingExplanation > 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    startTransition(async () => {
      const result = await submitQuiz(token, ratingOverall, ratingExplanation, freeText);
      if (result.ok) setSubmitted(true);
      else setError(result.error || "Eroare necunoscută.");
    });
  };

  if (submitted) {
    return (
      <div
        style={{
          ...S.card,
          textAlign: "center",
          background: "#f0fdf4",
          border: "1px solid #bbf7d0",
          padding: "clamp(28px, 5vw, 40px)",
        }}
      >
        <div style={{ margin: "0 auto 16px", width: 56, height: 56, borderRadius: "50%", background: "#dcfce7", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <CheckCircle2 style={{ width: 28, height: 28, color: "#16a34a" }} />
        </div>
        <h3 style={{ margin: "0 0 8px", fontSize: "1.1rem", fontWeight: 700, color: "#111" }}>Mulțumim pentru feedback!</h3>
        <p style={{ margin: 0, color: "#666", fontSize: "0.9375rem" }}>Se încarcă înregistrarea video...</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={S.card}>
      <span style={S.kicker}>Pas obligatoriu</span>
      <h2 style={{ margin: "0 0 6px", fontSize: "clamp(1.15rem, 2.5vw, 1.35rem)", fontWeight: 700, color: "#111" }}>
        Feedback rapid înainte de vizionare
      </h2>
      <p style={{ margin: "0 0 22px", color: "#888", fontSize: "0.9375rem" }}>
        Completați cele 2 întrebări pentru a debloca înregistrările video.
      </p>

      <div style={{ display: "grid", gap: "clamp(20px, 3vw, 26px)" }}>
        {/* Q1 */}
        <div>
          <p style={{ margin: "0 0 10px", fontWeight: 700, fontSize: "1rem", color: "#111" }}>
            1. Cum apreciați experiența generală la service?
          </p>
          <RadioGroup name="rating_overall" value={ratingOverall} onChange={setRatingOverall} />
        </div>

        {/* Q2 */}
        <div>
          <p style={{ margin: "0 0 10px", fontWeight: 700, fontSize: "1rem", color: "#111" }}>
            2. Cât de clar v-au fost explicate constatările de mecanic?
          </p>
          <RadioGroup name="rating_explanation" value={ratingExplanation} onChange={setRatingExplanation} />
        </div>

        {/* Q3 */}
        <div>
          <p style={{ margin: "0 0 8px", fontWeight: 700, fontSize: "1rem", color: "#111" }}>
            3. Observații sau recomandări{" "}
            <span style={{ fontWeight: 400, color: "#888" }}>(opțional)</span>
          </p>
          <textarea
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder="Scrieți aici feedback-ul dumneavoastră…"
            rows={4}
            style={{
              width: "100%",
              padding: "14px 16px",
              borderRadius: 10,
              border: "1px solid #e0e0e0",
              background: "#f8fafb",
              fontFamily: "inherit",
              fontSize: "0.9375rem",
              resize: "vertical",
              minHeight: 110,
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>

        {error && (
          <div style={{ padding: "12px 16px", borderRadius: 8, background: "#fef2f2", border: "1px solid #fecaca", color: "#b91c1c", fontSize: "0.875rem" }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={!canSubmit || isPending}
          style={{
            border: 0,
            borderRadius: 10,
            padding: "15px 24px",
            background: canSubmit ? "var(--tedde-accent-cyan, #4fb9d3)" : "#cccccc",
            color: canSubmit ? "#000000" : "#888",
            fontFamily: "inherit",
            fontWeight: 700,
            fontSize: "1rem",
            cursor: canSubmit ? "pointer" : "not-allowed",
            transition: "filter .15s, transform .12s",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
          }}
        >
          {isPending && <Loader2 style={{ width: 18, height: 18, animation: "spin 1s linear infinite" }} />}
          {isPending ? "Se trimite..." : "Trimite și vizionează înregistrarea →"}
        </button>

        {!canSubmit && (
          <p style={{ margin: 0, fontSize: "0.8125rem", color: "#aaa", textAlign: "center" }}>
            Selectați o evaluare pentru ambele întrebări pentru a continua
          </p>
        )}
      </div>
    </form>
  );
}
