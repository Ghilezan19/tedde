"use client";

import { useState } from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { SaveBar } from "../_components/SaveBar";

interface Props { config: Record<string, string>; }

function Field({
  label, name, value, onChange, type = "text", mono, hint, placeholder, area
}: {
  label: string; name: string; value: string; onChange: (v: string) => void;
  type?: string; mono?: boolean; hint?: string; placeholder?: string; area?: boolean;
}) {
  const cls = `w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring ${mono ? "font-mono" : ""}`;
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {area ? (
        <textarea name={name} rows={4} defaultValue={value} onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder} className={`${cls} py-2`} />
      ) : (
        <input name={name} type={type} defaultValue={value} onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder} className={`${cls} h-9`} />
      )}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function PortalSmsClient({ config }: Props) {
  const [values, setValues] = useState({ ...config });
  const set = (key: string) => (v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  return (
    <div className="space-y-8 pb-20">
      <div>
        <h1 className="text-xl font-bold">Portal Client & SMS</h1>
        <p className="text-sm text-muted-foreground mt-1">Brand portal, gateway SMS și configurare avansată</p>
      </div>

      {/* Portal brand */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">📱 Portal Client — Brand</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="URL public bază" name="PUBLIC_BASE_URL" value={values.PUBLIC_BASE_URL || ""} onChange={set("PUBLIC_BASE_URL")} mono hint="ex. https://video.scoala-ai.ro" />
          <Field label="Prefix portal" name="PORTAL_PATH_PREFIX" value={values.PORTAL_PATH_PREFIX || "/verificare"} onChange={set("PORTAL_PATH_PREFIX")} mono hint="ex. /verificare" />
          <Field label="TTL link (zile)" name="CUSTOMER_LINK_TTL_DAYS" value={values.CUSTOMER_LINK_TTL_DAYS || "30"} onChange={set("CUSTOMER_LINK_TTL_DAYS")} />
          <Field label="Nume brand" name="PORTAL_BRAND_NAME" value={values.PORTAL_BRAND_NAME || ""} onChange={set("PORTAL_BRAND_NAME")} />
          <Field label="Telefon footer" name="PORTAL_FOOTER_PHONE" value={values.PORTAL_FOOTER_PHONE || ""} onChange={set("PORTAL_FOOTER_PHONE")} />
          <Field label="Email footer" name="PORTAL_FOOTER_EMAIL" value={values.PORTAL_FOOTER_EMAIL || ""} onChange={set("PORTAL_FOOTER_EMAIL")} />
          <Field label="Adresă footer" name="PORTAL_FOOTER_ADDRESS" value={values.PORTAL_FOOTER_ADDRESS || ""} onChange={set("PORTAL_FOOTER_ADDRESS")} />
          <Field label="Program footer" name="PORTAL_FOOTER_HOURS" value={values.PORTAL_FOOTER_HOURS || ""} onChange={set("PORTAL_FOOTER_HOURS")} />
          <Field label="Culoare accent portal (hex)" name="PORTAL_THEME_ACCENT" value={values.PORTAL_THEME_ACCENT || ""} onChange={set("PORTAL_THEME_ACCENT")} mono placeholder="#2563eb" />
          <Field label="Culoare dark portal (hex)" name="PORTAL_THEME_DARK" value={values.PORTAL_THEME_DARK || ""} onChange={set("PORTAL_THEME_DARK")} mono placeholder="#0f172a" />
        </div>
      </section>

      {/* SMS Gateway */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">📨 SMS Gateway</h2>
          <Link href="/sms-test" className="flex items-center gap-1 text-xs text-primary hover:underline">
            <ExternalLink className="h-3.5 w-3.5" />
            Test SMS
          </Link>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="URL Gateway SMS" name="SMS_GATEWAY_URL" value={values.SMS_GATEWAY_URL || ""} onChange={set("SMS_GATEWAY_URL")} mono hint="ex. http://localhost:3001" />
          <Field label="API Key Gateway" name="SMS_GATEWAY_API_KEY" value="" type="password" onChange={set("SMS_GATEWAY_API_KEY")} hint="Lasă gol pentru a nu schimba" />
        </div>
        <div className="rounded-md bg-muted/50 border p-3 text-xs text-muted-foreground space-y-1">
          <p>POST <span className="font-mono">{`{URL}`}/send-sms</span></p>
          <p>API key rămâne pe server, nu ajunge în browser.</p>
        </div>
      </section>

      {/* SMS Backend avansat */}
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">⚙ SMS Backend avansat</h2>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Backend SMS</label>
          <select value={values.SMS_BACKEND || "mock"} onChange={(e) => set("SMS_BACKEND")(e.target.value)}
            className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
            <option value="mock">Mock (doar log)</option>
            <option value="simple_gateway">Simple Gateway</option>
            <option value="custom_http">Custom HTTP</option>
          </select>
        </div>
        {values.SMS_BACKEND === "custom_http" && (
          <div className="space-y-4 pt-2 border-t">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="URL Custom HTTP" name="SMS_HTTP_URL" value={values.SMS_HTTP_URL || ""} onChange={set("SMS_HTTP_URL")} mono />
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Metodă HTTP</label>
                <select value={values.SMS_HTTP_METHOD || "POST"} onChange={(e) => set("SMS_HTTP_METHOD")(e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
                  <option value="POST">POST</option>
                  <option value="PUT">PUT</option>
                </select>
              </div>
            </div>
            <Field label="Body template (JSON)" name="SMS_HTTP_BODY_TEMPLATE" value={values.SMS_HTTP_BODY_TEMPLATE || ""} onChange={set("SMS_HTTP_BODY_TEMPLATE")} mono area
              hint='Folosește {{to}} și {{message}} ca placeholder-uri.' />
          </div>
        )}
      </section>

      <SaveBar getValues={() => values} />
    </div>
  );
}
