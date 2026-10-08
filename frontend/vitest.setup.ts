import "@testing-library/jest-dom/vitest"

import { cleanup, configure } from "@testing-library/react"
import { afterEach, vi } from "vitest"

// The default 1 s wait for findBy*/waitFor flakes when the full suite runs in parallel on a
// busy machine (Docker stack, dev server); real failures still fail, just after 5 s.
configure({ asyncUtilTimeout: 5000 })

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// jsdom lacks these; radix and the sidebar's mobile hook use them.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??=
  ResizeObserverStub as unknown as typeof ResizeObserver
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
Element.prototype.scrollIntoView ??= function scrollIntoView() {}
