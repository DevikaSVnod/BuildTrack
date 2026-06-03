"use client";
import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell,
} from "recharts";
import { Download, TrendingUp, Users, CheckSquare, Building2 } from "lucide-react";
import Button from "@/components/ui/Button";
import { projectsApi, tasksApi, teamApi, operationalApi } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { Project, Task, TeamMember } from "@/types";

const PIE_COLORS = ["#3B82F6", "#F59E0B", "#10B981", "#94A3B8"];

interface BudgetRow {
  project: string;
  budget_cr: number;
  spent_cr: number;
  utilization_pct: number;
}

interface ProductivityMeta {
  completion_rate_pct?: number;
  monthly?: Array<{ month: string; tasks: number; completed: number }>;
}

export default function ReportsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [budgetRows, setBudgetRows] = useState<BudgetRow[]>([]);
  const [productivity, setProductivity] = useState<ProductivityMeta>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      projectsApi.list(),
      tasksApi.list(),
      teamApi.list(),
      operationalApi.budget(),
      operationalApi.productivity(),
    ]).then(([p, t, m, budget, prod]) => {
      setProjects(p.data);
      setTasks(t.data);
      setMembers(m.data);
      setBudgetRows(budget.data);
      setProductivity(prod.data);
    }).catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const completedProjects = projects.filter((p) => p.status === "Completed");
  const completionRate = projects.length > 0
    ? Math.round((completedProjects.length / projects.length) * 100)
    : 0;

  const completedTasks = tasks.filter((t) => t.status === "Done");
  const taskCompletionRate = tasks.length > 0
    ? Math.round((completedTasks.length / tasks.length) * 100)
    : 0;

  const statusData = ["Planning", "In Progress", "Completed", "On Hold"].map((s) => ({
    name: s,
    value: projects.filter((p) => p.status === s).length,
  })).filter((s) => s.value > 0);

  const totalBudget = projects.reduce((sum, p) => sum + (p.budget || 0), 0);
  const budgetChartData = budgetRows.map((r) => ({
    project: r.project.split(" ").slice(0, 2).join(" "),
    budget: r.budget_cr * 1e7,
    actual: r.spent_cr * 1e7,
  }));
  const productivityData = productivity.monthly ?? [];
  const teamProductivityPct = productivity.completion_rate_pct ?? taskCompletionRate;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
          <p className="text-gray-500 text-sm mt-1">Analytics from Azure AI Search (SQL indexer)</p>
        </div>
        <Button variant="outline">
          <Download size={16} /> Export PDF
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {[
          {
            title: "Project Completion Rate",
            value: `${completionRate}%`,
            icon: Building2,
            sub: `${completedProjects.length} of ${projects.length} projects`,
            color: "text-primary",
            bg: "bg-primary/10",
          },
          {
            title: "Task Completion Rate",
            value: `${taskCompletionRate}%`,
            icon: CheckSquare,
            sub: `${completedTasks.length} of ${tasks.length} tasks done`,
            color: "text-green-600",
            bg: "bg-green-50",
          },
          {
            title: "Total Budget Managed",
            value: formatCurrency(totalBudget),
            icon: TrendingUp,
            sub: "Across all projects",
            color: "text-amber-600",
            bg: "bg-amber-50",
          },
          {
            title: "Team Productivity",
            value: `${teamProductivityPct}%`,
            icon: Users,
            sub: `${new Set(members.map((m) => m.user_id)).size} active members`,
            color: "text-purple-600",
            bg: "bg-purple-50",
          },
        ].map((item) => (
          <div key={item.title} className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex items-start gap-4">
            <div className={`p-3 rounded-xl flex-shrink-0 ${item.bg}`}>
              <item.icon size={20} className={item.color} />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium">{item.title}</p>
              <p className="text-2xl font-bold text-gray-900 mt-0.5">{loading ? "—" : item.value}</p>
              <p className="text-xs text-gray-400 mt-1">{item.sub}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="font-semibold text-gray-900 mb-4">Budget vs Actual Spend</h2>
          {budgetChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={budgetChartData} margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="project" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `₹${(v / 1e7).toFixed(0)}Cr`} />
                <Tooltip formatter={(v: number) => formatCurrency(v)} />
                <Legend />
                <Bar dataKey="budget" name="Budget" fill="#1E3A5F" radius={[4, 4, 0, 0]} />
                <Bar dataKey="actual" name="Actual" fill="#F59E0B" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
              {loading ? "Loading…" : "No budget data in search index"}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="font-semibold text-gray-900 mb-4">Project Status Distribution</h2>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={statusData}
                  cx="50%"
                  cy="50%"
                  innerRadius={70}
                  outerRadius={110}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {statusData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">No data</div>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="font-semibold text-gray-900 mb-4">Team Productivity (Tasks per Month)</h2>
        {productivityData.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={productivityData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="tasks" name="Tasks Created" stroke="#1E3A5F" strokeWidth={2} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="completed" name="Tasks Completed" stroke="#10B981" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
            {loading ? "Loading…" : "No productivity data in search index"}
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-50">
          <h2 className="font-semibold text-gray-900">Project Summary</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {["Project", "Status", "Progress", "Budget", "Team", "Tasks"].map((h) => (
                <th key={h} className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {projects.map((p) => (
              <tr key={p.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-6 py-4 font-medium text-sm text-gray-900">{p.name}</td>
                <td className="px-6 py-4">
                  <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium
                    ${p.status === "Completed" ? "bg-green-100 text-green-700" :
                      p.status === "In Progress" ? "bg-amber-100 text-amber-700" :
                      p.status === "Planning" ? "bg-blue-100 text-blue-700" :
                      "bg-gray-100 text-gray-600"}`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <div className="w-20 bg-gray-100 rounded-full h-1.5">
                      <div className="bg-primary h-1.5 rounded-full" style={{ width: `${p.progress}%` }} />
                    </div>
                    <span className="text-xs text-gray-500">{p.progress}%</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">{formatCurrency(p.budget)}</td>
                <td className="px-6 py-4 text-sm text-gray-600">{p.team_size}</td>
                <td className="px-6 py-4 text-sm text-gray-600">{p.task_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
