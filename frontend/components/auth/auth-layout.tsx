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
