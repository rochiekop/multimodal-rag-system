import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import SettingsPage from "@/app/admin/settings/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const KEY = "sk-live-abcdefghijklmnop9876"
const branding = {
  app_name: "Knowledge Assistant",
  primary_color: null,
  logo_url: null,
}

function mockApi(status: Record<string, unknown>) {
  return vi
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
      if (url === "/api/branding") return jsonResponse(branding)
      if (url === "/api/admin/settings/branding")
        return jsonResponse({ ...branding, ...JSON.parse(String(init?.body)) })
      if (url === "/api/admin/settings/openai-key" && init?.method === "PUT")
        return jsonResponse({
          source: "database",
          last4: "9876",
          updated_at: "2026-10-08T10:00:00Z",
          secrets_key_configured: true,
        })
      return jsonResponse(status)
    })
}

const sent = (
  fetchMock: ReturnType<typeof mockApi>,
  method: string,
  url: string
) => {
  const call = fetchMock.mock.calls.find(
    ([u, i]) => String(u) === url && i?.method === method
  )
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

describe("SettingsPage", () => {
  it("validates and saves branding", async () => {
    const fetchMock = mockApi({
      source: "none",
      last4: null,
      updated_at: null,
      secrets_key_configured: true,
    })
    renderWithProviders(<SettingsPage />)
    const name = await screen.findByLabelText("App name")
    await userEvent.clear(name)
    await userEvent.type(name, "Acme Docs")
    await userEvent.type(screen.getByLabelText("Primary color"), "blue")
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }))
    expect(
      await screen.findByText("Use a hex color like #1d4ed8")
    ).toBeInTheDocument()
    expect(
      sent(fetchMock, "PUT", "/api/admin/settings/branding")
    ).toBeUndefined()

    await userEvent.clear(screen.getByLabelText("Primary color"))
    await userEvent.type(screen.getByLabelText("Primary color"), "#1d4ed8")
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }))
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", "/api/admin/settings/branding")).toEqual({
        app_name: "Acme Docs",
        primary_color: "#1d4ed8",
      })
    )
  })

  it("saves the key after a password and never shows it again", async () => {
    const fetchMock = mockApi({
      source: "environment",
      last4: "1234",
      updated_at: null,
      secrets_key_configured: true,
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText(/RAG_OPENAI_API_KEY/)).toBeInTheDocument()
    const input = screen.getByLabelText("New OpenAI API key")
    await userEvent.type(input, KEY)
    await userEvent.click(screen.getByRole("button", { name: "Save key" }))
    await userEvent.type(
      await screen.findByLabelText("Your password"),
      "pw-123"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Save key securely" })
    )
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", "/api/admin/settings/openai-key")).toEqual({
        api_key: KEY,
        password: "pw-123",
      })
    )
    expect(await screen.findByText(/…9876/)).toBeInTheDocument()
    expect(input).toHaveValue("")
    expect(document.body.textContent).not.toContain(KEY)
  })

  it("explains when RAG_SECRETS_KEY is missing", async () => {
    mockApi({
      source: "environment",
      last4: "1234",
      updated_at: null,
      secrets_key_configured: false,
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText(/Set RAG_SECRETS_KEY/)).toBeInTheDocument()
    expect(screen.getByLabelText("New OpenAI API key")).toBeDisabled()
  })
})
