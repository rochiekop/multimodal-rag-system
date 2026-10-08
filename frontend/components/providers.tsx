"use client"

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { useState, type ReactNode } from "react"

import { BrandingEffect } from "@/components/branding"
import { ThemeProvider } from "@/components/theme-provider"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError, handleUnauthorized } from "@/lib/api"

function onApiError(error: unknown) {
  if (error instanceof ApiError && error.status === 401)
    void handleUnauthorized()
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({ onError: onApiError }),
        mutationCache: new MutationCache({ onError: onApiError }),
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
        },
      })
  )
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <BrandingEffect />
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster richColors position="top-center" />
      </QueryClientProvider>
    </ThemeProvider>
  )
}
