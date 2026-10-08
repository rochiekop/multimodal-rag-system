import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import ModelsPage from "@/app/admin/models/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const guardrails = { groundedness_check: true, pii_patterns: [] }
const config = {
  chat_model: "gpt-5-mini",
  rewrite_model: "gpt-5-nano",
  fallback_model: null,
  eval_judge_model: "gpt-5-mini",
  reranker_model: "Xenova/ms-marco-MiniLM-L-12-v2",
  search_top_k: 50,
  rerank_top_n: 8,
  rerank_threshold: 0.1,
  history_turns: 3,
  system_prompt: "Answer from sources.",
  rewrite_prompt: "Rewrite.",
  not_found_message: "Not found.",
  greeting_message: "Hi!",
  prices: { "gpt-5-mini": { input_per_mtok: 0.25, output_per_mtok: 2 } },
  guardrails,
}
const v1 = {
  id: "id1",
  version: 1,
  note: "first",
  is_active: false,
  created_at: "2026-10-01T00:00:00Z",
  activated_at: null,
  latest_eval: {
    run_id: "r1",
    eval_set_id: "s1",
    score: 0.82,
    finished_at: null,
  },
  config,
}
const v2 = {
  ...v1,
  id: "id2",
  version: 2,
  note: "second",
  is_active: true,
  latest_eval: {
    run_id: "r2",
    eval_set_id: "s1",
    score: 0.9,
    finished_at: null,
  },
}

function mockApi(role: string) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === "/api/auth/me")
        return jsonResponse({
          id: "u1",
          username: "r",
          full_name: "R",
          role,
          is_active: true,
          must_change_password: false,
          groups: [],
        })
      if (url === "/api/admin/rag-configs/active")
        return jsonResponse({ version: 2, config, latest_eval: v2.latest_eval })
      if (init?.method === "POST")
        return jsonResponse(
          { ...v2, id: "id3", version: 3, is_active: false },
          201
        )
      return jsonResponse([v2, v1])
    })
}

const posted = (fetchMock: ReturnType<typeof mockApi>, url: string) => {
  const call = fetchMock.mock.calls.find(
    ([u, i]) => String(u) === url && i?.method === "POST"
  )
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

describe("ModelsPage", () => {
  it("is closed to admins", async () => {
    const fetchMock = mockApi("admin")
    renderWithProviders(<ModelsPage />)
    expect(
      await screen.findByText("Only super admins can open this page.")
    ).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([u]) =>
        String(u).startsWith("/api/admin/rag-configs")
      )
    ).toBe(false)
  })

  it("saves a new version from the active config", async () => {
    const fetchMock = mockApi("super_admin")
    renderWithProviders(<ModelsPage />)
    const chat = await screen.findByLabelText("Chat model")
    await userEvent.clear(chat)
    await userEvent.type(chat, "gpt-5")
    await userEvent.type(screen.getByLabelText("Note"), "bigger model")
    await userEvent.click(
      screen.getByRole("button", { name: "Save as new version" })
    )
    await waitFor(() =>
      expect(posted(fetchMock, "/api/admin/rag-configs")).toBeDefined()
    )
    const body = posted(fetchMock, "/api/admin/rag-configs")
    expect(body.note).toBe("bigger model")
    expect(body.config.chat_model).toBe("gpt-5")
    expect(body.config.guardrails).toEqual(guardrails) // untouched
    expect(body.config.fallback_model).toBeNull()
  })

  it("rolls back with the eval warning and a password", async () => {
    const fetchMock = mockApi("super_admin")
    renderWithProviders(<ModelsPage />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Activate v1" })
    )
    expect(
      await screen.findByText(/v1 scored 82%.*active v2 scored 90%/)
    ).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Your password"), "pw-123")
    await userEvent.click(screen.getByRole("button", { name: "Activate" }))
    await waitFor(() =>
      expect(posted(fetchMock, "/api/admin/rag-configs/id1/activate")).toEqual({
        password: "pw-123",
      })
    )
  })
})
