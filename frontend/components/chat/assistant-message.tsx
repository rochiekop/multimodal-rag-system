import { LoaderIcon, TriangleAlertIcon } from "lucide-react"

import { FeedbackButtons } from "@/components/chat/feedback-buttons"
import { Markdown } from "@/components/chat/markdown"
import { SourceCard } from "@/components/chat/source-card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import type { UIMessage } from "@/lib/chat-state"
import type { SourceCard as Card } from "@/lib/types"

const NOTICE_OUTCOMES = new Set(["blocked", "support", "off_topic", "error"])

export function AssistantMessage({
  message,
  onOpenSource,
}: {
  message: UIMessage
  onOpenSource: (card: Card) => void
}) {
  const { outcome } = message
  const cards = outcome === "not_found" ? message.sources : message.citations
  const canRate =
    !message.streaming &&
    !message.id.startsWith("temp-") &&
    (outcome === "answered" || outcome === "not_found")

  return (
    <div className="flex flex-col gap-2">
      {message.low_confidence && (
        <Badge
          variant="outline"
          className="w-fit gap-1 border-amber-500 text-amber-700 dark:text-amber-400"
        >
          <TriangleAlertIcon className="size-3" /> Low confidence — verify
          sources
        </Badge>
      )}
      {outcome && NOTICE_OUTCOMES.has(outcome) ? (
        <Alert
          variant={
            outcome === "error" || outcome === "blocked"
              ? "destructive"
              : "default"
          }
        >
          <AlertDescription className="whitespace-pre-wrap">
            {message.content}
          </AlertDescription>
        </Alert>
      ) : message.content ? (
        <Markdown
          content={message.content}
          sources={message.sources}
          onOpenSource={onOpenSource}
        />
      ) : (
        message.streaming && (
          <LoaderIcon
            className="size-4 animate-spin text-muted-foreground"
            aria-label="Thinking"
          />
        )
      )}
      {message.notice && (
        <p className="text-sm text-destructive">{message.notice}</p>
      )}
      {outcome === "cancelled" && (
        <p className="text-xs text-muted-foreground">Stopped</p>
      )}
      {cards.length > 0 && (
        <div className="flex flex-col gap-1">
          {outcome === "not_found" && (
            <span className="text-xs font-medium text-muted-foreground">
              Closest matches
            </span>
          )}
          <div className="flex gap-2 overflow-x-auto pb-1">
            {cards.map((card) => (
              <SourceCard
                key={`${card.doc_id}-${card.n}`}
                card={card}
                onOpen={onOpenSource}
              />
            ))}
          </div>
        </div>
      )}
      {canRate && (
        <FeedbackButtons
          messageId={message.id}
          initial={message.feedback_rating}
        />
      )}
    </div>
  )
}
