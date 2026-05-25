"use client";

import { useState } from "react";
import { Send, Loader2, CheckCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ResendSmsButtonProps {
  linkId: number;
  smsStatus: string;
}

export function ResendSmsButton({ linkId, smsStatus }: ResendSmsButtonProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);
  const [message, setMessage] = useState("");

  const handleResend = async () => {
    setLoading(true);
    setResult(null);

    try {
      const res = await fetch(`/api/customer-links/${linkId}/resend`, {
        method: "POST",
        credentials: "include",
      });
      const data = await res.json();

      if (res.ok) {
        setResult("success");
        setMessage(data.sms_status === "sent" ? "SMS trimis!" : "SMS în așteptare");
      } else {
        setResult("error");
        setMessage(data.detail || "Eroare la trimitere");
      }
    } catch {
      setResult("error");
      setMessage("Eroare de rețea");
    } finally {
      setLoading(false);
    }
  };

  const label = smsStatus === "sent" || smsStatus === "mocked" ? "Re-trimite SMS" : "Trimite SMS";

  return (
    <div className="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={handleResend}
        disabled={loading}
        className="h-8 text-xs gap-1.5"
      >
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Send className="h-3.5 w-3.5" />
        )}
        {label}
      </Button>

      {result === "success" && (
        <span className="flex items-center gap-1 text-xs text-emerald-600">
          <CheckCircle className="h-3.5 w-3.5" />
          {message}
        </span>
      )}
      {result === "error" && (
        <span className="flex items-center gap-1 text-xs text-red-600">
          <XCircle className="h-3.5 w-3.5" />
          {message}
        </span>
      )}
    </div>
  );
}
