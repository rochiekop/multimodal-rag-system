"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useRouter } from "next/navigation"

import { AuthLayout } from "@/components/auth/auth-layout"
import { ChangePasswordForm } from "@/components/auth/change-password-form"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { api } from "@/lib/api"
import { navigateTo } from "@/lib/navigate"
import type { SessionInfo } from "@/lib/types"

export default function ChangePasswordPage() {
  const router = useRouter()
  const queryClient = useQueryClient()

  function onDone(info: SessionInfo) {
    // The /app layout gates on ["me"]; a stale must_change_password would bounce back here.
    queryClient.setQueryData(["me"], info.user)
    router.replace("/app")
  }

  async function signOut() {
    await api.logout().catch(() => undefined)
    queryClient.clear()
    navigateTo("/login")
  }

  return (
    <AuthLayout>
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">Set a new password</CardTitle>
          <CardDescription>
            You need to choose your own password before continuing
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm onDone={onDone} />
        </CardContent>
      </Card>
      <Button
        variant="link"
        className="self-center text-muted-foreground"
        onClick={() => void signOut()}
      >
        Sign out
      </Button>
    </AuthLayout>
  )
}
