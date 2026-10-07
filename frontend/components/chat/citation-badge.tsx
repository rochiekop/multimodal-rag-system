import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card"
import type { SourceCard } from "@/lib/types"

export function sourceLabel(card: SourceCard): string {
  return card.page ? `${card.filename}, page ${card.page}` : card.filename
}

export function CitationBadge({
  card,
  onOpen,
}: {
  card: SourceCard
  onOpen: (card: SourceCard) => void
}) {
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          onClick={() => onOpen(card)}
          aria-label={`Source ${card.n}: ${sourceLabel(card)}`}
          className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/10 px-1 align-super text-[0.65rem] font-medium text-primary hover:bg-primary/20"
        >
          {card.n}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-80 text-sm">
        <p className="font-medium">{sourceLabel(card)}</p>
        {card.heading_path.length > 0 && (
          <p className="text-xs text-muted-foreground">
            {card.heading_path.join(" › ")}
          </p>
        )}
        <p className="mt-2 line-clamp-4 text-muted-foreground">
          {card.snippet}
        </p>
      </HoverCardContent>
    </HoverCard>
  )
}
