"use client"

import { MessagesSquareIcon } from "lucide-react"
import { usePathname } from "next/navigation"
import { useEffect } from "react"

import { contrastText, useBranding } from "@/lib/branding"
import { cn } from "@/lib/utils"

const COLOR_VARS = ["--primary", "--sidebar-primary", "--ring"]
const TEXT_VARS = ["--primary-foreground", "--sidebar-primary-foreground"]

/** Applies the configured primary color and app name to the whole page. */
export function BrandingEffect() {
  const { appName, primaryColor } = useBranding()
  const pathname = usePathname()
  useEffect(() => {
    document.title = appName // re-applied after navigations reset the title
  }, [appName, pathname])
  useEffect(() => {
    const style = document.documentElement.style
    for (const name of [...COLOR_VARS, ...TEXT_VARS]) style.removeProperty(name)
    if (!primaryColor) return
    const text = contrastText(primaryColor)
    for (const name of COLOR_VARS) style.setProperty(name, primaryColor)
    for (const name of TEXT_VARS) style.setProperty(name, text)
  }, [primaryColor])
  return null
}

export function BrandMark({ className }: { className?: string }) {
  const { logoUrl } = useBranding()
  if (logoUrl) {
    return (
      // A small same-origin logo; next/image adds nothing here.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={logoUrl}
        alt=""
        className={cn("size-8 rounded-lg object-contain", className)}
      />
    )
  }
  return (
    <div
      className={cn(
        "flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground",
        className
      )}
    >
      <MessagesSquareIcon className="size-4" />
    </div>
  )
}
