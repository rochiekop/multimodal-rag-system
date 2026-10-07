# Plan 6 — Frontend Foundation & User App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Next.js user app (`/app`) where people sign in, change a forced password, pick collections and ask questions. Answers stream in with sanitized Markdown, `[n]` citation badges (hover preview, click to open the cited page with its region highlighted), a low-confidence badge and clear notices for not-found, blocked and support outcomes. Users can give 👍/👎 with a comment and manage their conversation history (search, rename, delete). Sessions use an httpOnly cookie with CSRF protection.

**Architecture:**
- **Backend:** a small change adds browser session endpoints (`/api/auth/session`). They set an httpOnly `SameSite=Strict` cookie that the auth dependency accepts alongside Bearer tokens. Cookie-authenticated unsafe requests must carry `X-CSRF-Protection: 1`.
- **Frontend:** a fresh `frontend/` app made with the official shadcn CLI: Next.js 16 App Router, TypeScript, Tailwind v4, radix base, nova preset.
  - The browser calls `/api/*` on its own origin. In development, Next `rewrites` forward those calls to FastAPI; in production, Caddy does (Plan 8).
  - `proxy.ts` (Next 16's renamed middleware) sends visitors without a session cookie to `/login`.
  - Small pure modules (`lib/api`, `lib/sse`, `lib/citations`, `lib/bbox`, `lib/chat-state`) hold the logic and are unit-tested with Vitest; components are tested with Testing Library.
- **Testing:** one Playwright smoke test runs against the real stack.

**Tech Stack:** Node 24 / npm 11, `next` 16.x, `react` 19.x, `shadcn` 4.21.4 (radix base, nova preset), Tailwind v4, `@tanstack/react-query` 5, `react-hook-form` 7 + `zod` 4 + `@hookform/resolvers`, `react-markdown` 10 + `remark-gfm` + `rehype-sanitize`, `sonner`, `next-themes`, `lucide-react`; Vitest 5 + jsdom + Testing Library; `@playwright/test`. Backend: FastAPI (existing).

**Spec:** `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md` (§6.4 user app, §6.8 frontend foundation, §5.3 web security, §4.1 citations/streaming, §5.2 low-confidence badge).

## Decisions this plan relies on (made with the user, 2026-10-08)

- **Session = backend httpOnly cookie**, not a Next.js BFF proxy. Bearer tokens keep working for API clients and tests.
- **Plan 6 scope:** the screens plus **one Playwright smoke test**. The frontend Docker service and Caddy come in **Plan 8**.

## Rulings made while planning

- **Browser session endpoints are separate from `/api/auth/login`.**
  - The endpoints: `POST /api/auth/session` (sign in), `DELETE /api/auth/session` (sign out), `POST /api/auth/session/password` (change password and refresh the cookie).
  - They never return the token in the body, so page scripts can't read it, while existing Bearer clients are untouched.
  - Cost if wrong: three small routes.
- **The cookie is `rag_session`:** `HttpOnly`, `SameSite=Strict`, `Path=/` (so `proxy.ts` can see it on page requests), `Secure` when `RAG_ENV=prod` (browsers treat `http://localhost` as secure, so local prod-mode testing still works), `Max-Age` equal to the JWT lifetime (8 h).
- **CSRF:** a cookie-authenticated `POST/PUT/PATCH/DELETE` without the header `X-CSRF-Protection: 1` gets **403 `csrf_required`**. A custom header can't be sent cross-site without CORS, and the API enables no CORS. Bearer requests are exempt.
- **Sign-out only clears the cookie.** Bumping `token_version` would also sign out the user's other devices.
- **Expired or invalid session:** any 401 calls `DELETE /api/auth/session` (to clear a stale cookie and avoid redirect loops), then goes to `/login`.
- **App name** comes from `NEXT_PUBLIC_APP_NAME`, default "Knowledge Assistant". Branding settings are Plan 7.

## Scope limits (deferred, by design)

- Admin console (`/admin`) → **Plan 7**. Frontend Dockerfile, compose service, Caddy and CI → **Plan 8**.
- A message cancelled mid-stream shows its partial text. Resuming isn't supported.
- Office documents have no page preview; their citations show the section and snippet (spec §3.3).

## Global Constraints

- The frontend lives in `frontend/`, created with the **official shadcn CLI** (`npx shadcn@4.21.4 init -t next -n frontend -b radix -p nova --no-monorepo -y`). Components come from the official registry into `frontend/components/ui` (spec §6.8).
- **Next.js 16 differs from older versions.** `frontend/AGENTS.md` says to read `node_modules/next/dist/docs/` before writing Next code. Middleware is now **`proxy.ts`** exporting `proxy()`, and route `params` are Promises in server components.
- Libraries are the ones shadcn uses (spec §6.8): `react-hook-form` + `zod` (forms), `lucide-react` (icons), `sonner` (toasts), `next-themes` (light/dark). Markdown is rendered with `react-markdown` + `rehype-sanitize` (spec §5.3 "sanitized Markdown rendering"). Never use `dangerouslySetInnerHTML`.
- No sign-up and no forgot-password pages (spec §6.8). A user with `must_change_password` is sent to `/change-password` before anything else (spec §6.3).
- User app (spec §6.4):
  - chat with a collection picker, streaming answers, citation cards (page preview + highlight), 👍/👎 with optional comment, low-confidence badge;
  - conversation history (search, rename, delete);
  - source viewer opening the cited page;
  - profile page with password change.
- Session (rulings above): httpOnly `SameSite=Strict` cookie; every unsafe request sends `X-CSRF-Protection: 1`; requests use same-origin credentials only.
- Light/dark mode via shadcn CSS variables and `next-themes` (spec §6.8).
- Frontend checks must pass: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. Backend: the existing pytest suite and ruff stay green.

## Review Focus

1. **An SSE event, or a multi-byte character, split across network chunks** must still parse into the same events and text. Test in Task 2 (`parses events split across chunks and multi-byte characters`).
2. **An answer containing raw HTML or `<script>`** (from a document or the model) must render as inert text, never as markup. Test in Task 5 (`sanitizes html in answers`).
3. **An expired or invalid session cookie** must land the user on `/login` with the cookie cleared, without a redirect loop. Tests in Task 2 (`401 clears the session and goes to login`) and Task 1 (`test_logout_works_without_a_valid_session`).
4. **A refusal before streaming** (423 chat locked, 429 rate or cost limit, 422 too long) must show the server's message in the conversation and leave the composer usable. Test in Task 5 (`shows a refusal from the server and allows asking again`).
5. **Bracketed numbers that aren't citations** (`[2024]`, or `[3]` when there are 2 sources) must stay plain text; only real sources become badges. Test in Task 2 (`only links citations that match a source`).

---

## File structure (new or changed)

```
backend/
  app/core/config.py              # + session_cookie_secure, cookie_secure()            (T1)
  app/auth/session.py             # cookie name, CSRF header, set/clear helpers          (T1)
  app/auth/deps.py                # cookie auth + CSRF check                              (T1)
  app/api/auth.py                 # /auth/session POST, DELETE; /auth/session/password    (T1)
  tests/test_session_auth.py, tests/test_auth.py (PUBLIC_ROUTES)                         (T1)
frontend/                         # created by the shadcn CLI                             (T2)
  next.config.ts                  # /api rewrites to BACKEND_URL, compress off            (T2)
  proxy.ts                        # no session cookie -> /login                           (T2)
  vitest.config.mts, vitest.setup.ts, test/render.tsx                                    (T2)
  lib/config.ts, lib/types.ts, lib/api.ts, lib/sse.ts, lib/citations.ts, lib/bbox.ts,
  lib/chat-state.ts (+ *.test.ts)                                                        (T2)
  components/providers.tsx        # theme, query client, tooltips, toaster               (T2)
  app/layout.tsx, app/page.tsx                                                           (T2)
  components/auth/login-form.tsx, change-password-form.tsx (+ tests)                     (T3)
  app/login/page.tsx, app/change-password/page.tsx                                       (T3)
  components/app-sidebar.tsx, conversation-list.tsx, user-menu.tsx (+ test)              (T4)
  app/app/layout.tsx, app/app/profile/page.tsx                                           (T4)
  hooks/use-chat.ts                                                                      (T5)
  components/chat/chat-view.tsx, chat-panel.tsx, message-list.tsx, assistant-message.tsx,
  markdown.tsx, citation-badge.tsx, source-card.tsx, source-viewer.tsx, feedback-buttons.tsx,
  composer.tsx, collection-picker.tsx (+ tests)                                          (T5)
  app/app/page.tsx, app/app/c/[id]/page.tsx                                              (T5)
  playwright.config.ts, e2e/smoke.spec.ts                                                (T6)
```

---

### Task 1: Backend browser session — httpOnly cookie + CSRF

**Files:**
- Create: `backend/app/auth/session.py`, `backend/tests/test_session_auth.py`
- Modify: `backend/app/core/config.py`, `backend/app/auth/deps.py`, `backend/app/api/auth.py`, `backend/tests/test_auth.py`

**Interfaces:**
- Produces:
  - Constants `SESSION_COOKIE = "rag_session"` and `CSRF_HEADER = "X-CSRF-Protection"`, plus `set_session_cookie(response, token, settings)` and `clear_session_cookie(response, settings)`.
  - `Settings.session_cookie_secure: bool | None = None` and `Settings.cookie_secure() -> bool`.
  - Routes:
    - `POST /api/auth/session` (public) → `SessionOut {must_change_password, user}` plus the cookie
    - `DELETE /api/auth/session` (public) → 204, cookie cleared
    - `POST /api/auth/session/password` (authenticated, allowed while a password change is pending) → `SessionOut` plus a new cookie
  - The auth dependency accepts a Bearer header, else the cookie. Cookie + unsafe method + no `X-CSRF-Protection: 1` → 403 `csrf_required`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_session_auth.py`

```python
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

CSRF = {"X-CSRF-Protection": "1"}


async def _sign_in(client: AsyncClient, username: str = "alice"):
    return await client.post(
        "/api/auth/session", json={"username": username, "password": DEFAULT_PASSWORD}
    )


async def test_sign_in_sets_an_httponly_strict_cookie_and_hides_the_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    response = await _sign_in(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" not in body
    assert body["user"]["username"] == "alice" and body["must_change_password"] is False
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("rag_session=")
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "max-age=28800" in cookie
    assert "secure" not in cookie  # settings fixture runs with env=test


async def test_cookie_authenticates_reads_and_csrf_guards_writes(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    await _sign_in(client)  # the client keeps the cookie
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "alice"

    url = f"/api/messages/{uuid.uuid4()}/feedback"
    blocked = await client.post(url, json={"rating": 1})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "csrf_required"
    allowed = await client.post(url, json={"rating": 1}, headers=CSRF)
    assert allowed.status_code == 404  # passed auth + CSRF; the message just doesn't exist


async def test_bearer_requests_need_no_csrf_header(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    token = await login(client, "alice")
    client.cookies.clear()
    response = await client.post(
        f"/api/messages/{uuid.uuid4()}/feedback", json={"rating": 1}, headers=bearer(token)
    )
    assert response.status_code == 404


async def test_sign_out_clears_the_cookie(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    await _sign_in(client)
    out = await client.delete("/api/auth/session")
    assert out.status_code == 204
    assert "rag_session=" in out.headers["set-cookie"].lower()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_works_without_a_valid_session(client: AsyncClient) -> None:
    client.cookies.set("rag_session", "garbage")
    out = await client.delete("/api/auth/session")
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_bad_credentials_set_no_cookie(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    response = await client.post(
        "/api/auth/session", json={"username": "alice", "password": "wrong"}
    )
    assert response.status_code == 401 and "set-cookie" not in response.headers


async def test_forced_password_change_refreshes_the_cookie(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="newbie", must_change_password=True)
    first = await _sign_in(client, "newbie")
    assert first.json()["must_change_password"] is True
    old_token = client.cookies.get("rag_session")
    assert (await client.get("/api/collections")).status_code == 403  # change required first

    changed = await client.post(
        "/api/auth/session/password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "a-much-better-pass-99"},
        headers=CSRF,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change_password"] is False
    assert client.cookies.get("rag_session") != old_token
    assert (await client.get("/api/collections")).status_code == 200
    stale = await client.get("/api/auth/me", headers=bearer(str(old_token)))
    assert stale.status_code == 401  # the old token was revoked by the change
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_session_auth.py -v`
Expected: FAIL (404/405 for `/api/auth/session`)

- [ ] **Step 3: Implement**

`backend/app/core/config.py` — add a field after `jwt_ttl_seconds` and a method on `Settings`:

```python
    session_cookie_secure: bool | None = None  # None: secure only when env == "prod"

    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.env == "prod"
```

`backend/app/auth/session.py`:

```python
"""Browser sessions: the JWT lives in an httpOnly cookie that page scripts can't read.
Cookie-authenticated writes must carry a custom header, which a cross-site page can't send
without CORS (the API enables none)."""

from fastapi import Response

from app.core.config import Settings

SESSION_COOKIE = "rag_session"
CSRF_HEADER = "X-CSRF-Protection"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure(),
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.cookie_secure(),
        samesite="strict",
        path="/",
    )
```

`backend/app/auth/deps.py` — change `current_user_allow_password_change` to read the cookie when there's no Bearer header (add `from fastapi import Request` and the session imports):

```python
async def current_user_allow_password_change(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Any authenticated, active user, including one who still must change their password.
    Bearer header first; otherwise the session cookie, whose writes need the CSRF header."""
    if credentials is not None:
        token: str | None = credentials.credentials
    else:
        token = request.cookies.get(SESSION_COOKIE)
        if (
            token is not None
            and request.method in UNSAFE_METHODS
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            raise api_error(403, "csrf_required", "Missing CSRF protection header")
    if token is None:
        raise api_error(401, "not_authenticated", "Missing bearer token", headers=_WWW_AUTH)
    try:
        user_id, token_version = decode_access_token(token, settings)
    except TokenError:
        raise api_error(
            401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH
        ) from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.token_version != token_version:
        raise api_error(401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH)
    return user
```

`backend/app/api/auth.py`:
- Move the login error mapping into `async def _authenticate(body, session, settings) -> User`, which raises the same `api_error`s and commits exactly as `login` does today.
- `login` calls it unchanged in behaviour.
- Add the routes below (imports: `Response`, `clear_session_cookie`, `set_session_cookie`):

```python
class SessionOut(BaseModel):
    must_change_password: bool
    user: UserOut


@router.post("/session")
async def create_session(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> SessionOut:
    """Browser sign-in: the token goes into an httpOnly cookie, never into the body."""
    user = await _authenticate(body, session, settings)
    set_session_cookie(response, create_access_token(user, settings), settings)
    return SessionOut(
        must_change_password=user.must_change_password, user=UserOut.model_validate(user)
    )


@router.delete("/session", status_code=204)
async def delete_session(settings: SettingsDep) -> Response:
    """Sign out: clears the cookie. Public, so a stale or invalid cookie can always be cleared."""
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.post("/session/password")
async def change_session_password(
    body: ChangePasswordRequest,
    user: PendingUser,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> SessionOut:
    try:
        await change_password(
            session, user=user, current_password=body.current_password,
            new_password=body.new_password,
        )
    except InvalidCredentials as exc:
        raise api_error(400, exc.code, "Current password is incorrect") from None
    except WeakPasswordError as exc:
        raise api_error(422, "weak_password", str(exc)) from None
    await session.commit()
    set_session_cookie(response, create_access_token(user, settings), settings)
    return SessionOut(
        must_change_password=user.must_change_password, user=UserOut.model_validate(user)
    )
```

`backend/tests/test_auth.py` — extend `PUBLIC_ROUTES`:

```python
PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/session"),
    ("DELETE", "/api/auth/session"),
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_session_auth.py tests/test_auth.py -v`, then `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(auth): browser session cookie with csrf protection"
```

---

### Task 2: Frontend foundation — scaffold, tooling, core libraries

**Files:**
- Create: `frontend/` (via the CLI), plus `frontend/vitest.config.mts`, `frontend/vitest.setup.ts`, `frontend/test/render.tsx`, `frontend/proxy.ts`, `frontend/components/providers.tsx`, `frontend/lib/{config,types,api,sse,citations,bbox,chat-state}.ts` and their `*.test.ts`
- Modify (generated): `frontend/next.config.ts`, `frontend/app/layout.tsx`, `frontend/app/page.tsx`, `frontend/package.json`

**Interfaces:**
- Produces (used by later tasks):
  - `lib/config.ts`: `APP_NAME`.
  - `lib/types.ts`: `User`, `Group`, `SessionInfo`, `Collection`, `Conversation`, `ConversationDetail`, `Message`, `SourceCard`, `Bbox`, `Outcome`, `ChatEvent`.
  - `lib/api.ts`: `ApiError(status, code, message)`, `apiFetch(path, init)`, `apiJson<T>(path, init)`, `handleUnauthorized()`, `pageImageUrl(docId, page)`, and the `api` object (`me`, `login`, `logout`, `changePassword`, `collections`, `conversations(q?)`, `conversation(id)`, `renameConversation(id, title)`, `deleteConversation(id)`, `feedback(messageId, rating, comment?)`).
  - `lib/sse.ts`: `parseSSE(stream)`, `streamChat(body, signal)`.
  - `lib/citations.ts`: `linkCitations(markdown, sourceNumbers: Set<number>)`, `CITATION_HREF_PREFIX = "#cite-"`.
  - `lib/bbox.ts`: `highlightBox(bbox, pageImageScale, naturalWidth, renderedWidth)`.
  - `lib/chat-state.ts`: `ChatState`, `ChatAction`, `UIMessage`, `chatReducer`, `initialChatState(conversationId, messages)`.
  - `components/providers.tsx`: `Providers`.
  - `test/render.tsx`: `renderWithProviders(ui)`, `jsonResponse(body, status?)`.

- [ ] **Step 1: Scaffold with the official CLI** (from the repo root)

```bash
npx -y shadcn@4.21.4 init -t next -n frontend -b radix -p nova --no-monorepo -y
cd frontend
npx shadcn@4.21.4 add -y sidebar scroll-area textarea card avatar hover-card sheet sonner field input label badge skeleton dropdown-menu tooltip dialog alert alert-dialog separator
npm install @tanstack/react-query react-hook-form zod @hookform/resolvers react-markdown remark-gfm rehype-sanitize
npm install -D vitest @vitejs/plugin-react vite-tsconfig-paths jsdom @testing-library/react @testing-library/dom @testing-library/jest-dom @testing-library/user-event
```

Read `frontend/AGENTS.md` and skim `node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md` and `.../02-guides/testing/vitest.md` before writing code. Delete the CLI's demo `app/login/page.tsx` and `components/login-form.tsx` if the `add` step created them; Task 3 writes its own. Add to `package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 2: Tooling files**

`frontend/vitest.config.mts`:

```ts
import react from "@vitejs/plugin-react"
import tsconfigPaths from "vite-tsconfig-paths"
import { defineConfig } from "vitest/config"

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
  },
})
```

`frontend/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterEach, vi } from "vitest"

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// jsdom lacks these; radix and the sidebar's mobile hook use them.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
Element.prototype.scrollIntoView ??= function scrollIntoView() {}
```

`frontend/test/render.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render } from "@testing-library/react"
import type { ReactElement } from "react"

import { TooltipProvider } from "@/components/ui/tooltip"

export function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>
  )
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}
```

`frontend/next.config.ts`:

```ts
import type { NextConfig } from "next"

// Development and `next start`: forward the API to FastAPI. In production Caddy routes /api
// straight to the backend (Plan 8). Rewrites are fixed at build time.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000"

const nextConfig: NextConfig = {
  compress: false, // never buffer the answer stream; Caddy compresses in production
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]
  },
}

export default nextConfig
```

`frontend/proxy.ts`:

```ts
import { NextResponse, type NextRequest } from "next/server"

const SESSION_COOKIE = "rag_session"

// Only checks that a session cookie exists; the API decides whether it is valid.
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next()
  }
  const login = new URL("/login", request.url)
  login.searchParams.set("next", request.nextUrl.pathname)
  return NextResponse.redirect(login)
}

export const config = {
  matcher: ["/app/:path*", "/change-password"],
}
```

- [ ] **Step 3: Write the failing library tests**

`frontend/lib/sse.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest"

import { parseSSE, streamChat } from "@/lib/sse"

function streamOf(...chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk)
      }
      controller.close()
    },
  })
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = []
  for await (const item of iterable) out.push(item)
  return out
}

describe("parseSSE", () => {
  it("parses events split across chunks and multi-byte characters", async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"café"}\n\n')
    const cut = bytes.indexOf(0xc3) + 1 // split inside the two-byte "é"
    const events = await collect(
      parseSSE(
        streamOf(
          "event: meta\nda",
          'ta: {"conversation_id":"c1"}\n',
          "\n",
          bytes.slice(0, cut),
          bytes.slice(cut)
        )
      )
    )
    expect(events).toEqual([
      { event: "meta", data: '{"conversation_id":"c1"}' },
      { event: "token", data: '{"text":"café"}' },
    ])
  })

  it("handles CRLF line endings, comments and a final event without blank line", async () => {
    const events = await collect(
      parseSSE(streamOf(": keepalive\r\nevent: done\r\ndata: {}\r\n\r\nevent: x\ndata: 1"))
    )
    expect(events).toEqual([
      { event: "done", data: "{}" },
      { event: "x", data: "1" },
    ])
  })
})

describe("streamChat", () => {
  it("posts with the CSRF header and yields typed events", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(streamOf('event: token\ndata: {"text":"Hi"}\n\n'), { status: 200 })
    )
    const events = await collect(streamChat({ question: "q" }))
    expect(events).toEqual([{ event: "token", data: { text: "Hi" } }])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/chat")
    expect(new Headers(init?.headers).get("X-CSRF-Protection")).toBe("1")
  })
})
```

`frontend/lib/api.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest"

import { api, apiFetch, ApiError, handleUnauthorized } from "@/lib/api"
import { jsonResponse } from "@/test/render"

describe("apiFetch", () => {
  it("adds the CSRF header to writes but not reads", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}))
    await apiFetch("/api/x")
    await apiFetch("/api/x", { method: "POST", body: "{}" })
    const headers = fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers))
    expect(headers[0].get("X-CSRF-Protection")).toBeNull()
    expect(headers[1].get("X-CSRF-Protection")).toBe("1")
    expect(headers[1].get("Content-Type")).toBe("application/json")
    expect(fetchMock.mock.calls[1][1]?.credentials).toBe("same-origin")
  })

  it("turns API error bodies into ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ detail: { code: "rate_limited", message: "Slow down" } }, 429)
    )
    await expect(apiFetch("/api/chat", { method: "POST" })).rejects.toMatchObject({
      status: 429,
      code: "rate_limited",
      message: "Slow down",
    })
  })

  it("maps FastAPI validation errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ detail: [{ msg: "String should have at least 1 character" }] }, 422)
    )
    const error = await apiFetch("/api/chat", { method: "POST" }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe("validation_error")
  })

  it("401 clears the session and goes to login", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(null, 204))
    const navigate = vi.fn()
    await handleUnauthorized(navigate)
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({ method: "DELETE" })
    )
    expect(navigate).toHaveBeenCalledWith("/login")
  })

  it("builds conversation search URLs", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse([]))
    await api.conversations("leave & pay")
    expect(fetchMock.mock.calls[0][0]).toBe("/api/conversations?q=leave%20%26%20pay")
  })
})
```

`frontend/lib/citations.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { linkCitations } from "@/lib/citations"

describe("linkCitations", () => {
  it("only links citations that match a source", () => {
    const text = "Leave is 25 days [1][2]. Since [2024] see [3]."
    expect(linkCitations(text, new Set([1, 2]))).toBe(
      "Leave is 25 days [1](#cite-1)[2](#cite-2). Since [2024] see [3]."
    )
  })

  it("leaves text without citations alone", () => {
    expect(linkCitations("Nothing here.", new Set([1]))).toBe("Nothing here.")
  })
})
```

`frontend/lib/bbox.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { highlightBox } from "@/lib/bbox"

describe("highlightBox", () => {
  it("maps page points to rendered pixels", () => {
    // 1.5 px per point in the PNG; PNG is 1500px wide, rendered at 750px -> 0.75 px per point.
    expect(highlightBox({ l: 10, t: 20, r: 110, b: 70 }, 1.5, 1500, 750)).toEqual({
      left: 7.5,
      top: 15,
      width: 75,
      height: 37.5,
    })
  })
})
```

`frontend/lib/chat-state.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { chatReducer, initialChatState } from "@/lib/chat-state"
import type { ChatEvent, SourceCard } from "@/lib/types"

const card: SourceCard = {
  n: 1, doc_id: "d1", version_id: "v1", filename: "handbook.pdf", page: 1,
  bbox: { l: 1, t: 2, r: 3, b: 4 }, page_image_scale: 1.5, heading_path: ["Leave"],
  modality: "text", score: 0.9, snippet: "Annual leave is 25 days.",
}

function ask() {
  return chatReducer(initialChatState(null, []), { type: "ask", question: "Leave?", tempId: "t1" })
}

describe("chatReducer", () => {
  it("streams an answer and replaces it with the final content", () => {
    let state = ask()
    expect(state.streaming).toBe(true)
    expect(state.messages.map((m) => m.role)).toEqual(["user", "assistant"])
    const events: ChatEvent[] = [
      { event: "meta", data: { conversation_id: "c1", user_message_id: "u1" } },
      { event: "sources", data: { sources: [card] } },
      { event: "token", data: { text: "Annual leave is " } },
      { event: "token", data: { text: "25 days [1] [9]" } },
      {
        event: "done",
        data: {
          message_id: "m1", content: "Annual leave is 25 days [1]", outcome: "answered",
          citations: [card], low_confidence: true, trace_id: null,
        },
      },
    ]
    for (const event of events) state = chatReducer(state, { type: "event", event, tempId: "t1" })
    expect(state.conversationId).toBe("c1")
    expect(state.streaming).toBe(false)
    const [question, answer] = state.messages
    expect(question.id).toBe("u1")
    expect(answer).toMatchObject({
      id: "m1", content: "Annual leave is 25 days [1]", outcome: "answered",
      low_confidence: true, streaming: false,
    })
    expect(answer.sources).toEqual([card])
  })

  it("records an error event", () => {
    const state = chatReducer(ask(), {
      type: "event",
      event: { event: "error", data: { code: "answer_failed", message: "Try again", message_id: "m2" } },
      tempId: "t1",
    })
    expect(state.messages[1]).toMatchObject({ id: "m2", outcome: "error", content: "Try again" })
    expect(state.streaming).toBe(false)
  })

  it("shows a refusal from the server and allows asking again", () => {
    const state = chatReducer(ask(), { type: "fail", tempId: "t1", message: "Chat is locked" })
    expect(state.messages[1]).toMatchObject({ outcome: "error", content: "Chat is locked" })
    expect(state.streaming).toBe(false)
  })

  it("keeps partial text when the user stops", () => {
    let state = chatReducer(ask(), {
      type: "event", event: { event: "token", data: { text: "Partial" } }, tempId: "t1",
    })
    state = chatReducer(state, { type: "stopped", tempId: "t1" })
    expect(state.messages[1]).toMatchObject({ content: "Partial", outcome: "cancelled" })
  })

  it("adds a strike notice to blocked answers", () => {
    const state = chatReducer(ask(), {
      type: "event",
      event: {
        event: "done",
        data: {
          message_id: "m3", content: "I can't help with that request.", outcome: "blocked",
          citations: [], low_confidence: false, trace_id: null, strikes: 2, strike_limit: 3,
          locked_until: null,
        },
      },
      tempId: "t1",
    })
    expect(state.messages[1].notice).toBe(
      "This request broke the usage policy (2 of 3 warnings)."
    )
  })
})
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (cannot resolve `@/lib/sse`, `@/lib/api`, …)

- [ ] **Step 5: Implement the libraries**

`frontend/lib/config.ts`:

```ts
export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Knowledge Assistant"
```

`frontend/lib/types.ts`:

```ts
// Mirrors the backend response schemas (app/*/schemas.py).
export type Role = "user" | "admin" | "super_admin"

export interface Group {
  id: string
  name: string
  description: string
}

export interface User {
  id: string
  username: string
  full_name: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  groups: Group[]
}

export interface SessionInfo {
  must_change_password: boolean
  user: User
}

export interface Collection {
  id: string
  name: string
  description: string
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Bbox {
  l: number
  t: number
  r: number
  b: number
}

export interface SourceCard {
  n: number
  doc_id: string
  version_id: string
  filename: string
  page: number | null
  bbox: Bbox | null
  page_image_scale: number | null
  heading_path: string[]
  modality: string
  score: number
  snippet: string
}

export type Outcome =
  | "answered"
  | "not_found"
  | "blocked"
  | "support"
  | "off_topic"
  | "error"
  | "cancelled"

export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  outcome: Outcome | null
  sources: SourceCard[]
  citations: SourceCard[]
  low_confidence: boolean
  feedback_rating: 1 | -1 | null
  feedback_comment: string | null
  created_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface DoneData {
  message_id: string
  content: string
  outcome: Outcome
  citations: SourceCard[]
  low_confidence: boolean
  trace_id: string | null
  strikes?: number
  strike_limit?: number
  locked_until?: string | null
}

export type ChatEvent =
  | { event: "meta"; data: { conversation_id: string; user_message_id: string } }
  | { event: "sources"; data: { sources: SourceCard[] } }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: DoneData }
  | { event: "error"; data: { code: string; message: string; message_id?: string } }
```

`frontend/lib/api.ts`:

```ts
import type {
  Collection,
  Conversation,
  ConversationDetail,
  Message,
  SessionInfo,
  User,
} from "@/lib/types"

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"])
export const CSRF_HEADER = "X-CSRF-Protection"

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error"
  let message = `Request failed (${response.status})`
  try {
    const body = await response.json()
    const detail = body?.detail
    if (Array.isArray(detail)) {
      code = "validation_error"
      message = detail[0]?.msg ?? message
    } else if (detail && typeof detail === "object") {
      code = detail.code ?? code
      message = detail.message ?? message
    }
  } catch {
    // non-JSON error body: keep the generic message
  }
  return new ApiError(response.status, code, message)
}

/** Same-origin fetch that adds the CSRF header to writes and throws ApiError on failure. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase()
  const headers = new Headers(init.headers)
  if (UNSAFE.has(method)) headers.set(CSRF_HEADER, "1")
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(path, { ...init, method, headers, credentials: "same-origin" })
  if (!response.ok) throw await toApiError(response)
  return response
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Clear a stale cookie (so /login can't bounce back) and go to the sign-in page. */
export async function handleUnauthorized(
  navigate: (url: string) => void = (url) => window.location.assign(url)
): Promise<void> {
  try {
    await fetch("/api/auth/session", {
      method: "DELETE",
      headers: { [CSRF_HEADER]: "1" },
      credentials: "same-origin",
    })
  } catch {
    // offline: still go to the sign-in page
  } finally {
    navigate("/login")
  }
}

export const pageImageUrl = (docId: string, page: number) =>
  `/api/documents/${docId}/pages/${page}`

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) })

export const api = {
  me: () => apiJson<User>("/api/auth/me"),
  login: (username: string, password: string) =>
    apiJson<SessionInfo>("/api/auth/session", post({ username, password })),
  logout: () => apiJson<void>("/api/auth/session", { method: "DELETE" }),
  changePassword: (current_password: string, new_password: string) =>
    apiJson<SessionInfo>("/api/auth/session/password", post({ current_password, new_password })),
  collections: () => apiJson<Collection[]>("/api/collections"),
  conversations: (q?: string) =>
    apiJson<Conversation[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  conversation: (id: string) => apiJson<ConversationDetail>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    apiJson<Conversation>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    apiJson<void>(`/api/conversations/${id}`, { method: "DELETE" }),
  feedback: (messageId: string, rating: 1 | -1, comment?: string) =>
    apiJson<Message>(`/api/messages/${messageId}/feedback`, post({ rating, comment })),
}
```

`frontend/lib/sse.ts`:

```ts
import { apiFetch, ApiError } from "@/lib/api"
import type { ChatEvent } from "@/lib/types"

export interface SSEMessage {
  event: string
  data: string
}

function parseBlock(block: string): SSEMessage | null {
  let event = "message"
  const data: string[] = []
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue
    const colon = line.indexOf(":")
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? "" : line.slice(colon + 1)
    if (value.startsWith(" ")) value = value.slice(1)
    if (field === "event") event = value
    else if (field === "data") data.push(value)
  }
  return data.length ? { event, data: data.join("\n") } : null
}

/** Server-Sent Events from a byte stream; safe across chunk and UTF-8 boundaries. */
export async function* parseSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<SSEMessage> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
      let index = buffer.indexOf("\n\n")
      while (index !== -1) {
        const message = parseBlock(buffer.slice(0, index))
        buffer = buffer.slice(index + 2)
        if (message) yield message
        index = buffer.indexOf("\n\n")
      }
    }
    buffer += decoder.decode().replace(/\r\n/g, "\n")
    const tail = parseBlock(buffer.trim())
    if (tail) yield tail
  } finally {
    reader.releaseLock()
  }
}

export interface ChatRequest {
  question: string
  conversation_id?: string
  collection_ids?: string[]
}

export async function* streamChat(
  body: ChatRequest,
  signal?: AbortSignal
): AsyncGenerator<ChatEvent> {
  const response = await apiFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { Accept: "text/event-stream" },
    signal,
  })
  if (!response.body) throw new ApiError(502, "no_stream", "The server sent no answer stream")
  for await (const message of parseSSE(response.body)) {
    yield { event: message.event, data: JSON.parse(message.data) } as ChatEvent
  }
}
```

`frontend/lib/citations.ts`:

```ts
export const CITATION_HREF_PREFIX = "#cite-"
const CITATION = /\[(\d+)\]/g

/** Turn "[n]" into a Markdown link only when n is one of this answer's sources. */
export function linkCitations(markdown: string, sourceNumbers: Set<number>): string {
  return markdown.replace(CITATION, (match, digits: string) => {
    const n = Number(digits)
    return sourceNumbers.has(n) ? `[${n}](${CITATION_HREF_PREFIX}${n})` : match
  })
}
```

`frontend/lib/bbox.ts`:

```ts
import type { Bbox } from "@/lib/types"

/** Bbox is in page points (top-left origin); the page PNG has pageImageScale px per point. */
export function highlightBox(
  bbox: Bbox,
  pageImageScale: number,
  naturalWidth: number,
  renderedWidth: number
) {
  const ratio = (pageImageScale * renderedWidth) / naturalWidth
  return {
    left: bbox.l * ratio,
    top: bbox.t * ratio,
    width: (bbox.r - bbox.l) * ratio,
    height: (bbox.b - bbox.t) * ratio,
  }
}
```

`frontend/lib/chat-state.ts`:

```ts
import type { ChatEvent, DoneData, Message } from "@/lib/types"

export type UIMessage = Message & { streaming?: boolean; notice?: string }

export interface ChatState {
  conversationId: string | null
  messages: UIMessage[]
  streaming: boolean
}

export type ChatAction =
  | { type: "load"; conversationId: string | null; messages: Message[] }
  | { type: "ask"; question: string; tempId: string }
  | { type: "event"; event: ChatEvent; tempId: string }
  | { type: "fail"; message: string; tempId: string }
  | { type: "stopped"; tempId: string }

export function initialChatState(conversationId: string | null, messages: Message[]): ChatState {
  return { conversationId, messages, streaming: false }
}

function blank(id: string, role: Message["role"], content: string): UIMessage {
  return {
    id, role, content, outcome: null, sources: [], citations: [], low_confidence: false,
    feedback_rating: null, feedback_comment: null, created_at: new Date().toISOString(),
  }
}

function strikeNotice(data: DoneData): string | undefined {
  if (data.strikes === undefined) return undefined
  const base = `This request broke the usage policy (${data.strikes} of ${data.strike_limit} warnings).`
  return data.locked_until
    ? `${base} Chat is locked until ${new Date(data.locked_until).toLocaleString()}.`
    : base
}

function updateAnswer(
  state: ChatState,
  tempId: string,
  change: (message: UIMessage) => UIMessage
): UIMessage[] {
  return state.messages.map((m) => (m.id === tempId ? change(m) : m))
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "load":
      return initialChatState(action.conversationId, action.messages)
    case "ask":
      return {
        ...state,
        streaming: true,
        messages: [
          ...state.messages,
          blank(`${action.tempId}-q`, "user", action.question),
          { ...blank(action.tempId, "assistant", ""), streaming: true },
        ],
      }
    case "stopped":
      return {
        ...state,
        streaming: false,
        messages: updateAnswer(state, action.tempId, (m) => ({
          ...m, streaming: false, outcome: "cancelled",
        })),
      }
    case "fail":
      return {
        ...state,
        streaming: false,
        messages: updateAnswer(state, action.tempId, (m) => ({
          ...m, streaming: false, outcome: "error", content: action.message,
        })),
      }
    case "event": {
      const { event, tempId } = action
      switch (event.event) {
        case "meta":
          return {
            ...state,
            conversationId: event.data.conversation_id,
            messages: state.messages.map((m) =>
              m.id === `${tempId}-q` ? { ...m, id: event.data.user_message_id } : m
            ),
          }
        case "sources":
          return {
            ...state,
            messages: updateAnswer(state, tempId, (m) => ({ ...m, sources: event.data.sources })),
          }
        case "token":
          return {
            ...state,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m, content: m.content + event.data.text,
            })),
          }
        case "done":
          return {
            ...state,
            streaming: false,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m,
              id: event.data.message_id,
              content: event.data.content,
              outcome: event.data.outcome,
              citations: event.data.citations,
              low_confidence: event.data.low_confidence,
              streaming: false,
              notice: strikeNotice(event.data),
            })),
          }
        case "error":
          return {
            ...state,
            streaming: false,
            messages: updateAnswer(state, tempId, (m) => ({
              ...m,
              id: event.data.message_id ?? m.id,
              content: event.data.message,
              outcome: "error",
              streaming: false,
            })),
          }
      }
    }
  }
  return state
}
```

`frontend/components/providers.tsx`:

```tsx
"use client"

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState, type ReactNode } from "react"

import { ThemeProvider } from "@/components/theme-provider"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError, handleUnauthorized } from "@/lib/api"

function onApiError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) void handleUnauthorized()
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({ onError: onApiError }),
        mutationCache: new MutationCache({ onError: onApiError }),
        defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
      })
  )
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster richColors position="top-center" />
      </QueryClientProvider>
    </ThemeProvider>
  )
}
```

`frontend/app/layout.tsx` — keep the CLI's fonts and `<html suppressHydrationWarning>`. Wrap `{children}` in `<Providers>` instead of `<ThemeProvider>`, and set `export const metadata = { title: APP_NAME, description: "Answers from your company's documents" }`.

`frontend/app/page.tsx`:

```tsx
import { redirect } from "next/navigation"

export default function Home() {
  redirect("/app")
}
```

- [ ] **Step 6: Run the checks**

Run: `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`
Expected: all library tests PASS, and lint, typecheck and build succeed. The build may warn that `/app` doesn't exist yet; it is created in Task 4.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat(frontend): next.js + shadcn foundation with api, sse, citation and chat-state libraries"
```

---

### Task 3: Sign-in, forced password change, sign-out

**Files:**
- Create: `frontend/components/auth/login-form.tsx`, `frontend/components/auth/change-password-form.tsx`, `frontend/components/auth/auth-layout.tsx`, `frontend/app/login/page.tsx`, `frontend/app/change-password/page.tsx`, `frontend/components/auth/login-form.test.tsx`, `frontend/components/auth/change-password-form.test.tsx`

**Interfaces:**
- Consumes: `api.login`, `api.changePassword`, `ApiError`, `APP_NAME`; shadcn `Card`, `Field*`, `Input`, `Button`, `Alert`.
- Produces: `LoginForm` (`next` prop: path to go to after sign-in), `ChangePasswordForm` (`onDone(info: SessionInfo)`, `requireCurrent` flag), `AuthLayout` (layout from the login-03 block).

- [ ] **Step 1: Write the failing tests**

`frontend/components/auth/login-form.test.tsx`:

```tsx
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { LoginForm } from "@/components/auth/login-form"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }))

const user = { id: "u1", username: "alice", full_name: "Alice", role: "user",
  is_active: true, must_change_password: false, groups: [] }

describe("LoginForm", () => {
  beforeEach(() => replace.mockReset())

  it("signs in and goes to the requested page", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ must_change_password: false, user })
    )
    renderWithProviders(<LoginForm next="/app/c/123" />)
    await userEvent.type(screen.getByLabelText("Username"), "alice")
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass")
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/session")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      username: "alice", password: "secret-pass",
    })
    expect(replace).toHaveBeenCalledWith("/app/c/123")
  })

  it("sends users who must change their password there first", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ must_change_password: true, user: { ...user, must_change_password: true } })
    )
    renderWithProviders(<LoginForm next="/app" />)
    await userEvent.type(screen.getByLabelText("Username"), "alice")
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass")
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(replace).toHaveBeenCalledWith("/change-password")
  })

  it("shows the server's error and ignores unsafe next paths", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ detail: { code: "invalid_credentials", message: "Invalid username or password" } }, 401)
    )
    renderWithProviders(<LoginForm next="https://evil.example" />)
    await userEvent.type(screen.getByLabelText("Username"), "alice")
    await userEvent.type(screen.getByLabelText("Password"), "nope")
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument()
    expect(replace).not.toHaveBeenCalled()
  })

  it("requires both fields", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
    renderWithProviders(<LoginForm next="/app" />)
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(await screen.findByText("Enter your username")).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
```

Add a fifth test inside the `describe`:

```tsx
  it("ignores next paths that aren't local", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ must_change_password: false, user })
    )
    renderWithProviders(<LoginForm next="//evil.example/app" />)
    await userEvent.type(screen.getByLabelText("Username"), "alice")
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass")
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect(replace).toHaveBeenCalledWith("/app")
  })
```

`frontend/components/auth/change-password-form.test.tsx`:

```tsx
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ChangePasswordForm } from "@/components/auth/change-password-form"
import { jsonResponse, renderWithProviders } from "@/test/render"

describe("ChangePasswordForm", () => {
  it("checks the confirmation and calls the session password endpoint", async () => {
    const onDone = vi.fn()
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ must_change_password: false, user: { id: "u1", username: "alice" } })
    )
    renderWithProviders(<ChangePasswordForm onDone={onDone} />)
    await userEvent.type(screen.getByLabelText("Current password"), "old-pass-123")
    await userEvent.type(screen.getByLabelText("New password"), "brand-new-pass-456")
    await userEvent.type(screen.getByLabelText("Confirm new password"), "different-pass-789")
    await userEvent.click(screen.getByRole("button", { name: "Change password" }))
    expect(await screen.findByText("Passwords don't match")).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()

    await userEvent.clear(screen.getByLabelText("Confirm new password"))
    await userEvent.type(screen.getByLabelText("Confirm new password"), "brand-new-pass-456")
    await userEvent.click(screen.getByRole("button", { name: "Change password" }))
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/session/password")
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("X-CSRF-Protection")).toBe("1")
    expect(onDone).toHaveBeenCalled()
  })

  it("shows weak-password errors from the server", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ detail: { code: "weak_password", message: "Password is too short" } }, 422)
    )
    renderWithProviders(<ChangePasswordForm onDone={vi.fn()} />)
    await userEvent.type(screen.getByLabelText("Current password"), "old-pass-123")
    await userEvent.type(screen.getByLabelText("New password"), "short")
    await userEvent.type(screen.getByLabelText("Confirm new password"), "short")
    await userEvent.click(screen.getByRole("button", { name: "Change password" }))
    expect(await screen.findByText("Password is too short")).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run components/auth`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement**

`frontend/components/auth/auth-layout.tsx` (the official `login-03` block's layout, with the product name):

```tsx
import { MessagesSquareIcon } from "lucide-react"
import type { ReactNode } from "react"

import { APP_NAME } from "@/lib/config"

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center gap-2 self-center font-medium">
          <div className="flex size-6 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <MessagesSquareIcon className="size-4" />
          </div>
          {APP_NAME}
        </div>
        {children}
      </div>
    </div>
  )
}
```

`frontend/components/auth/login-form.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"

const schema = z.object({
  username: z.string().trim().min(1, "Enter your username"),
  password: z.string().min(1, "Enter your password"),
})
type Values = z.infer<typeof schema>

/** Only same-site paths are allowed as the post-login destination. */
export function safeNext(next: string | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/app"
}

export function LoginForm({ next }: { next?: string }) {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", password: "" },
  })

  async function onSubmit(values: Values) {
    setError(null)
    try {
      const info = await api.login(values.username, values.password)
      router.replace(info.must_change_password ? "/change-password" : safeNext(next))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server")
    }
  }

  const { errors, isSubmitting } = form.formState
  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-xl">Sign in</CardTitle>
        <CardDescription>Use the account your administrator gave you</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field data-invalid={!!errors.username}>
              <FieldLabel htmlFor="username">Username</FieldLabel>
              <Input id="username" autoComplete="username" {...form.register("username")} />
              <FieldError>{errors.username?.message}</FieldError>
            </Field>
            <Field data-invalid={!!errors.password}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...form.register("password")}
              />
              <FieldError>{errors.password?.message}</FieldError>
            </Field>
            <Field>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Signing in…" : "Sign in"}
              </Button>
            </Field>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
```

`frontend/components/auth/change-password-form.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"
import type { SessionInfo } from "@/lib/types"

const schema = z
  .object({
    current: z.string().min(1, "Enter your current password"),
    next: z.string().min(1, "Enter a new password"),
    confirm: z.string(),
  })
  .refine((v) => v.next === v.confirm, { message: "Passwords don't match", path: ["confirm"] })
type Values = z.infer<typeof schema>

export function ChangePasswordForm({ onDone }: { onDone: (info: SessionInfo) => void }) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { current: "", next: "", confirm: "" },
  })

  async function onSubmit(values: Values) {
    setError(null)
    try {
      onDone(await api.changePassword(values.current, values.next))
      form.reset()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server")
    }
  }

  const { errors, isSubmitting } = form.formState
  const fields = [
    ["current", "Current password", "current-password"],
    ["next", "New password", "new-password"],
    ["confirm", "Confirm new password", "new-password"],
  ] as const
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
      <FieldGroup>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {fields.map(([name, label, autoComplete]) => (
          <Field key={name} data-invalid={!!errors[name]}>
            <FieldLabel htmlFor={name}>{label}</FieldLabel>
            <Input id={name} type="password" autoComplete={autoComplete} {...form.register(name)} />
            <FieldError>{errors[name]?.message}</FieldError>
          </Field>
        ))}
        <Field>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Change password"}
          </Button>
        </Field>
      </FieldGroup>
    </form>
  )
}
```

`frontend/app/login/page.tsx`:

```tsx
import { AuthLayout } from "@/components/auth/auth-layout"
import { LoginForm } from "@/components/auth/login-form"

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams
  return (
    <AuthLayout>
      <LoginForm next={next} />
    </AuthLayout>
  )
}
```

`frontend/app/change-password/page.tsx`:

```tsx
"use client"

import { useRouter } from "next/navigation"

import { AuthLayout } from "@/components/auth/auth-layout"
import { ChangePasswordForm } from "@/components/auth/change-password-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function ChangePasswordPage() {
  const router = useRouter()
  return (
    <AuthLayout>
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">Set a new password</CardTitle>
          <CardDescription>You need to choose your own password before continuing</CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm onDone={() => router.replace("/app")} />
        </CardContent>
      </Card>
    </AuthLayout>
  )
}
```

- [ ] **Step 4: Run the checks**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): sign-in and forced password change"
```

---

### Task 4: App shell — sidebar with conversation history, user menu, profile

**Files:**
- Create: `frontend/components/app-sidebar.tsx`, `frontend/components/conversation-list.tsx`, `frontend/components/user-menu.tsx`, `frontend/components/conversation-list.test.tsx`, `frontend/app/app/layout.tsx`, `frontend/app/app/profile/page.tsx`, `frontend/hooks/use-debounced-value.ts`

**Interfaces:**
- Consumes: `api.me`, `api.conversations`, `api.renameConversation`, `api.deleteConversation`, `api.logout`, `handleUnauthorized`, `APP_NAME`, `ChangePasswordForm`; shadcn `Sidebar*`, `DropdownMenu*`, `Dialog*`, `AlertDialog*`, `Input`, `Avatar`.
- Produces:
  - `AppSidebar`, `ConversationList` (props: `activeId?: string`), `UserMenu`.
  - Query keys `["me"]`, `["conversations", q]`, `["conversation", id]`, `["collections"]`, which Task 5 reuses.
  - The `/app` layout redirects to `/change-password` when `me.must_change_password`.

- [ ] **Step 1: Write the failing test** — `frontend/components/conversation-list.test.tsx`

```tsx
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ConversationList } from "@/components/conversation-list"
import { SidebarProvider } from "@/components/ui/sidebar"
import { jsonResponse, renderWithProviders } from "@/test/render"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/app" }))

const conversations = [
  { id: "c1", title: "Leave policy", created_at: "", updated_at: "" },
  { id: "c2", title: "Parking", created_at: "", updated_at: "" },
]

function setup(fetchImpl: (url: string, init?: RequestInit) => Response) {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => fetchImpl(String(input), init))
  renderWithProviders(
    <SidebarProvider>
      <ConversationList activeId="c1" />
    </SidebarProvider>
  )
  return fetchMock
}

describe("ConversationList", () => {
  it("lists conversations and searches", async () => {
    const fetchMock = setup((url) =>
      jsonResponse(url.includes("?q=") ? [conversations[0]] : conversations)
    )
    expect(await screen.findByRole("link", { name: "Leave policy" })).toHaveAttribute(
      "href",
      "/app/c/c1"
    )
    expect(screen.getByRole("link", { name: "Parking" })).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText("Search conversations"), "leave")
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u) === "/api/conversations?q=leave")).toBe(true)
    )
    await waitFor(() => expect(screen.queryByRole("link", { name: "Parking" })).toBeNull())
  })

  it("renames and deletes a conversation", async () => {
    const fetchMock = setup((url, init) => {
      if (init?.method === "PATCH") return jsonResponse({ ...conversations[1], title: "Car park" })
      if (init?.method === "DELETE") return jsonResponse(null, 204)
      return jsonResponse(conversations)
    })
    const item = (await screen.findByRole("link", { name: "Parking" })).closest("li")!
    await userEvent.click(within(item).getByRole("button", { name: "Conversation actions" }))
    await userEvent.click(await screen.findByRole("menuitem", { name: "Rename" }))
    const input = await screen.findByLabelText("Title")
    await userEvent.clear(input)
    await userEvent.type(input, "Car park")
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PATCH")).toBe(true)
    )
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ title: "Car park" })

    await userEvent.click(within(item).getByRole("button", { name: "Conversation actions" }))
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }))
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => i?.method === "DELETE" && String(u) === "/api/conversations/c2")).toBe(true)
    )
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run components/conversation-list.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

`frontend/hooks/use-debounced-value.ts`:

```ts
import { useEffect, useState } from "react"

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}
```

`frontend/components/conversation-list.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MoreHorizontalIcon, PencilIcon, Trash2Icon } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarInput, SidebarMenu,
  SidebarMenuAction, SidebarMenuButton, SidebarMenuItem, SidebarMenuSkeleton,
} from "@/components/ui/sidebar"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { api, ApiError } from "@/lib/api"
import type { Conversation } from "@/lib/types"

export function ConversationList({ activeId }: { activeId?: string }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const q = useDebouncedValue(search.trim())
  const { data, isPending } = useQuery({
    queryKey: ["conversations", q],
    queryFn: () => api.conversations(q || undefined),
  })
  const [renaming, setRenaming] = useState<Conversation | null>(null)
  const [title, setTitle] = useState("")
  const [deleting, setDeleting] = useState<Conversation | null>(null)

  const onError = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : "Something went wrong")
  const rename = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => api.renameConversation(id, value),
    onSuccess: () => {
      setRenaming(null)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    },
    onError,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_, id) => {
      setDeleting(null)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      if (id === activeId) router.push("/app")
    },
    onError,
  })

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Conversations</SidebarGroupLabel>
      <SidebarGroupContent className="flex flex-col gap-2">
        <SidebarInput
          placeholder="Search conversations"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <SidebarMenu>
          {isPending &&
            Array.from({ length: 4 }, (_, i) => (
              <SidebarMenuItem key={i}>
                <SidebarMenuSkeleton />
              </SidebarMenuItem>
            ))}
          {data?.length === 0 && (
            <p className="px-2 py-1 text-sm text-muted-foreground">
              {q ? "No matching conversations" : "No conversations yet"}
            </p>
          )}
          {data?.map((c) => (
            <SidebarMenuItem key={c.id}>
              <SidebarMenuButton asChild isActive={c.id === activeId}>
                <Link href={`/app/c/${c.id}`}>
                  <span className="truncate">{c.title}</span>
                </Link>
              </SidebarMenuButton>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuAction showOnHover aria-label="Conversation actions">
                    <MoreHorizontalIcon />
                  </SidebarMenuAction>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="right" align="start">
                  <DropdownMenuItem
                    onSelect={() => {
                      setTitle(c.title)
                      setRenaming(c)
                    }}
                  >
                    <PencilIcon /> Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(c)}>
                    <Trash2Icon /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>

      <Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (renaming && title.trim()) rename.mutate({ id: renaming.id, value: title.trim() })
            }}
            className="flex flex-col gap-4"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="conversation-title">Title</Label>
              <Input
                id="conversation-title"
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!title.trim() || rename.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              “{deleting?.title}” and its messages will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => deleting && remove.mutate(deleting.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SidebarGroup>
  )
}
```

If the generated `AlertDialogAction` or `DropdownMenuItem` doesn't accept `variant`, use `className="bg-destructive text-white"` (or the component's own destructive styling) instead. Check the generated file.

`frontend/components/user-menu.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import { ChevronsUpDownIcon, LogOutIcon, MonitorIcon, MoonIcon, SunIcon, UserIcon } from "lucide-react"
import Link from "next/link"
import { useTheme } from "next-themes"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar"
import { api } from "@/lib/api"

export function UserMenu() {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const { theme, setTheme } = useTheme()
  const initials = (me?.full_name || me?.username || "?").slice(0, 2).toUpperCase()

  async function signOut() {
    await api.logout().catch(() => undefined)
    window.location.assign("/login")
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" aria-label="Account menu">
              <Avatar className="size-8 rounded-lg">
                <AvatarFallback className="rounded-lg">{initials}</AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{me?.full_name ?? "…"}</span>
                <span className="truncate text-xs text-muted-foreground">{me?.username}</span>
              </div>
              <ChevronsUpDownIcon className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="w-56">
            <DropdownMenuItem asChild>
              <Link href="/app/profile">
                <UserIcon /> Profile
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Theme</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
              <DropdownMenuRadioItem value="light"><SunIcon /> Light</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark"><MoonIcon /> Dark</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system"><MonitorIcon /> System</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void signOut()}>
              <LogOutIcon /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
```

`frontend/components/app-sidebar.tsx`:

```tsx
"use client"

import { MessagesSquareIcon, SquarePenIcon } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { ConversationList } from "@/components/conversation-list"
import { UserMenu } from "@/components/user-menu"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarMenu, SidebarMenuButton,
  SidebarMenuItem, SidebarRail,
} from "@/components/ui/sidebar"
import { APP_NAME } from "@/lib/config"

export function AppSidebar() {
  const pathname = usePathname()
  const activeId = pathname.startsWith("/app/c/") ? pathname.split("/")[3] : undefined
  return (
    <Sidebar>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/app">
                <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <MessagesSquareIcon className="size-4" />
                </div>
                <span className="truncate font-medium">{APP_NAME}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild>
              <Link href="/app">
                <SquarePenIcon /> New chat
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <ConversationList activeId={activeId} />
      </SidebarContent>
      <SidebarFooter>
        <UserMenu />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
```

`frontend/app/app/layout.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { api } from "@/lib/api"

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  useEffect(() => {
    if (me?.must_change_password) router.replace("/change-password")
  }, [me, router])

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="flex h-svh flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
          <SidebarTrigger />
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  )
}
```

`frontend/app/app/profile/page.tsx`:

```tsx
"use client"

import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { ChangePasswordForm } from "@/components/auth/change-password-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function ProfilePage() {
  const queryClient = useQueryClient()
  return (
    <div className="mx-auto w-full max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>You'll stay signed in on this device.</CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm
            onDone={(info) => {
              queryClient.setQueryData(["me"], info.user)
              toast.success("Password changed")
            }}
          />
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 4: Run the checks**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): app shell with conversation history, user menu and profile"
```

---

### Task 5: Chat — streaming answers, citations, source viewer, feedback, collection picker

**Files:**
- Create: `frontend/hooks/use-chat.ts`, `frontend/components/chat/{chat-view,chat-panel,message-list,assistant-message,markdown,citation-badge,source-card,source-viewer,feedback-buttons,composer,collection-picker}.tsx`, `frontend/components/chat/assistant-message.test.tsx`, `frontend/components/chat/chat-panel.test.tsx`, `frontend/app/app/page.tsx`, `frontend/app/app/c/[id]/page.tsx`

**Interfaces:**
- Consumes: `chatReducer`, `initialChatState`, `UIMessage` (Task 2); `streamChat`; `api.conversation`, `api.collections`, `api.feedback`; `pageImageUrl`; `linkCitations`, `CITATION_HREF_PREFIX`; `highlightBox`; the query keys from Task 4.
- Produces: `useChat(conversationId, initialMessages, onStarted?)` → `{ conversationId, messages, streaming, ask(question, collectionIds), stop() }` (`onStarted(id)` fires after the first answer of a new chat; the panel then `router.replace`s to `/app/c/<id>`); `ChatView({ conversationId? })`; `ChatPanel({ conversationId, initialMessages })`; `AssistantMessage({ message, onOpenSource })`.

- [ ] **Step 1: Write the failing tests**

`frontend/components/chat/assistant-message.test.tsx`:

```tsx
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { AssistantMessage } from "@/components/chat/assistant-message"
import type { UIMessage } from "@/lib/chat-state"
import type { SourceCard } from "@/lib/types"
import { jsonResponse, renderWithProviders } from "@/test/render"

const card: SourceCard = {
  n: 1, doc_id: "d1", version_id: "v1", filename: "handbook.pdf", page: 3,
  bbox: { l: 10, t: 20, r: 110, b: 70 }, page_image_scale: 1.5, heading_path: ["Leave"],
  modality: "text", score: 0.9, snippet: "Annual leave is 25 days.",
}

function message(overrides: Partial<UIMessage> = {}): UIMessage {
  return {
    id: "m1", role: "assistant", content: "Annual leave is **25 days** [1]. In [2024] too.",
    outcome: "answered", sources: [card], citations: [card], low_confidence: false,
    feedback_rating: null, feedback_comment: null, created_at: "", ...overrides,
  }
}

describe("AssistantMessage", () => {
  it("renders markdown with citation badges for real sources only", async () => {
    const onOpenSource = vi.fn()
    renderWithProviders(<AssistantMessage message={message()} onOpenSource={onOpenSource} />)
    expect(screen.getByText("25 days").tagName).toBe("STRONG")
    expect(screen.getByText(/In \[2024\] too/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Source 1: handbook.pdf, page 3" }))
    expect(onOpenSource).toHaveBeenCalledWith(card)
  })

  it("sanitizes html in answers", () => {
    const { container } = renderWithProviders(
      <AssistantMessage
        message={message({ content: 'Hi <script>alert(1)</script><img src=x onerror="alert(2)"> there' })}
        onOpenSource={vi.fn()}
      />
    )
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img[onerror]")).toBeNull()
  })

  it("shows the low-confidence badge and the not-found closest matches", () => {
    renderWithProviders(
      <>
        <AssistantMessage message={message({ low_confidence: true })} onOpenSource={vi.fn()} />
        <AssistantMessage
          message={message({
            id: "m2", outcome: "not_found", citations: [],
            content: "I couldn't find this in the available documents.",
          })}
          onOpenSource={vi.fn()}
        />
      </>
    )
    expect(screen.getByText("Low confidence — verify sources")).toBeInTheDocument()
    expect(screen.getByText("Closest matches")).toBeInTheDocument()
  })

  it("sends 👎 feedback with a comment", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ ...message(), feedback_rating: -1 }))
    renderWithProviders(<AssistantMessage message={message()} onOpenSource={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Bad answer" }))
    await userEvent.type(await screen.findByLabelText("What was wrong? (optional)"), "Outdated")
    await userEvent.click(screen.getByRole("button", { name: "Send feedback" }))
    expect(fetchMock.mock.calls[0][0]).toBe("/api/messages/m1/feedback")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      rating: -1, comment: "Outdated",
    })
  })

  it("hides feedback while streaming", () => {
    renderWithProviders(
      <AssistantMessage message={message({ id: "temp-1", streaming: true })} onOpenSource={vi.fn()} />
    )
    expect(screen.queryByRole("button", { name: "Bad answer" })).toBeNull()
  })
})
```

`frontend/components/chat/chat-panel.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ChatPanel } from "@/components/chat/chat-panel"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }))

function sse(...events: [string, unknown][]): Response {
  const body = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("")
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } })
}

describe("ChatPanel", () => {
  it("asks, streams and shows the final answer", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url === "/api/collections") return jsonResponse([{ id: "k1", name: "HR", description: "" }])
      return sse(
        ["meta", { conversation_id: "c1", user_message_id: "u1" }],
        ["token", { text: "Twenty " }],
        ["done", { message_id: "m1", content: "Twenty days.", outcome: "answered",
          citations: [], low_confidence: false, trace_id: null }]
      )
    })
    renderWithProviders(<ChatPanel conversationId={null} initialMessages={[]} />)
    await userEvent.type(screen.getByPlaceholderText("Ask a question"), "How many days?{Enter}")
    expect(await screen.findByText("Twenty days.")).toBeInTheDocument()
    expect(screen.getByText("How many days?")).toBeInTheDocument()
    const chatCall = fetchMock.mock.calls.find(([u]) => String(u) === "/api/chat")!
    expect(JSON.parse(String(chatCall[1]?.body))).toEqual({
      question: "How many days?", collection_ids: [],
    })
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/c/c1"))
  })

  it("shows a refusal from the server and allows asking again", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input) === "/api/collections") return jsonResponse([])
      return jsonResponse({ detail: { code: "rate_limited", message: "You're sending questions too quickly. Wait a minute." } }, 429)
    })
    renderWithProviders(<ChatPanel conversationId={null} initialMessages={[]} />)
    const box = screen.getByPlaceholderText("Ask a question")
    await userEvent.type(box, "Hi{Enter}")
    expect(await screen.findByText(/sending questions too quickly/)).toBeInTheDocument()
    await waitFor(() => expect(box).not.toBeDisabled())
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run components/chat`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement**

`frontend/hooks/use-chat.ts`:

```ts
"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useReducer, useRef } from "react"

import { ApiError } from "@/lib/api"
import { chatReducer, initialChatState } from "@/lib/chat-state"
import { streamChat } from "@/lib/sse"
import type { Message } from "@/lib/types"

/**
 * One chat panel's state. A brand-new chat creates its conversation on the first question;
 * `onStarted` is called once that answer has finished (or was stopped) so the page can move to
 * /app/c/<id>. The URL never changes mid-stream, so the stream is never unmounted.
 */
export function useChat(
  conversationId: string | null,
  initialMessages: Message[],
  onStarted?: (conversationId: string) => void
) {
  const [state, dispatch] = useReducer(
    chatReducer,
    initialChatState(conversationId, initialMessages)
  )
  const queryClient = useQueryClient()
  const abortRef = useRef<AbortController | null>(null)
  const conversationRef = useRef(conversationId)
  useEffect(() => {
    conversationRef.current = state.conversationId
  }, [state.conversationId])

  const ask = useCallback(
    async (question: string, collectionIds: string[]) => {
      const tempId = `temp-${crypto.randomUUID()}`
      dispatch({ type: "ask", question, tempId })
      const controller = new AbortController()
      abortRef.current = controller
      let started: string | null = null
      try {
        const body = {
          question,
          collection_ids: collectionIds,
          ...(conversationRef.current ? { conversation_id: conversationRef.current } : {}),
        }
        for await (const event of streamChat(body, controller.signal)) {
          dispatch({ type: "event", event, tempId })
          if (event.event === "meta" && !conversationRef.current) {
            started = event.data.conversation_id
            conversationRef.current = started
          }
        }
      } catch (err) {
        if (controller.signal.aborted) dispatch({ type: "stopped", tempId })
        else
          dispatch({
            type: "fail",
            tempId,
            message: err instanceof ApiError ? err.message : "Could not reach the assistant.",
          })
      } finally {
        abortRef.current = null
        void queryClient.invalidateQueries({ queryKey: ["conversations"] })
        if (started) onStarted?.(started)
      }
    },
    [queryClient, onStarted]
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])
  return { ...state, ask, stop }
}
```

`frontend/components/chat/markdown.tsx`:

```tsx
import ReactMarkdown from "react-markdown"
import rehypeSanitize from "rehype-sanitize"
import remarkGfm from "remark-gfm"

import { CitationBadge } from "@/components/chat/citation-badge"
import { CITATION_HREF_PREFIX, linkCitations } from "@/lib/citations"
import type { SourceCard } from "@/lib/types"

/** Sanitized Markdown (spec §5.3). Raw HTML from documents or the model is never rendered. */
export function Markdown({
  content,
  sources,
  onOpenSource,
}: {
  content: string
  sources: SourceCard[]
  onOpenSource: (card: SourceCard) => void
}) {
  const byNumber = new Map(sources.map((s) => [s.n, s]))
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert [&_table]:text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a({ href, children }) {
            if (href?.startsWith(CITATION_HREF_PREFIX)) {
              const card = byNumber.get(Number(href.slice(CITATION_HREF_PREFIX.length)))
              if (card) return <CitationBadge card={card} onOpen={onOpenSource} />
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            )
          },
        }}
      >
        {linkCitations(content, new Set(byNumber.keys()))}
      </ReactMarkdown>
    </div>
  )
}
```

`react-markdown` does not render raw HTML by default (it is escaped as text), and `rehype-sanitize` is a second guard. `prose` classes need `@tailwindcss/typography`. If they aren't installed, either `npm install -D @tailwindcss/typography` and add `@plugin "@tailwindcss/typography";` to `app/globals.css`, or remove the prose classes. Prefer installing it.

`frontend/components/chat/citation-badge.tsx`:

```tsx
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import type { SourceCard } from "@/lib/types"

export function sourceLabel(card: SourceCard): string {
  return card.page ? `${card.filename}, page ${card.page}` : card.filename
}

export function CitationBadge({
  card,
  onOpen,
}: {
  card: SourceCard
  onOpen: (card: SourceCard) => void
}) {
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          onClick={() => onOpen(card)}
          aria-label={`Source ${card.n}: ${sourceLabel(card)}`}
          className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/10 px-1 align-super text-[0.65rem] font-medium text-primary hover:bg-primary/20"
        >
          {card.n}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-80 text-sm">
        <p className="font-medium">{sourceLabel(card)}</p>
        {card.heading_path.length > 0 && (
          <p className="text-xs text-muted-foreground">{card.heading_path.join(" › ")}</p>
        )}
        <p className="mt-2 line-clamp-4 text-muted-foreground">{card.snippet}</p>
      </HoverCardContent>
    </HoverCard>
  )
}
```

`frontend/components/chat/source-card.tsx`:

```tsx
import { FileTextIcon } from "lucide-react"

import { sourceLabel } from "@/components/chat/citation-badge"
import type { SourceCard as Card } from "@/lib/types"

export function SourceCard({ card, onOpen }: { card: Card; onOpen: (card: Card) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(card)}
      className="flex w-56 shrink-0 flex-col gap-1 rounded-lg border bg-card p-2 text-left text-xs hover:bg-accent"
    >
      <span className="flex items-center gap-1 font-medium">
        <FileTextIcon className="size-3.5" />
        <span className="truncate">
          [{card.n}] {sourceLabel(card)}
        </span>
      </span>
      <span className="line-clamp-2 text-muted-foreground">{card.snippet}</span>
    </button>
  )
}
```

`frontend/components/chat/source-viewer.tsx`:

```tsx
"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { sourceLabel } from "@/components/chat/citation-badge"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { highlightBox } from "@/lib/bbox"
import { pageImageUrl } from "@/lib/api"
import type { SourceCard } from "@/lib/types"

/** Opens the cited page with the cited region highlighted (spec §4.1 step 9, §6.4). */
export function SourceViewer({
  card,
  onClose,
}: {
  card: SourceCard | null
  onClose: () => void
}) {
  return (
    <Sheet open={card !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{card ? sourceLabel(card) : ""}</SheetTitle>
          <SheetDescription>{card?.heading_path.join(" › ")}</SheetDescription>
        </SheetHeader>
        {/* Keyed so each source starts with fresh highlight/error state. */}
        {card && <PagePreview key={`${card.doc_id}-${card.n}`} card={card} />}
      </SheetContent>
    </Sheet>
  )
}

function PagePreview({ card }: { card: SourceCard }) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [box, setBox] = useState<ReturnType<typeof highlightBox> | null>(null)
  const [failed, setFailed] = useState(false)

  const measure = useCallback(() => {
    const img = imgRef.current
    if (!img || !card.bbox || !card.page_image_scale || !img.naturalWidth) return
    setBox(highlightBox(card.bbox, card.page_image_scale, img.naturalWidth, img.clientWidth))
  }, [card])

  useEffect(() => {
    window.addEventListener("resize", measure)
    return () => window.removeEventListener("resize", measure)
  }, [measure])

  const hasPage = card.page != null
  return (
    <>
      {hasPage && !failed && (
        <div className="relative mx-4 mb-4">
          {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
          <img
            ref={imgRef}
            src={pageImageUrl(card.doc_id, card.page!)}
            alt={`Page ${card.page} of ${card.filename}`}
            onLoad={measure}
            onError={() => setFailed(true)}
            className="w-full rounded border"
          />
          {box && (
            <div
              data-testid="source-highlight"
              className="pointer-events-none absolute rounded-sm border-2 border-amber-500 bg-amber-300/25"
              style={box}
            />
          )}
        </div>
      )}
      {(!hasPage || failed) && (
        <p className="mx-4 text-sm text-muted-foreground">
          {failed ? "The page preview isn't available." : "This file type has no page preview."}
        </p>
      )}
      <blockquote className="mx-4 mb-6 border-l-2 pl-3 text-sm">{card.snippet}</blockquote>
    </>
  )
}
```

`frontend/components/chat/feedback-buttons.tsx`:

```tsx
"use client"

import { useMutation } from "@tanstack/react-query"
import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"

export function FeedbackButtons({
  messageId,
  initial,
}: {
  messageId: string
  initial: 1 | -1 | null
}) {
  const [rating, setRating] = useState(initial)
  const [open, setOpen] = useState(false)
  const [comment, setComment] = useState("")
  const send = useMutation({
    mutationFn: ({ value, text }: { value: 1 | -1; text?: string }) =>
      api.feedback(messageId, value, text),
    onSuccess: (_, { value }) => {
      setRating(value)
      setOpen(false)
      toast.success("Thanks for the feedback")
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't send feedback"),
  })

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Good answer"
        aria-pressed={rating === 1}
        onClick={() => send.mutate({ value: 1 })}
        className={rating === 1 ? "text-primary" : "text-muted-foreground"}
      >
        <ThumbsUpIcon />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Bad answer"
        aria-pressed={rating === -1}
        onClick={() => setOpen(true)}
        className={rating === -1 ? "text-destructive" : "text-muted-foreground"}
      >
        <ThumbsDownIcon />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>What went wrong?</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`feedback-${messageId}`}>What was wrong? (optional)</Label>
            <Textarea
              id={`feedback-${messageId}`}
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              disabled={send.isPending}
              onClick={() => send.mutate({ value: -1, text: comment.trim() || undefined })}
            >
              Send feedback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

`frontend/components/chat/assistant-message.tsx`:

```tsx
import { LoaderIcon, TriangleAlertIcon } from "lucide-react"

import { FeedbackButtons } from "@/components/chat/feedback-buttons"
import { Markdown } from "@/components/chat/markdown"
import { SourceCard } from "@/components/chat/source-card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import type { UIMessage } from "@/lib/chat-state"
import type { SourceCard as Card } from "@/lib/types"

const NOTICE_OUTCOMES = new Set(["blocked", "support", "off_topic", "error"])

export function AssistantMessage({
  message,
  onOpenSource,
}: {
  message: UIMessage
  onOpenSource: (card: Card) => void
}) {
  const { outcome } = message
  const cited = message.citations.length ? message.citations : []
  const cards = outcome === "not_found" ? message.sources : cited
  const canRate =
    !message.streaming && !message.id.startsWith("temp-") &&
    (outcome === "answered" || outcome === "not_found")

  return (
    <div className="flex flex-col gap-2">
      {message.low_confidence && (
        <Badge variant="outline" className="w-fit gap-1 border-amber-500 text-amber-700 dark:text-amber-400">
          <TriangleAlertIcon className="size-3" /> Low confidence — verify sources
        </Badge>
      )}
      {outcome && NOTICE_OUTCOMES.has(outcome) ? (
        <Alert variant={outcome === "error" || outcome === "blocked" ? "destructive" : "default"}>
          <AlertDescription className="whitespace-pre-wrap">{message.content}</AlertDescription>
        </Alert>
      ) : message.content ? (
        <Markdown content={message.content} sources={message.sources} onOpenSource={onOpenSource} />
      ) : (
        message.streaming && <LoaderIcon className="size-4 animate-spin text-muted-foreground" aria-label="Thinking" />
      )}
      {message.notice && <p className="text-sm text-destructive">{message.notice}</p>}
      {outcome === "cancelled" && <p className="text-xs text-muted-foreground">Stopped</p>}
      {cards.length > 0 && (
        <div className="flex flex-col gap-1">
          {outcome === "not_found" && (
            <span className="text-xs font-medium text-muted-foreground">Closest matches</span>
          )}
          <div className="flex gap-2 overflow-x-auto pb-1">
            {cards.map((card) => (
              <SourceCard key={`${card.doc_id}-${card.n}`} card={card} onOpen={onOpenSource} />
            ))}
          </div>
        </div>
      )}
      {canRate && <FeedbackButtons messageId={message.id} initial={message.feedback_rating} />}
    </div>
  )
}
```

`frontend/components/chat/message-list.tsx`:

```tsx
"use client"

import { useEffect, useRef } from "react"

import { AssistantMessage } from "@/components/chat/assistant-message"
import type { UIMessage } from "@/lib/chat-state"
import type { SourceCard } from "@/lib/types"

export function MessageList({
  messages,
  onOpenSource,
}: {
  messages: UIMessage[]
  onOpenSource: (card: SourceCard) => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  const last = messages.at(-1)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" })
  }, [messages.length, last?.content])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6" aria-live="polite">
      {messages.map((m) =>
        m.role === "user" ? (
          <div key={m.id} className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-2xl bg-muted px-4 py-2">
            {m.content}
          </div>
        ) : (
          <AssistantMessage key={m.id} message={m} onOpenSource={onOpenSource} />
        )
      )}
      <div ref={endRef} />
    </div>
  )
}
```

`frontend/components/chat/collection-picker.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import { LibraryIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api } from "@/lib/api"

export function CollectionPicker({
  value,
  onChange,
}: {
  value: string[]
  onChange: (ids: string[]) => void
}) {
  const { data = [] } = useQuery({ queryKey: ["collections"], queryFn: api.collections })
  const label =
    value.length === 0
      ? "All collections"
      : value.length === 1
        ? (data.find((c) => c.id === value[0])?.name ?? "1 collection")
        : `${value.length} collections`
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground">
          <LibraryIcon /> {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Search in</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {data.length === 0 && (
          <p className="px-2 py-1.5 text-sm text-muted-foreground">No collections available</p>
        )}
        {data.map((c) => (
          <DropdownMenuCheckboxItem
            key={c.id}
            checked={value.includes(c.id)}
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(checked) =>
              onChange(checked ? [...value, c.id] : value.filter((id) => id !== c.id))
            }
          >
            {c.name}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

`frontend/components/chat/composer.tsx`:

```tsx
"use client"

import { ArrowUpIcon, SquareIcon } from "lucide-react"
import { useState } from "react"

import { CollectionPicker } from "@/components/chat/collection-picker"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

export function Composer({
  streaming,
  onAsk,
  onStop,
}: {
  streaming: boolean
  onAsk: (question: string, collectionIds: string[]) => void
  onStop: () => void
}) {
  const [text, setText] = useState("")
  const [collections, setCollections] = useState<string[]>([])

  function submit() {
    const question = text.trim()
    if (!question || streaming) return
    onAsk(question, collections)
    setText("")
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="rounded-2xl border bg-background p-2 shadow-sm">
        <Textarea
          placeholder="Ask a question"
          aria-label="Ask a question"
          value={text}
          disabled={streaming}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
          className="min-h-12 resize-none border-0 shadow-none focus-visible:ring-0"
        />
        <div className="flex items-center justify-between">
          <CollectionPicker value={collections} onChange={setCollections} />
          {streaming ? (
            <Button size="icon" variant="outline" aria-label="Stop" onClick={onStop}>
              <SquareIcon />
            </Button>
          ) : (
            <Button size="icon" aria-label="Send" disabled={!text.trim()} onClick={submit}>
              <ArrowUpIcon />
            </Button>
          )}
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-muted-foreground">
        Answers come from your company's documents. Check the sources.
      </p>
    </div>
  )
}
```

`frontend/components/chat/chat-panel.tsx`:

```tsx
"use client"

import { useRouter } from "next/navigation"
import { useCallback, useState } from "react"

import { Composer } from "@/components/chat/composer"
import { MessageList } from "@/components/chat/message-list"
import { SourceViewer } from "@/components/chat/source-viewer"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useChat } from "@/hooks/use-chat"
import { APP_NAME } from "@/lib/config"
import type { Message, SourceCard } from "@/lib/types"

export function ChatPanel({
  conversationId,
  initialMessages,
}: {
  conversationId: string | null
  initialMessages: Message[]
}) {
  const router = useRouter()
  // A new chat moves to its conversation URL once the first answer is complete.
  const onStarted = useCallback((id: string) => router.replace(`/app/c/${id}`), [router])
  const chat = useChat(conversationId, initialMessages, conversationId ? undefined : onStarted)
  const [source, setSource] = useState<SourceCard | null>(null)
  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="min-h-0 flex-1">
        {chat.messages.length === 0 ? (
          <div className="mx-auto flex max-w-3xl flex-col items-center gap-2 px-4 pt-[20vh] text-center">
            <h1 className="text-2xl font-semibold">{APP_NAME}</h1>
            <p className="text-muted-foreground">
              Ask about your company's documents. Answers cite their sources.
            </p>
          </div>
        ) : (
          <MessageList messages={chat.messages} onOpenSource={setSource} />
        )}
      </ScrollArea>
      <Composer streaming={chat.streaming} onAsk={chat.ask} onStop={chat.stop} />
      <SourceViewer card={source} onClose={() => setSource(null)} />
    </div>
  )
}
```

`frontend/components/chat/chat-view.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"

import { ChatPanel } from "@/components/chat/chat-panel"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"

export function ChatView({ conversationId }: { conversationId?: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: !!conversationId,
  })
  if (!conversationId) return <ChatPanel key="new" conversationId={null} initialMessages={[]} />
  if (isPending)
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <Skeleton className="ml-auto h-10 w-1/2" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  if (isError || !data)
    return <p className="p-6 text-muted-foreground">This conversation isn't available.</p>
  return <ChatPanel key={conversationId} conversationId={conversationId} initialMessages={data.messages} />
}
```

`frontend/app/app/page.tsx`:

```tsx
"use client"

import { ChatView } from "@/components/chat/chat-view"

export default function NewChatPage() {
  // After the first answer the panel moves to /app/c/<id>; "New chat" links back here.
  return <ChatView />
}
```

`frontend/app/app/c/[id]/page.tsx`:

```tsx
"use client"

import { useParams } from "next/navigation"

import { ChatView } from "@/components/chat/chat-view"

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>()
  return <ChatView conversationId={id} />
}
```

- [ ] **Step 4: Run the checks**

Run: `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`
Expected: PASS, and the build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): streaming chat with citations, source viewer, feedback and collection picker"
```

---

### Task 6: Playwright smoke test on the real stack

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts`
- Modify: `frontend/package.json` (adds the `e2e` script and the `@playwright/test` dev dependency)

**Interfaces:**
- Consumes: the whole app, and the backend stack with a ready document whose text says "Annual leave is twenty days per year".

- [ ] **Step 1: Add Playwright**

```bash
cd frontend
npm install -D @playwright/test
npx playwright install chromium
```

Add the script `"e2e": "playwright test"`.

`frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test"

// Runs against an already-running app (npm run build && npm start) and backend stack.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
```

`frontend/e2e/smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

const username = process.env.E2E_USERNAME ?? "root"
const password = process.env.E2E_PASSWORD ?? "root-password-123"

test("sign in, ask, see a cited answer and open its page", async ({ page }) => {
  await page.goto("/app")
  await expect(page).toHaveURL(/\/login/) // no session yet

  await page.getByLabel("Username").fill(username)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page).toHaveURL(/\/app/)

  await page.getByPlaceholder("Ask a question").fill("How many days of annual leave do employees get?")
  await page.keyboard.press("Enter")

  const citation = page.getByRole("button", { name: /^Source 1:/ })
  await expect(citation).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText(/twenty/i).first()).toBeVisible()
  await expect(page).toHaveURL(/\/app\/c\//)

  await citation.click()
  await expect(page.getByRole("img", { name: /^Page 1 of / })).toBeVisible()
  await expect(page.getByTestId("source-highlight")).toBeVisible()

  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "Good answer" }).click()
  await expect(page.getByText("Thanks for the feedback")).toBeVisible()
})
```

- [ ] **Step 2: Start the backend stack and seed data**

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

Seed the data the same way as the Plan 3/4 e2e: create root with password `root-password-123`, the `e2e` group (with root added) and the `E2E` collection. Then upload `e2e.pdf` ("Annual leave is twenty days per year") and wait for `ready`. `deploy/.env` must have `RAG_OPENAI_API_KEY`; never print it.

- [ ] **Step 3: Build, start and run**

```bash
cd frontend
BACKEND_URL=http://127.0.0.1:8000 npm run build
BACKEND_URL=http://127.0.0.1:8000 npm start &   # wait until http://localhost:3000 responds
npm run e2e
```
Expected: 1 passed. If it fails, keep the trace (`test-results/`) and report the failing step and the error. Check in particular whether tokens stream through the Next rewrite: the answer should appear progressively in a headed run (`npx playwright test --headed`). If streaming is buffered, report it; it's a concern for Plan 8's Caddy routing, not a reason to patch now.

- [ ] **Step 4: Clean up and commit**

Stop `npm start`, `rm e2e.pdf`, `docker compose -f deploy/docker-compose.yml down -v`. Make sure `test-results/` and `playwright-report/` are git-ignored (add them to `frontend/.gitignore`).

```bash
git add frontend
git commit -m "test(frontend): playwright smoke test for sign-in, cited answer and source page"
```

---

## Spec coverage for this plan

| Spec requirement | Task |
|---|---|
| §6.8 Next.js App Router + Tailwind v4 + official shadcn CLI and components; light/dark theming | 2 (all UI tasks use registry components) |
| §6.8 auth pages from the login block; forced password change page; no sign-up / forgot password | 3 |
| §6.3 user must change the initial password at first login | 1, 3, 4 |
| §5.3 secure httpOnly cookies, CSRF protection, sanitized Markdown rendering | 1, 2, 5 |
| §6.4 chat with collection picker and streaming answers | 5 |
| §6.4 / §4.1 step 9 citation cards with page preview + highlighted region | 2 (bbox), 5 |
| §6.4 👍/👎 with optional comment | 5 |
| §5.2 low-confidence badge | 5 |
| §6.4 conversation history: search, rename, delete | 4 |
| §6.4 source viewer opens the cited page | 5 |
| §6.4 profile: password change | 4 |
| §9 frontend E2E: login → ask → citation shown (smoke; CI in Plan 8) | 6 |
