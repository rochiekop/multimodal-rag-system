export const APP_NAME =
  process.env.NEXT_PUBLIC_APP_NAME ?? "Knowledge Assistant"

const PHOENIX_URL = process.env.NEXT_PUBLIC_PHOENIX_URL?.replace(/\/+$/, "")

/** Link to a trace in Phoenix (spec §7.2), or null when Phoenix's URL isn't configured. */
export const traceUrl = (traceId: string | null) =>
  PHOENIX_URL && traceId
    ? `${PHOENIX_URL}/redirects/traces/${encodeURIComponent(traceId)}`
    : null
