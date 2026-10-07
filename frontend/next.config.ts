import type { NextConfig } from "next"

// Development and `next start`: forward the API to FastAPI. In production Caddy routes /api
// straight to the backend (Plan 8). Rewrites are fixed at build time.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000"

const nextConfig: NextConfig = {
  compress: false, // never buffer the answer stream; Caddy compresses in production
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]
  },
}

export default nextConfig
