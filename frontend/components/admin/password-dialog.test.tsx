import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { PasswordDialog } from "@/components/admin/password-dialog"
import { ApiError } from "@/lib/api"

describe("PasswordDialog", () => {
  it("keeps the dialog open on a wrong password", async () => {
    const onOpenChange = vi.fn()
    const onConfirm = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(
          403,
          "password_confirmation_failed",
          "Re-enter your password to confirm"
        )
      )
      .mockResolvedValueOnce(undefined)
    render(
      <PasswordDialog
        open
        onOpenChange={onOpenChange}
        title="Delete document"
        description="This hides the document from answers."
        confirmLabel="Delete"
        destructive
        onConfirm={onConfirm}
      />
    )
    const input = screen.getByLabelText("Your password")
    await userEvent.type(input, "nope")
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Re-enter your password to confirm"
    )
    expect(onOpenChange).not.toHaveBeenCalled()

    await userEvent.clear(input)
    await userEvent.type(input, "right-password")
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(onConfirm).toHaveBeenLastCalledWith("right-password")
  })
})
