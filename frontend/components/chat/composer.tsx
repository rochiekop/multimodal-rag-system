"use client"

import { ArrowUpIcon, SquareIcon } from "lucide-react"
import { useState } from "react"

import { CollectionPicker } from "@/components/chat/collection-picker"
import { useCollectionSelection } from "@/components/chat/collection-selection"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

export function Composer({
  selectionKey,
  streaming,
  onAsk,
  onStop,
}: {
  /** Conversation id, or "new" for a chat that hasn't started. */
  selectionKey: string
  streaming: boolean
  onAsk: (question: string, collectionIds: string[]) => void
  onStop: () => void
}) {
  const [text, setText] = useState("")
  const [collections, setCollections] = useCollectionSelection(selectionKey)

  function submit() {
    const question = text.trim()
    if (!question || streaming) return
    onAsk(question, collections)
    setText("")
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="rounded-2xl border bg-background p-2 shadow-sm">
        <Textarea
          placeholder="Ask a question"
          aria-label="Ask a question"
          value={text}
          disabled={streaming}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault()
              submit()
            }
          }}
          className="min-h-12 resize-none border-0 shadow-none focus-visible:ring-0"
        />
        <div className="flex items-center justify-between">
          <CollectionPicker value={collections} onChange={setCollections} />
          {streaming ? (
            <Button
              size="icon"
              variant="outline"
              aria-label="Stop"
              onClick={onStop}
            >
              <SquareIcon />
            </Button>
          ) : (
            <Button
              size="icon"
              aria-label="Send"
              disabled={!text.trim()}
              onClick={submit}
            >
              <ArrowUpIcon />
            </Button>
          )}
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-muted-foreground">
        Answers come from your company&apos;s documents. Check the sources.
      </p>
    </div>
  )
}
