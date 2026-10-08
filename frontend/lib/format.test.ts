import { describe, expect, it } from "vitest"

import { formatBytes, formatPercent, formatUsd } from "@/lib/format"

describe("format", () => {
  it("formats rates, money and sizes", () => {
    expect(formatPercent(null)).toBe("—")
    expect(formatPercent(0.4567)).toBe("46%")
    expect(formatPercent(0)).toBe("0%")
    expect(formatUsd(0.75)).toBe("$0.75")
    expect(formatUsd(0.0042)).toBe("$0.0042")
    expect(formatBytes(512)).toBe("512 B")
    expect(formatBytes(1536)).toBe("1.5 KB")
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB")
  })
})
