import { describe, expect, it } from "vitest"

import { highlightBox } from "@/lib/bbox"

describe("highlightBox", () => {
  it("maps page points to rendered pixels", () => {
    // 1.5 px per point in the PNG; PNG is 1500px wide, rendered at 750px -> 0.75 px per point.
    expect(
      highlightBox({ l: 10, t: 20, r: 110, b: 70 }, 1.5, 1500, 750)
    ).toEqual({
      left: 7.5,
      top: 15,
      width: 75,
      height: 37.5,
    })
  })
})
