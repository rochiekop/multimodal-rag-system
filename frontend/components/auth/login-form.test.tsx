import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { LoginForm, safeNext } from "@/components/auth/login-form"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }))

const user = {
  id: "u1",
  username: "alice",
  full_name: "Alice",
  role: "user",
  is_active: true,
  must_change_password: false,
  groups: [],
}

async function fillAndSubmit(password = "secret-pass") {
  await userEvent.type(screen.getByLabelText("Username"), "alice")
  await userEvent.type(screen.getByLabelText("Password"), password)
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
}

describe("LoginForm", () => {
  beforeEach(() => replace.mockReset())

  it("signs in and goes to the requested page", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ must_change_password: false, user }))
    renderWithProviders(<LoginForm next="/app/c/123" />)
    await fillAndSubmit()
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/session")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      username: "alice",
      password: "secret-pass",
    })
    expect(replace).toHaveBeenCalledWith("/app/c/123")
  })

  it("sends users who must change their password there first", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        must_change_password: true,
        user: { ...user, must_change_password: true },
      })
    )
    renderWithProviders(<LoginForm next="/app" />)
    await fillAndSubmit()
    expect(replace).toHaveBeenCalledWith("/change-password")
  })

  it("shows the server's error and ignores unsafe next paths", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: "invalid_credentials",
            message: "Invalid username or password",
          },
        },
        401
      )
    )
    renderWithProviders(<LoginForm next="https://evil.example" />)
    await fillAndSubmit("nope")
    expect(
      await screen.findByText("Invalid username or password")
    ).toBeInTheDocument()
    expect(replace).not.toHaveBeenCalled()
  })

  it("requires both fields", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
    renderWithProviders(<LoginForm next="/app" />)
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(await screen.findByText("Enter your username")).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("ignores next paths that aren't local", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ must_change_password: false, user })
    )
    renderWithProviders(<LoginForm next="//evil.example/app" />)
    await fillAndSubmit()
    expect(replace).toHaveBeenCalledWith("/app")
  })
})

describe("safeNext", () => {
  it("keeps local paths", () => {
    expect(safeNext("/app/c/1?x=1#y")).toBe("/app/c/1?x=1#y")
  })

  it.each([
    "/\\evil.example",
    "/\\/evil.example",
    "/\t/evil.example",
    "//evil.example",
    "https://evil.example",
    "",
    undefined,
    "app",
  ])("falls back to /app for %j", (value) => {
    expect(safeNext(value)).toBe("/app")
  })
})
