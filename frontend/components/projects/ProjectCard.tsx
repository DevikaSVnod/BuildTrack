"use client";
import Link from "next/link";
import { MapPin, Calendar, Users, CheckSquare, TrendingUp } from "lucide-react";
import type { Project } from "@/types";
import { formatDate, formatCurrency, STATUS_COLORS, cn } from "@/lib/utils";

interface ProjectCardProps {
  project: Project;
}

export default function ProjectCard({ project }: ProjectCardProps) {
  return (
    <Link href={`/projects/${project.id}`}>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 hover:shadow-md hover:border-primary/20 transition-all duration-200 cursor-pointer group">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-gray-900 text-base group-hover:text-primary transition-colors truncate">
              {project.name}
            </h3>
            {project.description && (
              <p className="text-sm text-gray-500 mt-1 line-clamp-2">{project.description}</p>
            )}
          </div>
          <span className={cn("text-xs px-2.5 py-1 rounded-full font-medium flex-shrink-0", STATUS_COLORS[project.status])}>
            {project.status}
          </span>
        </div>

        {/* Progress */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-gray-500 font-medium">Progress</span>
            <span className="text-xs font-semibold text-gray-700">{project.progress}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div
              className="bg-primary h-2 rounded-full transition-all duration-500"
              style={{ width: `${project.progress}%` }}
            />
          </div>
        </div>

        {/* Meta info */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          {project.location && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <MapPin size={12} />
              <span className="truncate">{project.location.split(",")[0]}</span>
            </div>
          )}
          {project.end_date && (
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Calendar size={12} />
              <span>Due {formatDate(project.end_date)}</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Users size={12} />
            <span>{project.team_size} members</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <CheckSquare size={12} />
            <span>{project.task_count} tasks</span>
          </div>
        </div>

        {project.budget && (
          <div className="mt-3 pt-3 border-t border-gray-50 flex items-center justify-between">
            <span className="text-xs text-gray-400">Budget</span>
            <span className="text-xs font-semibold text-gray-700">{formatCurrency(project.budget)}</span>
          </div>
        )}
      </div>
    </Link>
  );
}
