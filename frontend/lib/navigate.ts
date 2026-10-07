/** Full page navigation (resets all in-memory client state). Mockable in tests. */
export function navigateTo(url: string) {
  window.location.assign(url)
}
