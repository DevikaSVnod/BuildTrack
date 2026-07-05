"use client";
import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { Plus, Sparkles, ClipboardList, CheckCircle2, Clock, AlertCircle } from "lucide-react";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import TaskList from "@/components/tasks/TaskList";
import TaskForm from "@/components/tasks/TaskForm";
import { tasksApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";
import type { Task } from "@/types";

export default function TasksPage() {
  const { data: tasks, loading, reload } = usePageData<Task[]>(
    "tasks",
    () => tasksApi.list().then((r) => r.data),
  );
  const list = tasks ?? [];
  const [showModal, setShowModal] = useState(false);
  const [defaultStatus, setDefaultStatus] = useState<Task["status"]>("To Do");
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const searchParams = useSearchParams();
  const highlightRef = useRef<HTMLDivElement>(null);

  const fetchTasks = () => reload();

  useEffect(() => {
    const id = searchParams.get("taskId");
    if (id) {
      setHighlightId(Number(id));
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 700);
      const timer = setTimeout(() => setHighlightId(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  const handleStatusChange = async (task: Task, newStatus: Task["status"]) => {
    await tasksApi.update(task.id, { status: newStatus });
    fetchTasks();
  };

  const handleAddTask = (status: Task["status"]) => {
    setDefaultStatus(status);
    setShowModal(true);
  };

  const handleCreate = async (data: Partial<Task>) => {
    await tasksApi.create(data);
    setShowModal(false);
    fetchTasks();
  };

  const totalByStatus = (status: Task["status"]) => list.filter((t) => t.status === status).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-widest text-amber-700 bg-amber-100 px-2.5 py-0.5 rounded-full">
              Operations
            </span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Site Activities</h1>
          <p className="text-gray-500 text-sm mt-1">
            {list.length} total activities · {totalByStatus("Done")} completed · {totalByStatus("In Progress")} in progress
          </p>
        </div>
        <Button onClick={() => { setDefaultStatus("To Do"); setShowModal(true); }}>
          <Plus size={16} /> Add Activity
        </Button>
      </div>

      {/* Activity KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "To Do",        value: totalByStatus("To Do"),        icon: ClipboardList,  color: "text-gray-600",   bg: "bg-gray-50"    },
          { label: "In Progress",  value: totalByStatus("In Progress"),  icon: Clock,          color: "text-amber-600",  bg: "bg-amber-50"   },
          { label: "Under Review", value: totalByStatus("Review"),       icon: AlertCircle,    color: "text-purple-600", bg: "bg-purple-50"  },
          { label: "Completed",    value: totalByStatus("Done"),         icon: CheckCircle2,   color: "text-green-600",  bg: "bg-green-50"   },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-3">
            <div className={`p-2.5 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={18} className={color} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-xl font-bold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Search result banner */}
      {highlightId && (
        <div ref={highlightRef} className="flex items-center gap-2 px-4 py-2.5 bg-primary/5 border border-primary/20 rounded-xl text-sm text-primary font-medium">
          <Sparkles size={14} />
          Navigated from search — task highlighted below
        </div>
      )}

      {loading && list.length === 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-xl bg-gray-50 p-4 h-64 animate-pulse" />
          ))}
        </div>
      ) : (
        <TaskList
          tasks={list}
          onStatusChange={handleStatusChange}
          onAddTask={handleAddTask}
          highlightId={highlightId}
        />
      )}

      <Modal open={showModal} onClose={() => setShowModal(false)} title="Add Task">
        <TaskForm
          initialData={{ status: defaultStatus }}
          onSubmit={handleCreate}
          onCancel={() => setShowModal(false)}
        />
      </Modal>
    </div>
  );
}
