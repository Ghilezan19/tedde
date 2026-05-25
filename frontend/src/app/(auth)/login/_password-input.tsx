"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export function PasswordInput() {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <input
        id="password"
        name="password"
        type={visible ? "text" : "password"}
        autoComplete="current-password"
        required
        autoFocus
        className="w-full rounded-md border border-input bg-background px-3 py-2 pr-10 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent transition-shadow"
        placeholder="Introdu parola"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Ascunde parola" : "Arată parola"}
        aria-pressed={visible}
        tabIndex={-1}
        className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground hover:text-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-ring rounded-r-md"
      >
        {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}
