"use client";
import type { Task } from "@/types";
import TaskCard from "./TaskCard";
import { Plus } from "lucide-react";

interface KanbanColumn {
  id: Task["status"];
  label: string;
  color: string;
  bg: string;
}

const COLUMNS: KanbanColumn[] = [
  { id: "To Do", label: "To Do", color: "text-slate-600", bg: "bg-slate-50" },
  { id: "In Progress", label: "In Progress", color: "text-amber-600", bg: "bg-amber-50" },
  { id: "Review", label: "Review", color: "text-purple-600", bg: "bg-purple-50" },
  { id: "Done", label: "Done", color: "text-green-600", bg: "bg-green-50" },
];

interface TaskListProps {
  tasks: Task[];
  onStatusChange: (task: Task, newStatus: Task["status"]) => void;
  onAddTask?: (status: Task["status"]) => void;
  highlightId?: number | null;
}

export default function TaskList({ tasks, onStatusChange, onAddTask, highlightId }: TaskListProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {COLUMNS.map((col) => {
        const columnTasks = tasks.filter((t) => t.status === col.id);
        return (
          <div key={col.id} className={`rounded-xl p-4 ${col.bg} border border-gray-100`}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className={`font-semibold text-sm ${col.color}`}>{col.label}</span>
                <span className="bg-white text-gray-500 text-xs font-medium px-2 py-0.5 rounded-full border border-gray-200">
                  {columnTasks.length}
                </span>
              </div>
              {onAddTask && (
                <button
                  onClick={() => onAddTask(col.id)}
                  className="p-1 hover:bg-white rounded-lg transition-colors text-gray-400 hover:text-gray-600"
                >
                  <Plus size={16} />
                </button>
              )}
            </div>
            <div className="space-y-3">
              {columnTasks.map((task) => (
                <div
                  key={task.id}
                  className={`rounded-xl transition-all duration-700 ${
                    highlightId === task.id
                      ? "ring-2 ring-primary ring-offset-1 shadow-md scale-[1.02]"
                      : ""
                  }`}
                >
                  <TaskCard task={task} onStatusChange={onStatusChange} />
                </div>
              ))}
              {columnTasks.length === 0 && (
                <div className="text-center py-6 text-gray-400 text-xs">
                  No tasks
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
