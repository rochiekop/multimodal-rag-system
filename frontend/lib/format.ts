const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
})

export const formatDateTime = (iso: string) => dateTime.format(new Date(iso))

export const formatPercent = (rate: number | null | undefined) =>
  rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`

export function formatUsd(amount: number): string {
  const digits = amount !== 0 && Math.abs(amount) < 0.01 ? 4 : 2
  return `$${amount.toFixed(digits)}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
