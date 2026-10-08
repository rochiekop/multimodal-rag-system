import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { LoginForm, safeNext } from "@/components/auth/login-form"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
const router = { replace } // stable, like Next's router
vi.mock("next/navigation", () => ({ useRouter: () => router }))

const user = {
  id: "u1",
  username: "alice",
  full_name: "Alice",
  role: "user",
  is_active: true,
  must_change_password: false,
  groups: [],
}

const unauthorized = () =>
  jsonResponse(
    { detail: { code: "unauthorized", message: "Unauthorized" } },
    401
  )

/** Not signed in yet (/me probe 401s); the login endpoint answers with `login()`. */
function mockLogin(login: () => Response) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) =>
      String(input) === "/api/auth/me" ? unauthorized() : login()
    )
}

const loginCall = (fetchMock: ReturnType<typeof mockLogin>) =>
  fetchMock.mock.calls.find(([u]) => String(u) === "/api/auth/session")

async function fillAndSubmit(password = "secret-pass") {
  await userEvent.type(screen.getByLabelText("Username"), "alice")
  await userEvent.type(screen.getByLabelText("Password"), password)
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
}

describe("LoginForm", () => {
  beforeEach(() => replace.mockReset())

  it("signs in and goes to the requested page", async () => {
    const fetchMock = mockLogin(() =>
      jsonResponse({ must_change_password: false, user })
    )
    renderWithProviders(<LoginForm next="/app/c/123" />)
    await fillAndSubmit()
    expect(JSON.parse(String(loginCall(fetchMock)?.[1]?.body))).toEqual({
      username: "alice",
      password: "secret-pass",
    })
    expect(replace).toHaveBeenCalledWith("/app/c/123")
  })

  it("sends users who must change their password there first", async () => {
    mockLogin(() =>
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
    mockLogin(() =>
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
    const fetchMock = mockLogin(() => jsonResponse(null, 500))
    renderWithProviders(<LoginForm next="/app" />)
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(await screen.findByText("Enter your username")).toBeInTheDocument()
    expect(loginCall(fetchMock)).toBeUndefined()
  })

  it("ignores next paths that aren't local", async () => {
    mockLogin(() => jsonResponse({ must_change_password: false, user }))
    renderWithProviders(<LoginForm next="//evil.example/app" />)
    await fillAndSubmit()
    expect(replace).toHaveBeenCalledWith("/app")
  })

  it("skips the form when the session is already valid", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => jsonResponse(user))
    renderWithProviders(<LoginForm next="/app/c/123" />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/c/123"))
    expect(fetchMock.mock.calls.map(([u]) => String(u))).toEqual([
      "/api/auth/me",
    ])
  })

  it("keeps the redirect safe and honours a pending password change", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      jsonResponse({ ...user, must_change_password: true })
    )
    renderWithProviders(<LoginForm next="https://evil.example" />)
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/change-password")
    )
  })

  it("stays on the form when not signed in", async () => {
    mockLogin(() => jsonResponse(null, 500))
    renderWithProviders(<LoginForm next="/app" />)
    await new Promise((r) => setTimeout(r, 20))
    expect(replace).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument()
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
