import { cn, STATUS_COLORS } from "@/lib/utils";
import type { ProjectStatus as ProjectStatusType } from "@/types";

export default function ProjectStatus({ status }: { status: ProjectStatusType }) {
  return (
    <span className={cn("text-xs px-2.5 py-1 rounded-full font-medium", STATUS_COLORS[status])}>
      {status}
    </span>
  );
}
