"use client";
import { useEffect, useState } from "react";
import {
  Building2, CheckSquare, Users, FolderOpen,
  ShieldCheck, TrendingUp, HardHat, AlertTriangle,
  ArrowRight, Clock,
} from "lucide-react";
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  LineChart, Line,
} from "recharts";
import RecentProjects from "@/components/dashboard/RecentProjects";
import ActivityFeed from "@/components/dashboard/ActivityFeed";
import { projectsApi, tasksApi, teamApi, documentsApi, operationalApi } from "@/lib/api";
import type { Project, Task, TeamMember, Document } from "@/types";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import Link from "next/link";

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

interface Milestone {
  label: string;
  due: string;
  priority: string;
}

interface SiteWeek {
  week: string;
  completed: number;
  open: number;
}

const PRIORITY_COLOR: Record<string, string> = {
  High:   "bg-red-100 text-red-700",
  Medium: "bg-amber-100 text-amber-700",
  Low:    "bg-blue-100 text-blue-700",
};

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export default function DashboardPage() {
  const user = useCurrentUser();
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [budgetRows, setBudgetRows] = useState<BudgetRow[]>([]);
  const [safetyMetrics, setSafetyMetrics] = useState<SafetyMetrics>({});
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [siteActivity, setSiteActivity] = useState<SiteWeek[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const results = await Promise.allSettled([
        projectsApi.list(),
        tasksApi.list(),
        teamApi.list(),
        documentsApi.list(),
        operationalApi.budget(),
        operationalApi.safetyMetrics(),
        operationalApi.milestones(),
        operationalApi.siteActivity(),
      ]);
      const val = <T,>(i: number, fallback: T): T =>
        results[i].status === "fulfilled" ? (results[i] as PromiseFulfilledResult<{ data: T }>).value.data : fallback;

      if (results.some((r) => r.status === "rejected")) {
        console.error("Dashboard partial load failures:", results.filter((r) => r.status === "rejected"));
      }

      setProjects(val(0, []));
      setTasks(val(1, []));
      setMembers(val(2, []));
      setDocuments(val(3, []));
      setBudgetRows(val(4, []));
      setSafetyMetrics(val(5, {}));
      setMilestones(val(6, []));
      const activity = val(7, {} as { weekly?: SiteWeek[] });
      setSiteActivity(activity.weekly ?? []);
      setLoading(false);
    };
    load().catch((err) => {
      console.error("Dashboard load failed:", err);
      setLoading(false);
    });
  }, []);

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
      value: loading ? "—" : activeProjects,
      sub: `${projects.length} total projects`,
      icon: Building2, color: "text-blue-600", bg: "bg-blue-50",
      href: "/projects", trend: loading ? "" : `${projects.length} indexed`,
    },
    {
      title: "Open Site Activities",
      value: loading ? "—" : openActivities,
      sub: `${tasks.filter((t) => t.status === "Done").length} completed`,
      icon: CheckSquare, color: "text-amber-600", bg: "bg-amber-50",
      href: "/tasks", trend: loading ? "" : `${highPriorityTasks} high priority`,
    },
    {
      title: "Workforce on Roll",
      value: loading ? "—" : workforce,
      sub: "Personnel across projects",
      icon: HardHat, color: "text-primary", bg: "bg-primary/10",
      href: "/team", trend: "View LMS →",
    },
    {
      title: "Documents Filed",
      value: loading ? "—" : documents.length,
      sub: "In document register",
      icon: FolderOpen, color: "text-purple-600", bg: "bg-purple-50",
      href: "/documents", trend: "View DMS →",
    },
    {
      title: "Safety Score",
      value: loading ? "—" : `${safetyMetrics.safety_score ?? "—"}/100`,
      sub: loading ? "Loading…" : `${safetyMetrics.open_incidents ?? 0} open incidents`,
      icon: ShieldCheck, color: "text-green-600", bg: "bg-green-50",
      href: "/safety", trend: "Good standing",
    },
    {
      title: "Budget Utilization",
      value: loading ? "—" : `${budgetUtilPct}%`,
      sub: loading
        ? "Loading…"
        : `₹${totalSpentCr.toFixed(1)}Cr of ₹${totalBudgetCr.toFixed(0)}Cr spent`,
      icon: TrendingUp, color: "text-rose-600", bg: "bg-rose-50",
      href: "/reports", trend: "On track",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900" suppressHydrationWarning>
            {getGreeting()}, {user?.full_name?.split(" ")[0] ?? ""}
          </h1>
          <p className="text-gray-500 text-sm mt-1" suppressHydrationWarning>
            {new Date().toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
            &nbsp;·&nbsp;Here&apos;s your site overview for today.
          </p>
        </div>
        <div className="hidden md:flex items-center gap-2 px-4 py-2 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700 font-medium">
          <AlertTriangle size={15} />
          {loading ? "Loading safety status…" : `${safetyMetrics.open_incidents ?? 0} open safety incidents`}
        </div>
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
              {loading ? "Loading…" : "No project data in search index"}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900">Budget vs Spent (₹ Cr)</h2>
            <Link href="/reports" className="text-xs text-primary font-medium hover:underline flex items-center gap-1">
              Full Report <ArrowRight size={12} />
            </Link>
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
              {loading ? "Loading budget data…" : "No budget data in search index"}
            </div>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">Site Activity Trend (Last 5 Weeks)</h2>
          <Link href="/tasks" className="text-xs text-primary font-medium hover:underline flex items-center gap-1">
            View All Activities <ArrowRight size={12} />
          </Link>
        </div>
        {siteActivity.length > 0 ? (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={siteActivity} margin={{ top: 0, right: 10, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="week" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="completed" name="Completed" stroke="#10B981" strokeWidth={2} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="open" name="Open" stroke="#F59E0B" strokeWidth={2} dot={{ r: 4 }} strokeDasharray="5 5" />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-44 flex items-center justify-center text-gray-400 text-sm">
            {loading ? "Loading site activity…" : "No site activity data in search index"}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <RecentProjects projects={projects} />
        </div>

        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2">
              <Clock size={15} className="text-primary" />
              <h2 className="font-semibold text-gray-900 text-sm">Upcoming Milestones</h2>
            </div>
            <div className="divide-y divide-gray-50">
              {milestones.length > 0 ? milestones.map((item, i) => (
                <div key={i} className="px-5 py-3 flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-800 leading-snug">{item.label}</p>
                    <p className="text-xs text-gray-400 mt-0.5">Due: {item.due}</p>
                  </div>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${PRIORITY_COLOR[item.priority] ?? PRIORITY_COLOR.Medium}`}>
                    {item.priority}
                  </span>
                </div>
              )) : (
                <p className="px-5 py-6 text-sm text-gray-400 text-center">
                  {loading ? "Loading milestones…" : "No milestones in search index"}
                </p>
              )}
            </div>
          </div>

          <ActivityFeed />
        </div>
      </div>
    </div>
  );
}
