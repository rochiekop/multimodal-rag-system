import { describe, expect, it } from "vitest"

import { contrastText } from "@/lib/branding"

describe("contrastText", () => {
  it("picks black on light colors and white on dark ones", () => {
    expect(contrastText("#ffffff")).toBe("#000000")
    expect(contrastText("#FACC15")).toBe("#000000")
    expect(contrastText("#1d4ed8")).toBe("#ffffff")
    expect(contrastText("#000000")).toBe("#ffffff")
  })
})
