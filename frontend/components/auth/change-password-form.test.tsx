import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ChangePasswordForm } from "@/components/auth/change-password-form"
import { jsonResponse, renderWithProviders } from "@/test/render"

describe("ChangePasswordForm", () => {
  it("checks the confirmation and calls the session password endpoint", async () => {
    const onDone = vi.fn()
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        must_change_password: false,
        user: { id: "u1", username: "alice" },
      })
    )
    renderWithProviders(<ChangePasswordForm onDone={onDone} />)
    await userEvent.type(
      screen.getByLabelText("Current password"),
      "old-pass-123"
    )
    await userEvent.type(
      screen.getByLabelText("New password"),
      "brand-new-pass-456"
    )
    await userEvent.type(
      screen.getByLabelText("Confirm new password"),
      "different-pass-789"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Change password" })
    )
    expect(await screen.findByText("Passwords don't match")).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()

    await userEvent.clear(screen.getByLabelText("Confirm new password"))
    await userEvent.type(
      screen.getByLabelText("Confirm new password"),
      "brand-new-pass-456"
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Change password" })
    )
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/session/password")
    expect(
      new Headers(fetchMock.mock.calls[0][1]?.headers).get("X-CSRF-Protection")
    ).toBe("1")
    expect(onDone).toHaveBeenCalled()
  })

  it("shows weak-password errors from the server", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { detail: { code: "weak_password", message: "Password is too short" } },
        422
      )
    )
    renderWithProviders(<ChangePasswordForm onDone={vi.fn()} />)
    await userEvent.type(
      screen.getByLabelText("Current password"),
      "old-pass-123"
    )
    await userEvent.type(screen.getByLabelText("New password"), "short")
    await userEvent.type(screen.getByLabelText("Confirm new password"), "short")
    await userEvent.click(
      screen.getByRole("button", { name: "Change password" })
    )
    expect(await screen.findByText("Password is too short")).toBeInTheDocument()
  })
})
