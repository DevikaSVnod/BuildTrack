import Link from "next/link";
import type { Project } from "@/types";
import { formatDate } from "@/lib/utils";
import { STATUS_COLORS } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { ArrowRight } from "lucide-react";

interface RecentProjectsProps {
  projects: Project[];
}

export default function RecentProjects({ projects }: RecentProjectsProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
        <h2 className="font-semibold text-gray-900">Recent Projects</h2>
        <Link href="/projects" className="text-sm text-primary hover:underline flex items-center gap-1">
          View all <ArrowRight size={14} />
        </Link>
      </div>
      <div className="divide-y divide-gray-50">
        {projects.slice(0, 5).map((project) => (
          <Link
            key={project.id}
            href={`/projects/${project.id}`}
            className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors group"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p className="font-medium text-gray-900 text-sm truncate group-hover:text-primary">
                  {project.name}
                </p>
                <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0", STATUS_COLORS[project.status])}>
                  {project.status}
                </span>
              </div>
              <div className="flex items-center gap-4 mt-1.5">
                <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                  <div
                    className="bg-primary h-1.5 rounded-full transition-all"
                    style={{ width: `${project.progress}%` }}
                  />
                </div>
                <span className="text-xs text-gray-500 flex-shrink-0">{project.progress}%</span>
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <p className="text-xs text-gray-500">Due {formatDate(project.end_date)}</p>
              <p className="text-xs text-gray-400 mt-0.5">{project.team_size} members</p>
            </div>
          </Link>
        ))}
        {projects.length === 0 && (
          <div className="px-6 py-8 text-center text-gray-400 text-sm">
            No projects yet
          </div>
        )}
      </div>
    </div>
  );
}
