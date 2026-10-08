import type { Role, User } from "@/lib/types"

const RANK: Record<Role, number> = { user: 0, admin: 1, super_admin: 2 }

export const isAdmin = (user: Pick<User, "role">) =>
  RANK[user.role] >= RANK.admin
export const isSuperAdmin = (user: Pick<User, "role">) =>
  user.role === "super_admin"
