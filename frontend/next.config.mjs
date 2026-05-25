/** @type {import('next').NextConfig} */
// Production: set BACKEND_URL=http://127.0.0.1:8000 (Next + API on the same host; with a
// public Nginx on a VM, only the VM talks to the laptop; server-side rewrites still hit localhost:8000).
// (or rely on the default below). See deploy/tedde.env.example.
const nextConfig = {
  async rewrites() {
    const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [
      // FastAPI static assets
      { source: "/events/:path*", destination: `${BACKEND}/events/:path*` },
      { source: "/recordings/:path*", destination: `${BACKEND}/recordings/:path*` },
      { source: "/snapshots/:path*", destination: `${BACKEND}/snapshots/:path*` },
      { source: "/public/:path*", destination: `${BACKEND}/public/:path*` },
      // FastAPI video (token-gated) - must be BEFORE /verificare/ generic
      { source: "/verificare/:token/video/:camera", destination: `${BACKEND}/verificare/:token/video/:camera` },
      // FastAPI APIs
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      { source: "/ws/audio", destination: `${BACKEND}/ws/audio` },
      { source: "/counter-start", destination: `${BACKEND}/counter-start` },
      { source: "/help-esp1", destination: `${BACKEND}/help-esp1` },
      // Auth handled by FastAPI
      { source: "/logout", destination: `${BACKEND}/logout` },
    ];
  },
};

export default nextConfig;
