"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"

export function FeedbackButtons({
  messageId,
  initial,
}: {
  messageId: string
  initial: 1 | -1 | null
}) {
  const [rating, setRating] = useState(initial)
  const [open, setOpen] = useState(false)
  const [comment, setComment] = useState("")
  const queryClient = useQueryClient()
  const send = useMutation({
    mutationFn: ({ value, text }: { value: 1 | -1; text?: string }) =>
      api.feedback(messageId, value, text),
    onSuccess: (_, { value }) => {
      setRating(value)
      // Cached transcripts carry the old rating.
      queryClient.removeQueries({
        queryKey: ["conversation"],
        type: "inactive",
      })
      void queryClient.invalidateQueries({ queryKey: ["conversation"] })
      setOpen(false)
      toast.success("Thanks for the feedback")
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : "Couldn't send feedback"
      ),
  })

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Good answer"
        aria-pressed={rating === 1}
        onClick={() => send.mutate({ value: 1 })}
        className={rating === 1 ? "text-primary" : "text-muted-foreground"}
      >
        <ThumbsUpIcon />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Bad answer"
        aria-pressed={rating === -1}
        onClick={() => setOpen(true)}
        className={rating === -1 ? "text-destructive" : "text-muted-foreground"}
      >
        <ThumbsDownIcon />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>What went wrong?</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`feedback-${messageId}`}>
              What was wrong? (optional)
            </Label>
            <Textarea
              id={`feedback-${messageId}`}
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              disabled={send.isPending}
              onClick={() =>
                send.mutate({ value: -1, text: comment.trim() || undefined })
              }
            >
              Send feedback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
