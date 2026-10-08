import { FileTextIcon } from "lucide-react"

import { sourceLabel } from "@/components/chat/citation-badge"
import type { SourceCard as Card } from "@/lib/types"

export function SourceCard({
  card,
  onOpen,
}: {
  card: Card
  onOpen: (card: Card) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(card)}
      className="flex w-56 shrink-0 flex-col gap-1 rounded-lg border bg-card p-2 text-left text-xs hover:bg-accent"
    >
      <span className="flex items-center gap-1 font-medium">
        <FileTextIcon className="size-3.5" />
        <span className="truncate">
          [{card.n}] {sourceLabel(card)}
        </span>
      </span>
      <span className="line-clamp-2 text-muted-foreground">{card.snippet}</span>
    </button>
  )
}
