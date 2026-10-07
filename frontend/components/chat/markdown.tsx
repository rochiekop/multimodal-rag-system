import ReactMarkdown from "react-markdown"
import rehypeSanitize from "rehype-sanitize"
import remarkGfm from "remark-gfm"

import { CitationBadge } from "@/components/chat/citation-badge"
import { CITATION_HREF_PREFIX, linkCitations } from "@/lib/citations"
import type { SourceCard } from "@/lib/types"

/** Sanitized Markdown (spec §5.3). Raw HTML from documents or the model is never rendered. */
export function Markdown({
  content,
  sources,
  onOpenSource,
}: {
  content: string
  sources: SourceCard[]
  onOpenSource: (card: SourceCard) => void
}) {
  const byNumber = new Map(sources.map((s) => [s.n, s]))
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert [&_table]:text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a({ href, children }) {
            if (href?.startsWith(CITATION_HREF_PREFIX)) {
              const card = byNumber.get(
                Number(href.slice(CITATION_HREF_PREFIX.length))
              )
              if (card)
                return <CitationBadge card={card} onOpen={onOpenSource} />
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            )
          },
        }}
      >
        {linkCitations(content, new Set(byNumber.keys()))}
      </ReactMarkdown>
    </div>
  )
}
