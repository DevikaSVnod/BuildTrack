import { cn, ROLE_COLORS } from "@/lib/utils";
import type { UserRole } from "@/types";

export default function RoleBadge({ role }: { role: UserRole }) {
  return (
    <span className={cn("text-xs px-2.5 py-0.5 rounded-full font-medium", ROLE_COLORS[role])}>
      {role}
    </span>
  );
}
