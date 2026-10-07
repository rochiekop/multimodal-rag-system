"use client"

import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { APP_NAME } from "@/lib/config"

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}

/** Black or white text, whichever contrasts more with `hex` (#rrggbb). */
export function contrastText(hex: string): "#000000" | "#ffffff" {
  const l = luminance(hex)
  return (l + 0.05) / 0.05 >= 1.05 / (l + 0.05) ? "#000000" : "#ffffff"
}

/** Branding from admin Settings; defaults while loading or when the API is unreachable. */
export function useBranding() {
  const { data } = useQuery({
    queryKey: ["branding"],
    queryFn: api.branding,
    staleTime: 5 * 60_000,
  })
  return {
    appName: data?.app_name ?? APP_NAME,
    primaryColor: data?.primary_color ?? null,
    logoUrl: data?.logo_url ?? null,
  }
}
