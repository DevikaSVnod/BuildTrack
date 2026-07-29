"use client";
import {
  Building2, CheckSquare, FolderOpen,
  ShieldCheck, TrendingUp, HardHat,
  ArrowRight,
} from "lucide-react";
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import RecentProjects from "@/components/dashboard/RecentProjects";
import { projectsApi, tasksApi, teamApi, documentsApi, operationalApi } from "@/lib/api";
import type { Project, Task, TeamMember, Document } from "@/types";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { usePageData } from "@/hooks/usePageData";
import { clearPageCache, isValidDashboardCache, readPageCache } from "@/lib/pageCache";
import Link from "next/link";
import { useLayoutEffect } from "react";

interface DashboardData {
  projects: Project[];
  tasks: Task[];
  members: TeamMember[];
  documents: Document[];
  budgetRows: BudgetRow[];
  safetyMetrics: SafetyMetrics;
}

const PIE_COLORS = ["#3B82F6", "#F59E0B", "#10B981", "#94A3B8"];
const STATUS_ORDER = ["Planning", "In Progress", "Completed", "On Hold"];

interface BudgetRow {
  project: string;
  budget_cr: number;
  spent_cr: number;
  utilization_pct: number;
}

interface SafetyMetrics {
  safety_score?: number;
  open_incidents?: number;
}

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export default function DashboardPage() {
  const user = useCurrentUser();

  // Drop legacy prefetch cache that stored {budget,safety,...} under the same key
  // (caused all dashboard cards to show 0).
  useLayoutEffect(() => {
    const cached = readPageCache<unknown>("dashboard");
    if (cached && !isValidDashboardCache(cached)) {
      clearPageCache("dashboard");
    }
  }, []);

  const { data, loading } = usePageData<DashboardData>("dashboard", async () => {
    const results = await Promise.allSettled([
      projectsApi.list(),
      tasksApi.list(),
      teamApi.list(),
      documentsApi.list(),
      operationalApi.budget(),
      operationalApi.safetyMetrics(),
    ]);
    const val = <T,>(i: number, fallback: T): T =>
      results[i].status === "fulfilled" ? (results[i] as PromiseFulfilledResult<{ data: T }>).value.data : fallback;

    return {
      projects: val(0, []),
      tasks: val(1, []),
      members: val(2, []),
      documents: val(3, []),
      budgetRows: val(4, []),
      safetyMetrics: val(5, {}),
    };
  });

  const projects = data?.projects ?? [];
  const tasks = data?.tasks ?? [];
  const members = data?.members ?? [];
  const documents = data?.documents ?? [];
  const budgetRows = data?.budgetRows ?? [];
  const safetyMetrics = data?.safetyMetrics ?? {};
  const showLoading = loading && !data;

  const totalBudgetCr = budgetRows.reduce((sum, r) => sum + r.budget_cr, 0);
  const totalSpentCr = budgetRows.reduce((sum, r) => sum + r.spent_cr, 0);
  const budgetUtilPct = totalBudgetCr > 0
    ? Math.round((totalSpentCr / totalBudgetCr) * 100)
    : 0;
  const budgetChartData = budgetRows.map((r) => ({
    project: r.project.split(" ").slice(0, 2).join(" "),
    budget: r.budget_cr,
    spent: r.spent_cr,
  }));

  const activeProjects  = projects.filter((p) => p.status === "In Progress").length;
  const openActivities  = tasks.filter((t) => t.status !== "Done").length;
  const workforce       = new Set(members.map((m) => m.user_id)).size;
  const statusBreakdown = STATUS_ORDER.map((status) => ({
    name: status,
    value: projects.filter((p) => p.status === status).length,
  })).filter((s) => s.value > 0);

  const highPriorityTasks = tasks.filter((t) => t.priority === "High" && t.status !== "Done").length;

  const KPI_CARDS = [
    {
      title: "Active Projects",
      value: showLoading ? "—" : activeProjects,
      sub: `${projects.length} total projects`,
      icon: Building2, color: "text-blue-600", bg: "bg-blue-50",
      href: "/projects", trend: showLoading ? "" : `${projects.length} indexed`,
    },
    {
      title: "Open Site Activities",
      value: showLoading ? "—" : openActivities,
      sub: `${tasks.filter((t) => t.status === "Done").length} completed`,
      icon: CheckSquare, color: "text-amber-600", bg: "bg-amber-50",
      href: "/tasks", trend: showLoading ? "" : `${highPriorityTasks} high priority`,
    },
    {
      title: "Workforce on Roll",
      value: showLoading ? "—" : workforce,
      sub: "Personnel across projects",
      icon: HardHat, color: "text-primary", bg: "bg-primary/10",
      href: "/team", trend: "View LMS →",
    },
    {
      title: "Documents Filed",
      value: showLoading ? "—" : documents.length,
      sub: "In document register",
      icon: FolderOpen, color: "text-purple-600", bg: "bg-purple-50",
      href: "/documents", trend: "View DMS →",
    },
    {
      title: "Safety Score",
      value: showLoading ? "—" : `${safetyMetrics.safety_score ?? "—"}/100`,
      sub: showLoading ? "Loading…" : `${safetyMetrics.open_incidents ?? 0} open incidents`,
      icon: ShieldCheck, color: "text-green-600", bg: "bg-green-50",
      href: "/safety", trend: "Good standing",
    },
    {
      title: "Budget Utilization",
      value: showLoading ? "—" : `${budgetUtilPct}%`,
      sub: showLoading
        ? "Loading…"
        : `₹${totalSpentCr.toFixed(1)}Cr of ₹${totalBudgetCr.toFixed(0)}Cr spent`,
      icon: TrendingUp, color: "text-rose-600", bg: "bg-rose-50",
      href: "/projects", trend: "On track",
    },
  ];

  return (
    <div className="space-y-6">
      <div>
          <h1 className="text-2xl font-bold text-gray-900" suppressHydrationWarning>
            {getGreeting()}, {user?.full_name?.split(" ")[0] ?? ""}
          </h1>
          <p className="text-gray-500 text-sm mt-1" suppressHydrationWarning>
            {new Date().toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
            &nbsp;·&nbsp;Here&apos;s your site overview for today.
          </p>
        </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {KPI_CARDS.map(({ title, value, sub, icon: Icon, color, bg, href, trend }) => (
          <Link
            key={title}
            href={href}
            className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex items-start gap-4 hover:shadow-md hover:border-primary/20 transition-all duration-200 group"
          >
            <div className={`p-3 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={22} className={color} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-500 font-medium">{title}</p>
              <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
              <p className="text-xs text-gray-400 mt-1">{sub}</p>
              {trend ? <p className={`text-xs font-medium mt-2 ${color}`}>{trend}</p> : null}
            </div>
            <ArrowRight size={16} className="text-gray-200 group-hover:text-primary mt-1 transition-colors" />
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900">Project Status Breakdown</h2>
            <Link href="/projects" className="text-xs text-primary font-medium hover:underline flex items-center gap-1">
              All Projects <ArrowRight size={12} />
            </Link>
          </div>
          {statusBreakdown.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={statusBreakdown}
                  cx="50%" cy="50%"
                  innerRadius={55} outerRadius={95}
                  paddingAngle={3} dataKey="value"
                >
                  {statusBreakdown.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v, n) => [v, n]} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-56 flex items-center justify-center text-gray-400 text-sm">
              {showLoading ? "Loading…" : "No project data yet"}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900">Budget vs Spent (₹ Cr)</h2>
          </div>
          {budgetChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={budgetChartData} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="project" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="budget" name="Budget" fill="#CBD5E1" radius={[4, 4, 0, 0]} />
                <Bar dataKey="spent" name="Spent" fill="#1E3A5F" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-56 flex items-center justify-center text-gray-400 text-sm">
              {showLoading ? "Loading budget data…" : "No budget data yet"}
            </div>
          )}
        </div>
      </div>

      <RecentProjects projects={projects} />
    </div>
  );
}
