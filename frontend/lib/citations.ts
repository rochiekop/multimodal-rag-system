export const CITATION_HREF_PREFIX = "#cite-"
const CITATION = /\[(\d+)\]/g

/** Turn "[n]" into a Markdown link only when n is one of this answer's sources. */
export function linkCitations(
  markdown: string,
  sourceNumbers: Set<number>
): string {
  return markdown.replace(CITATION, (match, digits: string) => {
    const n = Number(digits)
    return sourceNumbers.has(n) ? `[${n}](${CITATION_HREF_PREFIX}${n})` : match
  })
}
