import type { NextConfig } from "next"

// In production Caddy routes /api straight to FastAPI; this rewrite only serves `next start`
// and `next dev`. Rewrites are fixed at build time.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000"

const nextConfig: NextConfig = {
  output: "standalone",
  compress: false, // never buffer the answer stream; Caddy compresses in production
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]
  },
}

export default nextConfig
