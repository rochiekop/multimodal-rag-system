"use client"

import { useRouter } from "next/navigation"

import { AuthLayout } from "@/components/auth/auth-layout"
import { ChangePasswordForm } from "@/components/auth/change-password-form"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export default function ChangePasswordPage() {
  const router = useRouter()
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
          <ChangePasswordForm onDone={() => router.replace("/app")} />
        </CardContent>
      </Card>
    </AuthLayout>
  )
}
