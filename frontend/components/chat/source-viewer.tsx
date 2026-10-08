"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { sourceLabel } from "@/components/chat/citation-badge"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { highlightBox } from "@/lib/bbox"
import { pageImageUrl } from "@/lib/api"
import type { SourceCard } from "@/lib/types"

/** Opens the cited page with the cited region highlighted (spec §4.1 step 9, §6.4). */
export function SourceViewer({
  card,
  onClose,
}: {
  card: SourceCard | null
  onClose: () => void
}) {
  return (
    <Sheet open={card !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="w-full overflow-y-auto sm:max-w-2xl"
      >
        <SheetHeader>
          <SheetTitle>{card ? sourceLabel(card) : ""}</SheetTitle>
          <SheetDescription>{card?.heading_path.join(" › ")}</SheetDescription>
        </SheetHeader>
        {/* Keyed so each source starts with fresh highlight/error state. */}
        {card && <PagePreview key={`${card.doc_id}-${card.n}`} card={card} />}
      </SheetContent>
    </Sheet>
  )
}

function PagePreview({ card }: { card: SourceCard }) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [box, setBox] = useState<ReturnType<typeof highlightBox> | null>(null)
  const [failed, setFailed] = useState(false)

  const measure = useCallback(() => {
    const img = imgRef.current
    if (!img || !card.bbox || !card.page_image_scale || !img.naturalWidth)
      return
    setBox(
      highlightBox(
        card.bbox,
        card.page_image_scale,
        img.naturalWidth,
        img.clientWidth
      )
    )
  }, [card])

  useEffect(() => {
    window.addEventListener("resize", measure)
    return () => window.removeEventListener("resize", measure)
  }, [measure])

  const hasPage = card.page != null
  return (
    <>
      {hasPage && !failed && (
        <div className="relative mx-4 mb-4">
          {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
          <img
            ref={imgRef}
            src={pageImageUrl(card.doc_id, card.page!)}
            alt={`Page ${card.page} of ${card.filename}`}
            onLoad={measure}
            onError={() => setFailed(true)}
            className="w-full rounded border"
          />
          {box && (
            <div
              data-testid="source-highlight"
              className="pointer-events-none absolute rounded-sm border-2 border-amber-500 bg-amber-300/25"
              style={box}
            />
          )}
        </div>
      )}
      {(!hasPage || failed) && (
        <p className="mx-4 text-sm text-muted-foreground">
          {failed
            ? "The page preview isn't available."
            : "This file type has no page preview."}
        </p>
      )}
      <blockquote className="mx-4 mb-6 border-l-2 pl-3 text-sm">
        {card.snippet}
      </blockquote>
    </>
  )
}
