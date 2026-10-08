export const APP_NAME =
  process.env.NEXT_PUBLIC_APP_NAME ?? "Knowledge Assistant"

const PHOENIX_URL = process.env.NEXT_PUBLIC_PHOENIX_URL?.replace(/\/+$/, "")

/**
 * Phoenix projects page, or null when Phoenix's URL isn't configured. Phoenix has no
 * deep link to a single trace, so the console shows the trace id next to this link.
 */
export const phoenixUrl = () => (PHOENIX_URL ? `${PHOENIX_URL}/projects` : null)
