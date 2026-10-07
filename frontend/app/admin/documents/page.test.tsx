import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import DocumentsPage from "@/app/admin/documents/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const collection = {
  id: "c1",
  name: "Policies",
  description: "",
  sensitive: false,
  groups: [{ id: "g1", name: "hr", description: "" }],
  created_at: "2026-10-01T00:00:00Z",
}
const version = (status: string) => ({
  id: "v1",
  version_no: 1,
  status,
  failed_stage: status === "failed" ? "parsing" : null,
  error: status === "failed" ? "Docling could not read the file" : null,
  chunk_count: 12,
  page_count: 3,
  content_type: "application/pdf",
  size_bytes: 2048,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
})
const doc = (status: string) => ({
  id: "d1",
  collection_id: "c1",
  filename: "leave.pdf",
  current_version_id: "v1",
  deleted_at: null,
  restricted_groups: [],
  versions: [version(status)],
  created_at: "2026-10-01T00:00:00Z",
})

function mockApi(status = "ready") {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === "/api/admin/collections") return jsonResponse([collection])
      if (
        url === "/api/admin/collections/c1/documents" &&
        init?.method === "POST"
      )
        return jsonResponse([
          {
            filename: "a.pdf",
            outcome: "queued",
            message: "",
            document_id: "d2",
            version_id: "v2",
          },
          {
            filename: "b.pdf",
            outcome: "duplicate",
            message: "This file is already in the collection",
            document_id: "d1",
            version_id: null,
          },
        ])
      if (url.startsWith("/api/admin/collections/c1/documents"))
        return jsonResponse([doc(status)])
      if (url.includes("/chunks")) return jsonResponse([])
      if (url.startsWith("/api/admin/versions/"))
        return jsonResponse(version("queued"))
      if (url.startsWith("/api/admin/documents/d1"))
        return jsonResponse(doc(status))
      return jsonResponse([])
    })
}

const calls = (
  fetchMock: ReturnType<typeof mockApi>,
  method: string,
  url: string
) =>
  fetchMock.mock.calls.filter(
    ([u, i]) => String(u) === url && i?.method === method
  )

describe("DocumentsPage", () => {
  it("uploads files and reports duplicates", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<DocumentsPage />)
    expect(
      await screen.findByRole("button", { name: "leave.pdf" })
    ).toBeInTheDocument()
    const files = [
      new File(["%PDF-1"], "a.pdf", { type: "application/pdf" }),
      new File(["%PDF-1"], "b.pdf", { type: "application/pdf" }),
    ]
    await userEvent.upload(screen.getByLabelText("Upload files"), files)
    await waitFor(() =>
      expect(
        calls(fetchMock, "POST", "/api/admin/collections/c1/documents")
      ).toHaveLength(1)
    )
    const body = calls(
      fetchMock,
      "POST",
      "/api/admin/collections/c1/documents"
    )[0][1]?.body
    expect((body as FormData).getAll("files")).toHaveLength(2)
    expect(
      await screen.findByText(/b\.pdf: This file is already in the collection/)
    ).toBeInTheDocument()
  })

  it("deletes a document after password confirmation", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<DocumentsPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "leave.pdf" })
    )
    const sheet = await screen.findByRole("dialog")
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete" }))
    await userEvent.type(
      await screen.findByLabelText("Your password"),
      "pw-123"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Delete document" })
    )
    await waitFor(() =>
      expect(
        calls(fetchMock, "POST", "/api/admin/documents/d1/delete")
      ).toHaveLength(1)
    )
    expect(
      JSON.parse(
        String(
          calls(fetchMock, "POST", "/api/admin/documents/d1/delete")[0][1]?.body
        )
      )
    ).toEqual({ password: "pw-123" })
  })

  it("shows a failed version's error and retries it", async () => {
    const fetchMock = mockApi("failed")
    renderWithProviders(<DocumentsPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "leave.pdf" })
    )
    const sheet = await screen.findByRole("dialog")
    expect(
      await within(sheet).findByText(/Docling could not read the file/)
    ).toBeInTheDocument()
    await userEvent.click(within(sheet).getByRole("button", { name: "Retry" }))
    await waitFor(() =>
      expect(
        calls(fetchMock, "POST", "/api/admin/versions/v1/retry")
      ).toHaveLength(1)
    )
  })
})
