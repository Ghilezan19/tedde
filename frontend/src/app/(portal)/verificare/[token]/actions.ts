"use server";

import { revalidatePath } from "next/cache";

export async function submitQuiz(
  token: string,
  rating_overall: number,
  rating_explanation: number,
  free_text: string
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await fetch(`${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/api/customer-portal/${token}/quiz`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating_overall, rating_explanation, free_text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, error: data?.detail?.message || "Eroare la trimiterea răspunsurilor." };
    }
    revalidatePath(`/verificare/${token}`);
    return { ok: true };
  } catch {
    return { ok: false, error: "Eroare de rețea. Încearcă din nou." };
  }
}
