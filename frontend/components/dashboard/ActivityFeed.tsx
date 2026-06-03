"use client";
import { useEffect, useState } from "react";
import { getTimeAgo } from "@/lib/utils";
import { CheckCircle2, Upload, UserPlus, FolderPlus, Edit3 } from "lucide-react";
import { tasksApi, documentsApi } from "@/lib/api";
import type { Task, Document } from "@/types";

interface ActivityItem {
  id: string;
  type: "task" | "document" | "team" | "project" | "update";
  text: string;
  time: string;
  user: string;
}

const ACTIVITY_ICONS = {
  task: CheckCircle2,
  document: Upload,
  team: UserPlus,
  project: FolderPlus,
  update: Edit3,
};

const ACTIVITY_COLORS = {
  task: "bg-green-100 text-green-600",
  document: "bg-blue-100 text-blue-600",
  team: "bg-purple-100 text-purple-600",
  project: "bg-primary/10 text-primary",
  update: "bg-amber-100 text-amber-600",
};

function buildActivities(tasks: Task[], documents: Document[]): ActivityItem[] {
  const items: ActivityItem[] = [];

  for (const t of tasks.filter((x) => x.status === "Done").slice(0, 3)) {
    items.push({
      id: `task-${t.id}`,
      type: "task",
      text: `Completed '${t.title}'${t.project_name ? ` on ${t.project_name}` : ""}`,
      time: String(t.created_at),
      user: t.assignee?.full_name || "Team member",
    });
  }

  for (const d of documents.slice(0, 3)) {
    items.push({
      id: `doc-${d.id}`,
      type: "document",
      text: `Uploaded '${d.name}'${d.project_name ? ` to ${d.project_name}` : ""}`,
      time: String(d.created_at),
      user: d.uploader?.full_name || "Team member",
    });
  }

  return items.slice(0, 5);
}

export default function ActivityFeed() {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([tasksApi.list(), documentsApi.list()])
      .then(([t, d]) => setActivities(buildActivities(t.data, d.data)))
      .catch(() => setActivities([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
      <div className="px-6 py-4 border-b border-gray-50">
        <h2 className="font-semibold text-gray-900">Recent Activity</h2>
      </div>
      <div className="divide-y divide-gray-50">
        {activities.length > 0 ? activities.map((activity) => {
          const Icon = ACTIVITY_ICONS[activity.type];
          const colorClass = ACTIVITY_COLORS[activity.type];
          return (
            <div key={activity.id} className="flex items-start gap-4 px-6 py-4">
              <div className={`p-2 rounded-lg flex-shrink-0 ${colorClass}`}>
                <Icon size={14} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-700">
                  <span className="font-medium text-gray-900">{activity.user}</span>{" "}
                  {activity.text}
                </p>
                <p className="text-xs text-gray-400 mt-1">{getTimeAgo(activity.time)}</p>
              </div>
            </div>
          );
        }) : (
          <p className="px-6 py-8 text-sm text-gray-400 text-center">
            {loading ? "Loading activity…" : "No recent activity in search index"}
          </p>
        )}
      </div>
    </div>
  );
}
