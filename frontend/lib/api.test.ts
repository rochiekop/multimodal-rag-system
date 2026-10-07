import { describe, expect, it, vi } from "vitest"

import { api, apiFetch, ApiError, handleUnauthorized } from "@/lib/api"
import { jsonResponse } from "@/test/render"

describe("apiFetch", () => {
  it("adds the CSRF header to writes but not reads", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({}))
    await apiFetch("/api/x")
    await apiFetch("/api/x", { method: "POST", body: "{}" })
    const headers = fetchMock.mock.calls.map(
      ([, init]) => new Headers(init?.headers)
    )
    expect(headers[0].get("X-CSRF-Protection")).toBeNull()
    expect(headers[1].get("X-CSRF-Protection")).toBe("1")
    expect(headers[1].get("Content-Type")).toBe("application/json")
    expect(fetchMock.mock.calls[1][1]?.credentials).toBe("same-origin")
  })

  it("turns API error bodies into ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { detail: { code: "rate_limited", message: "Slow down" } },
        429
      )
    )
    await expect(
      apiFetch("/api/chat", { method: "POST" })
    ).rejects.toMatchObject({
      status: 429,
      code: "rate_limited",
      message: "Slow down",
    })
  })

  it("maps FastAPI validation errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { detail: [{ msg: "String should have at least 1 character" }] },
        422
      )
    )
    const error = await apiFetch("/api/chat", { method: "POST" }).catch(
      (e) => e
    )
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe("validation_error")
  })

  it("401 clears the session and goes to login", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(null, 204))
    const navigate = vi.fn()
    await handleUnauthorized(navigate)
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({ method: "DELETE" })
    )
    expect(navigate).toHaveBeenCalledWith("/login")
  })

  it("builds conversation search URLs", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse([]))
    await api.conversations("leave & pay")
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/conversations?q=leave%20%26%20pay"
    )
  })
})
