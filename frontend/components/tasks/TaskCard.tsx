"use client";
import { Calendar, AlertCircle, Folder } from "lucide-react";
import type { Task } from "@/types";
import { formatDate, STATUS_COLORS, PRIORITY_COLORS, getInitials, cn } from "@/lib/utils";

interface TaskCardProps {
  task: Task;
  onStatusChange?: (task: Task, newStatus: Task["status"]) => void;
}

const PRIORITY_DOT: Record<string, string> = {
  High: "bg-red-500",
  Medium: "bg-amber-500",
  Low: "bg-green-500",
};

export default function TaskCard({ task, onStatusChange }: TaskCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 hover:shadow-md hover:border-primary/20 transition-all duration-200">
      {/* Priority & status */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <span className={cn("w-2 h-2 rounded-full flex-shrink-0", PRIORITY_DOT[task.priority])} />
          <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", PRIORITY_COLORS[task.priority])}>
            {task.priority}
          </span>
        </div>
        {onStatusChange && (
          <select
            value={task.status}
            onChange={(e) => onStatusChange(task, e.target.value as Task["status"])}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary/30"
            onClick={(e) => e.stopPropagation()}
          >
            <option value="To Do">To Do</option>
            <option value="In Progress">In Progress</option>
            <option value="Review">Review</option>
            <option value="Done">Done</option>
          </select>
        )}
      </div>

      {/* Title */}
      <h4 className="font-medium text-gray-900 text-sm leading-snug mb-2">{task.title}</h4>

      {task.description && (
        <p className="text-xs text-gray-500 line-clamp-2 mb-3">{task.description}</p>
      )}

      {/* Meta */}
      <div className="space-y-1.5">
        {task.project_name && (
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <Folder size={11} />
            <span className="truncate">{task.project_name}</span>
          </div>
        )}
        {task.due_date && (
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <Calendar size={11} />
            <span>Due {formatDate(task.due_date)}</span>
          </div>
        )}
      </div>

      {/* Assignee */}
      {task.assignee && (
        <div className="mt-3 pt-3 border-t border-gray-50 flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold flex items-center justify-center flex-shrink-0">
            {getInitials(task.assignee.full_name)}
          </div>
          <span className="text-xs text-gray-600 truncate">{task.assignee.full_name}</span>
        </div>
      )}
    </div>
  );
}
