"use client"

import type { ReactNode } from "react"

import { BrandMark } from "@/components/branding"
import { useBranding } from "@/lib/branding"

export function AuthLayout({ children }: { children: ReactNode }) {
  const { appName } = useBranding()
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center gap-2 self-center font-medium">
          <BrandMark className="size-6 rounded-md" />
          {appName}
        </div>
        {children}
      </div>
    </div>
  )
}
