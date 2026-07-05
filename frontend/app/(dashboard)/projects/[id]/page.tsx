"use client";
import { useEffect, useState, useLayoutEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft, MapPin, Calendar, DollarSign,
  Edit2, Trash2, Plus, Users, CheckSquare,
} from "lucide-react";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import ProjectForm from "@/components/projects/ProjectForm";
import ProjectStatus from "@/components/projects/ProjectStatus";
import TaskCard from "@/components/tasks/TaskCard";
import TaskForm from "@/components/tasks/TaskForm";
import TeamMemberCard from "@/components/team/TeamMemberCard";
import DocumentList from "@/components/documents/DocumentList";
import { projectsApi, tasksApi, teamApi, documentsApi, operationalApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";
import { readPageCache } from "@/lib/pageCache";
import { formatDate, formatCurrency } from "@/lib/utils";
import type { Project, Task, TeamMember, Document } from "@/types";

const TABS = ["Overview", "Tasks", "Team", "Documents", "Timeline"] as const;

interface TimelinePhase {
  project?: string;
  phase?: string;
  start?: string;
  end?: string;
  status?: string;
  progress?: number;
}

interface ProjectDetailData {
  project: Project;
  tasks: Task[];
  team: TeamMember[];
  documents: Document[];
  timeline: TimelinePhase[];
}

export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = parseInt(params.id as string, 10);

  const { data, loading, error, reload, setData } = usePageData<ProjectDetailData>(
    `project-detail-${id}`,
    async () => {
      const p = await projectsApi.get(id);
      const [t, tm, d, tl] = await Promise.allSettled([
        tasksApi.list({ project_id: id }),
        teamApi.list(),
        documentsApi.list({ project_id: id }),
        operationalApi.timeline(),
      ]);
      const tasks = t.status === "fulfilled" ? t.value.data : [];
      const team = tm.status === "fulfilled"
        ? tm.value.data.filter(
            (m) => m.project_id === id || m.project_name === p.data.name,
          )
        : [];
      const documents = d.status === "fulfilled" ? d.value.data : [];
      const timeline = tl.status === "fulfilled"
        ? (tl.value.data as TimelinePhase[]).filter(
            (row) => row.project?.toLowerCase() === p.data.name.toLowerCase(),
          )
        : [];
      return { project: p.data, tasks, team, documents, timeline };
    },
    [id],
  );

  const project = data?.project ?? null;
  const tasks = data?.tasks ?? [];
  const team = data?.team ?? [];
  const documents = data?.documents ?? [];
  const timeline = data?.timeline ?? [];
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>("Overview");
  const [highlightTaskId, setHighlightTaskId] = useState<number | null>(null);
  const [editModal, setEditModal] = useState(false);
  const [addTaskModal, setAddTaskModal] = useState(false);
  const showLoading = loading && !data;

  // Instant paint when navigating from the projects list (cached).
  useLayoutEffect(() => {
    if (data) return;
    const stub = readPageCache<Project[]>("projects")?.find((p) => p.id === id);
    if (stub) {
      setData({ project: stub, tasks: [], team: [], documents: [], timeline: [] });
    }
  }, [id, data, setData]);

  useEffect(() => {
    const tab = searchParams.get("tab") as typeof TABS[number] | null;
    const taskId = searchParams.get("taskId");
    if (tab && TABS.includes(tab as typeof TABS[number])) {
      setActiveTab(tab as typeof TABS[number]);
    }
    if (taskId) {
      setHighlightTaskId(Number(taskId));
      setTimeout(() => setHighlightTaskId(null), 4000);
    }
  }, [searchParams]);

  const handleUpdate = async (update: Partial<Project>) => {
    const res = await projectsApi.update(id, update);
    if (data) setData({ ...data, project: res.data });
    setEditModal(false);
  };

  const handleDelete = async () => {
    if (!confirm("Delete this project? This cannot be undone.")) return;
    await projectsApi.delete(id);
    router.push("/projects");
  };

  const handleTaskStatusChange = async (task: Task, newStatus: Task["status"]) => {
    await tasksApi.update(task.id, { status: newStatus });
    reload();
  };

  const handleAddTask = async (taskData: Partial<Task>) => {
    await tasksApi.create({ ...taskData, project_id: id });
    setAddTaskModal(false);
    reload();
  };

  if (showLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-5 w-36 bg-gray-200 rounded" />
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-4">
          <div className="h-8 w-2/3 bg-gray-200 rounded" />
          <div className="h-4 w-1/2 bg-gray-200 rounded" />
          <div className="h-3 w-full bg-gray-100 rounded-full" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-12 bg-gray-100 rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="space-y-4 text-center py-20">
        <p className="text-gray-500">{error || "Project not found."}</p>
        <Link href="/projects">
          <Button variant="outline">Back to Projects</Button>
        </Link>
      </div>
    );
  }

  const STATUS_MILESTONE_COLORS: Record<string, string> = {
    Completed: "bg-green-100 text-green-700",
    "In Progress": "bg-amber-100 text-amber-700",
    Planning: "bg-blue-100 text-blue-700",
    "On Hold": "bg-gray-100 text-gray-600",
  };

  const detailItems = [
    { icon: MapPin, label: "Location", value: project.location || "—" },
    {
      icon: Calendar,
      label: "Timeline",
      value: project.start_date && project.end_date
        ? `${formatDate(project.start_date)} — ${formatDate(project.end_date)}`
        : project.end_date
          ? `Due ${formatDate(project.end_date)}`
          : "—",
    },
    { icon: Users, label: "Team", value: `${project.team_size} members` },
    { icon: CheckSquare, label: "Tasks", value: `${project.task_count} tasks` },
    { icon: DollarSign, label: "Budget", value: formatCurrency(project.budget) },
    { icon: Calendar, label: "Status", value: project.status },
  ];

  return (
    <div className="space-y-6">
      <Link href="/projects" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-primary transition-colors">
        <ArrowLeft size={16} />
        Back to Projects
      </Link>

      {/* Hero — expanded project card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 md:p-8">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl md:text-3xl font-bold text-gray-900">{project.name}</h1>
              <ProjectStatus status={project.status} />
            </div>
            {project.description && (
              <p className="text-gray-600 text-sm md:text-base mt-3 leading-relaxed max-w-3xl">
                {project.description}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button variant="outline" size="sm" onClick={() => setEditModal(true)}>
              <Edit2 size={14} /> Edit
            </Button>
            <Button variant="danger" size="sm" onClick={handleDelete}>
              <Trash2 size={14} />
            </Button>
          </div>
        </div>

        <div className="mt-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Overall Progress</span>
            <span className="text-sm font-bold text-primary">{project.progress}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-3">
            <div
              className="bg-primary h-3 rounded-full transition-all duration-500"
              style={{ width: `${project.progress}%` }}
            />
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {detailItems.map(({ icon: Icon, label, value }) => (
            <div
              key={label}
              className="flex items-start gap-3 rounded-lg border border-gray-100 bg-gray-50/60 px-4 py-3"
            >
              <div className="p-2 rounded-lg bg-white border border-gray-100 flex-shrink-0">
                <Icon size={16} className="text-primary" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">{label}</p>
                <p className="text-sm font-semibold text-gray-900 mt-0.5 break-words">{value}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <div className="flex gap-1 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab
                  ? "border-primary text-primary"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
              {tab === "Tasks" && tasks.length > 0 && (
                <span className="ml-1.5 text-xs text-gray-400">({tasks.length})</span>
              )}
              {tab === "Team" && team.length > 0 && (
                <span className="ml-1.5 text-xs text-gray-400">({team.length})</span>
              )}
              {tab === "Documents" && documents.length > 0 && (
                <span className="ml-1.5 text-xs text-gray-400">({documents.length})</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "Overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-semibold text-gray-900 mb-3">About this project</h3>
            <p className="text-gray-600 text-sm leading-relaxed">
              {project.description || "No description provided."}
            </p>
            {tasks.length > 0 && (
              <div className="mt-6 pt-6 border-t border-gray-100">
                <h4 className="text-sm font-semibold text-gray-900 mb-3">Recent tasks</h4>
                <ul className="space-y-2">
                  {tasks.slice(0, 5).map((t) => (
                    <li key={t.id} className="flex items-center justify-between text-sm">
                      <span className="text-gray-700 truncate pr-4">{t.title}</span>
                      <span className="text-xs text-gray-500 flex-shrink-0">{t.status}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="space-y-3">
            {[
              { label: "Status", value: project.status },
              { label: "Progress", value: `${project.progress}%` },
              { label: "Budget", value: formatCurrency(project.budget) },
              { label: "Start Date", value: formatDate(project.start_date) },
              { label: "End Date", value: formatDate(project.end_date) },
              { label: "Location", value: project.location || "—" },
              { label: "Team Size", value: `${project.team_size} members` },
              { label: "Open Tasks", value: `${project.task_count} tasks` },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white rounded-xl border border-gray-100 p-4">
                <p className="text-xs text-gray-400 font-medium mb-1">{label}</p>
                <p className="text-sm font-semibold text-gray-900">{value}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === "Tasks" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setAddTaskModal(true)}>
              <Plus size={14} /> Add Task
            </Button>
          </div>
          {tasks.length === 0 ? (
            <div className="text-center py-12 text-gray-400 text-sm">No tasks for this project</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {tasks.map((t) => (
                <div
                  key={t.id}
                  className={`rounded-xl transition-all duration-700 ${
                    highlightTaskId === t.id
                      ? "ring-2 ring-primary ring-offset-1 shadow-md scale-[1.02]"
                      : ""
                  }`}
                >
                  <TaskCard task={t} onStatusChange={handleTaskStatusChange} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "Team" && (
        team.length === 0 ? (
          <div className="text-center py-12 text-gray-400 text-sm">No team members assigned</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {team.map((m) => <TeamMemberCard key={m.id} member={m} />)}
          </div>
        )
      )}

      {activeTab === "Documents" && (
        <DocumentList documents={documents} />
      )}

      {activeTab === "Timeline" && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Phase</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Start</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">End</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Progress</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {timeline.length > 0 ? timeline.map((m, i) => (
                <tr key={i} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 font-medium text-sm text-gray-900">{m.phase}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">{m.start ? formatDate(m.start) : "—"}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">{m.end ? formatDate(m.end) : "—"}</td>
                  <td className="px-6 py-4">
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${STATUS_MILESTONE_COLORS[m.status ?? ""] || ""}`}>
                      {m.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-gray-100 rounded-full h-1.5 w-24">
                        <div className="bg-primary h-1.5 rounded-full" style={{ width: `${m.progress ?? 0}%` }} />
                      </div>
                      <span className="text-xs text-gray-500 w-8">{m.progress ?? 0}%</span>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={5} className="px-6 py-10 text-center text-sm text-gray-400">
                    No timeline phases for this project
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={editModal} onClose={() => setEditModal(false)} title="Edit Project" size="lg">
        <ProjectForm
          initialData={project}
          onSubmit={handleUpdate}
          onCancel={() => setEditModal(false)}
        />
      </Modal>

      <Modal open={addTaskModal} onClose={() => setAddTaskModal(false)} title="Add Task" size="md">
        <TaskForm
          initialData={{ project_id: id }}
          onSubmit={handleAddTask}
          onCancel={() => setAddTaskModal(false)}
        />
      </Modal>
    </div>
  );
}
