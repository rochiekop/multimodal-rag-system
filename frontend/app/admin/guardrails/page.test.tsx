import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import GuardrailsPage from "@/app/admin/guardrails/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const guardrails = {
  rate_limit_per_minute: 10,
  max_question_chars: 2000,
  moderation: {
    violence: "block",
    hate: "block",
    harassment: "block",
    sexual: "block",
    illegal: "block",
    weapons: "block",
    self_harm: "flag",
  },
  self_harm_support: true,
  injection_check: true,
  exfiltration_check: true,
  scope_check: false,
  scope_description: "",
  classifier_model: "gpt-5-nano",
  blocked_message: "I can't help with that request.",
  off_topic_message: "I can only help with company documents.",
  support_message: "Please reach out.",
  pii_redaction: true,
  pii_patterns: [{ name: "employee_number", regex: "\\bEMP-\\d{6}\\b" }],
  system_prompt_leak_check: true,
  groundedness_check: true,
  judge_model: "gpt-5-nano",
  strike_limit: 3,
  strike_window_hours: 24,
  strike_lock_hours: 24,
  user_daily_cost_usd: 2,
  installation_daily_cost_usd: 50,
  cost_alert_ratio: 0.8,
}
const config = { chat_model: "gpt-5-mini", guardrails }

describe("GuardrailsPage", () => {
  it("saves guardrail changes as a new version and offers activation", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input)
        if (url === "/api/auth/me")
          return jsonResponse({
            id: "u1",
            username: "r",
            full_name: "R",
            role: "super_admin",
            is_active: true,
            must_change_password: false,
            groups: [],
          })
        if (url === "/api/admin/rag-configs/active")
          return jsonResponse({ version: 4, config, latest_eval: null })
        if (init?.method === "POST")
          return jsonResponse(
            {
              id: "id5",
              version: 5,
              note: "",
              is_active: false,
              created_at: "",
              activated_at: null,
              latest_eval: null,
              config,
            },
            201
          )
        return jsonResponse([])
      })
    renderWithProviders(<GuardrailsPage />)
    await userEvent.click(await screen.findByLabelText("Groundedness check"))
    await userEvent.selectOptions(screen.getByLabelText("Weapons"), "flag")
    await userEvent.click(screen.getByRole("button", { name: "Add pattern" }))
    await userEvent.type(screen.getByLabelText("Pattern 2 name"), "badge_id")
    await userEvent.type(
      screen.getByLabelText("Pattern 2 regex"),
      "B-[[0-9]{{4}"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Save as new version" })
    )
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, i]) =>
          String(u) === "/api/admin/rag-configs" && i?.method === "POST"
      )
      const body = JSON.parse(String(call?.[1]?.body))
      expect(body.config.chat_model).toBe("gpt-5-mini")
      expect(body.config.guardrails.groundedness_check).toBe(false)
      expect(body.config.guardrails.moderation.weapons).toBe("flag")
      expect(body.config.guardrails.pii_patterns[1]).toEqual({
        name: "badge_id",
        regex: "B-[0-9]{4}",
      })
    })
    expect(
      await screen.findByRole("button", { name: "Activate v5" })
    ).toBeInTheDocument()
  })
})
