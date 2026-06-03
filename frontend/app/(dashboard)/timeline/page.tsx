"use client";
import { useEffect, useState } from "react";
import { Calendar } from "lucide-react";
import { operationalApi } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";

interface Milestone {
  project: string;
  phase: string;
  start: string | null;
  end: string | null;
  status: string;
  progress: number;
}

const STATUS_COLORS_LOCAL: Record<string, string> = {
  "Completed": "bg-green-100 text-green-700",
  "In Progress": "bg-amber-100 text-amber-700",
  "Planning": "bg-blue-100 text-blue-700",
  "On Hold": "bg-gray-100 text-gray-600",
};

export default function TimelinePage() {
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProject, setSelectedProject] = useState<string>("all");

  useEffect(() => {
    operationalApi.timeline()
      .then((r) => setMilestones(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const projectNames = [...new Set(milestones.map((m) => m.project).filter(Boolean))];
  const displayed =
    selectedProject === "all"
      ? milestones
      : milestones.filter((m) => m.project === selectedProject);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Timeline</h1>
          <p className="text-gray-500 text-sm mt-1">Project milestones and phases</p>
        </div>
        <select
          value={selectedProject}
          onChange={(e) => setSelectedProject(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="all">All Projects</option>
          {projectNames.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="bg-white rounded-xl border h-64 animate-pulse" />
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                {selectedProject === "all" && (
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Project</th>
                )}
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Phase</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Start</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">End</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3 min-w-[150px]">Progress</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {displayed.map((m, i) => (
                <tr key={i} className="hover:bg-gray-50 transition-colors">
                  {selectedProject === "all" && (
                    <td className="px-6 py-4 text-sm font-medium text-primary truncate max-w-[180px]">{m.project}</td>
                  )}
                  <td className="px-6 py-4 font-medium text-sm text-gray-900">{m.phase}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">{m.start ? formatDate(m.start) : "—"}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">{m.end ? formatDate(m.end) : "—"}</td>
                  <td className="px-6 py-4">
                    <span className={cn("text-xs px-2.5 py-0.5 rounded-full font-medium", STATUS_COLORS_LOCAL[m.status] || "bg-gray-100 text-gray-600")}>
                      {m.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-gray-100 rounded-full h-2 min-w-[80px]">
                        <div
                          className="h-2 rounded-full bg-primary transition-all"
                          style={{ width: `${m.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-500 w-8 text-right">{m.progress}%</span>
                    </div>
                  </td>
                </tr>
              ))}
              {displayed.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-gray-400 text-sm">
                    No milestones found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 flex-wrap">
        {Object.entries(STATUS_COLORS_LOCAL).map(([status, cls]) => (
          <div key={status} className="flex items-center gap-2">
            <span className={cn("text-xs px-2.5 py-0.5 rounded-full font-medium", cls)}>{status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
