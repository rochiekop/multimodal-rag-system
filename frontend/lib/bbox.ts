import type { Bbox } from "@/lib/types"

/** Bbox is in page points (top-left origin); the page PNG has pageImageScale px per point. */
export function highlightBox(
  bbox: Bbox,
  pageImageScale: number,
  naturalWidth: number,
  renderedWidth: number
) {
  const ratio = (pageImageScale * renderedWidth) / naturalWidth
  return {
    left: bbox.l * ratio,
    top: bbox.t * ratio,
    width: (bbox.r - bbox.l) * ratio,
    height: (bbox.b - bbox.t) * ratio,
  }
}
