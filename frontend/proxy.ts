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
  matcher: ["/app/:path*", "/admin/:path*", "/change-password"],
}
