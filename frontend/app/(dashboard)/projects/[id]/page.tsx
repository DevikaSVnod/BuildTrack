"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft, MapPin, Calendar, DollarSign,
  TrendingUp, Edit2, Trash2, Plus,
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

export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = parseInt(params.id as string);

  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [timeline, setTimeline] = useState<TimelinePhase[]>([]);
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>("Overview");
  const [highlightTaskId, setHighlightTaskId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [editModal, setEditModal] = useState(false);
  const [addTaskModal, setAddTaskModal] = useState(false);

  // Handle ?tab=Tasks&taskId=X from search navigation
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

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [p, t, tm, d, tl] = await Promise.all([
        projectsApi.get(id),
        tasksApi.list({ project_id: id }),
        teamApi.list(),
        documentsApi.list({ project_id: id }),
        operationalApi.timeline(),
      ]);
      setProject(p.data);
      setTasks(t.data);
      setTeam(tm.data.filter((m) => m.project_id === id || m.project_name === p.data.name));
      setDocuments(d.data);
      setTimeline(
        (tl.data as TimelinePhase[]).filter(
          (row) => row.project?.toLowerCase() === p.data.name.toLowerCase()
        )
      );
    } catch {
      router.push("/projects");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, [id]);

  const handleUpdate = async (data: Partial<Project>) => {
    const res = await projectsApi.update(id, data);
    setProject(res.data);
    setEditModal(false);
  };

  const handleDelete = async () => {
    if (!confirm("Delete this project? This cannot be undone.")) return;
    await projectsApi.delete(id);
    router.push("/projects");
  };

  const handleTaskStatusChange = async (task: Task, newStatus: Task["status"]) => {
    await tasksApi.update(task.id, { status: newStatus });
    fetchAll();
  };

  const handleAddTask = async (data: Partial<Task>) => {
    await tasksApi.create({ ...data, project_id: id });
    setAddTaskModal(false);
    fetchAll();
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="h-40 bg-gray-200 rounded-xl animate-pulse" />
      </div>
    );
  }

  if (!project) return null;

  const STATUS_MILESTONE_COLORS: Record<string, string> = {
    Completed: "bg-green-100 text-green-700",
    "In Progress": "bg-amber-100 text-amber-700",
    Planning: "bg-blue-100 text-blue-700",
    "On Hold": "bg-gray-100 text-gray-600",
  };

  return (
    <div className="space-y-6">
      {/* Back + Header */}
      <Link href="/projects" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-primary transition-colors">
        <ArrowLeft size={16} />
        Back to Projects
      </Link>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
              <ProjectStatus status={project.status} />
            </div>
            <div className="flex flex-wrap gap-4 mt-3">
              {project.location && (
                <div className="flex items-center gap-1.5 text-sm text-gray-500">
                  <MapPin size={14} />
                  {project.location}
                </div>
              )}
              {project.start_date && (
                <div className="flex items-center gap-1.5 text-sm text-gray-500">
                  <Calendar size={14} />
                  {formatDate(project.start_date)} — {formatDate(project.end_date)}
                </div>
              )}
              {project.budget && (
                <div className="flex items-center gap-1.5 text-sm text-gray-500">
                  <DollarSign size={14} />
                  {formatCurrency(project.budget)}
                </div>
              )}
            </div>
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

        {/* Progress bar */}
        <div className="mt-4">
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
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab
                  ? "border-primary text-primary"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {activeTab === "Overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h3 className="font-semibold text-gray-900 mb-3">Description</h3>
            <p className="text-gray-600 text-sm leading-relaxed">
              {project.description || "No description provided."}
            </p>
          </div>
          <div className="space-y-4">
            {[
              { label: "Status", value: project.status },
              { label: "Progress", value: `${project.progress}%` },
              { label: "Budget", value: formatCurrency(project.budget) },
              { label: "Start Date", value: formatDate(project.start_date) },
              { label: "End Date", value: formatDate(project.end_date) },
              { label: "Location", value: project.location || "—" },
              { label: "Team Size", value: `${project.team_size} members` },
              { label: "Tasks", value: `${project.task_count} tasks` },
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
                    No timeline phases in search index for this project
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit modal */}
      <Modal open={editModal} onClose={() => setEditModal(false)} title="Edit Project" size="lg">
        <ProjectForm
          initialData={project}
          onSubmit={handleUpdate}
          onCancel={() => setEditModal(false)}
        />
      </Modal>

      {/* Add task modal */}
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
