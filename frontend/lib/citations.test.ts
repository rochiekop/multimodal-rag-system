import { describe, expect, it } from "vitest"

import { linkCitations } from "@/lib/citations"

describe("linkCitations", () => {
  it("only links citations that match a source", () => {
    const text = "Leave is 25 days [1][2]. Since [2024] see [3]."
    expect(linkCitations(text, new Set([1, 2]))).toBe(
      "Leave is 25 days [1](#cite-1)[2](#cite-2). Since [2024] see [3]."
    )
  })

  it("leaves text without citations alone", () => {
    expect(linkCitations("Nothing here.", new Set([1]))).toBe("Nothing here.")
  })
})
