"use client"

import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { ChangePasswordForm } from "@/components/auth/change-password-form"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export default function ProfilePage() {
  const queryClient = useQueryClient()
  return (
    <div className="mx-auto w-full max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>
            You&apos;ll stay signed in on this device.
          </CardDescription>
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
