"use client";
import { ShieldCheck, AlertTriangle, CheckCircle2, HardHat, FileWarning } from "lucide-react";
import { operationalApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";

interface Incident {
  id: number;
  date: string | null;
  type: string;
  description: string;
  project: string;
  severity: string;
  status: string;
  reportedBy: string;
}

interface SafetyMetrics {
  safety_score?: number;
  safe_working_days?: number;
  open_incidents?: number;
  ppe_compliance_pct?: number;
  pending_inspections?: number;
}

const SEV: Record<string, string> = {
  High:   "bg-red-100    text-red-700",
  Medium: "bg-amber-100  text-amber-700",
  Low:    "bg-green-100  text-green-700",
};

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  Open:     AlertTriangle,
  Closed:   CheckCircle2,
  Resolved: CheckCircle2,
};

const STATUS_COLOR: Record<string, string> = {
  Open:     "text-red-500",
  Closed:   "text-gray-400",
  Resolved: "text-green-500",
};

interface SafetyData {
  incidents: Incident[];
  metrics: SafetyMetrics;
}

export default function SafetyPage() {
  const { data, loading } = usePageData<SafetyData>("safety", async () => {
    const [inc, met] = await Promise.all([
      operationalApi.safetyIncidents(),
      operationalApi.safetyMetrics(),
    ]);
    return { incidents: inc.data, metrics: met.data };
  });
  const incidents = data?.incidents ?? [];
  const metrics = data?.metrics ?? {};
  const showLoading = loading && !data;

  const SAFETY_METRICS = [
    { label: "Safe Working Days", value: metrics.safe_working_days ?? "—", icon: ShieldCheck, color: "text-green-600", bg: "bg-green-50" },
    { label: "Open Incidents", value: metrics.open_incidents ?? "—", icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "PPE Compliance", value: metrics.ppe_compliance_pct != null ? `${metrics.ppe_compliance_pct}%` : "—", icon: HardHat, color: "text-primary", bg: "bg-primary/10" },
    { label: "Pending Inspections", value: metrics.pending_inspections ?? "—", icon: FileWarning, color: "text-amber-600", bg: "bg-amber-50" },
  ];

  return (
    <div className="space-y-6 min-w-0 max-w-full">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">Safety & HSE Register</h1>
          <p className="text-gray-500 text-sm mt-1">Incident log and HSE metrics across projects</p>
        </div>
        <button className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-xl text-sm font-semibold hover:bg-red-700 transition-colors">
          <AlertTriangle size={15} /> Report Incident
        </button>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {SAFETY_METRICS.map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-3 min-w-0">
            <div className={`p-2.5 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={18} className={color} />
            </div>
            <div className="min-w-0">
              <p className="text-xs sm:text-sm text-gray-500 truncate">{label}</p>
              <p className="text-xl sm:text-2xl font-bold text-gray-900">{showLoading ? "—" : value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-gradient-to-r from-green-600 to-green-500 rounded-2xl p-5 sm:p-6 text-white flex items-center justify-between gap-4 overflow-hidden">
        <div className="min-w-0">
          <p className="text-green-100 text-sm font-medium">Site Safety Score</p>
          <p className="text-4xl sm:text-5xl font-black mt-1">{showLoading ? "—" : metrics.safety_score}<span className="text-xl sm:text-2xl">/100</span></p>
          <p className="text-green-100 text-sm mt-2 truncate">
            {metrics.pending_inspections != null
              ? `${metrics.pending_inspections} pending inspections`
              : "Track incidents and inspections across projects"}
          </p>
        </div>
        <ShieldCheck size={64} className="text-white/20 flex-shrink-0 hidden sm:block" />
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden min-w-0">
        <div className="px-4 sm:px-6 py-4 border-b border-gray-50">
          <h2 className="font-semibold text-gray-900">Incident & Observation Log</h2>
        </div>
        <table className="w-full table-fixed">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="text-left px-3 sm:px-4 py-3 w-[88px]">Date</th>
              <th className="text-left px-3 sm:px-4 py-3 w-[18%]">Type</th>
              <th className="text-left px-3 sm:px-4 py-3">Description</th>
              <th className="text-left px-3 sm:px-4 py-3 w-[20%] hidden lg:table-cell">Project</th>
              <th className="text-left px-3 sm:px-4 py-3 w-[72px]">Severity</th>
              <th className="text-left px-3 sm:px-4 py-3 w-[88px] hidden sm:table-cell">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {incidents.length > 0 ? incidents.map((inc) => {
              const StatusIcon = STATUS_ICON[inc.status] || CheckCircle2;
              return (
                <tr key={inc.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-3 sm:px-4 py-3 text-xs sm:text-sm text-gray-500 truncate">{inc.date || "—"}</td>
                  <td className="px-3 sm:px-4 py-3 text-xs sm:text-sm font-medium text-gray-900 truncate">{inc.type}</td>
                  <td className="px-3 sm:px-4 py-3 text-xs sm:text-sm text-gray-600 truncate">{inc.description}</td>
                  <td className="px-3 sm:px-4 py-3 text-xs sm:text-sm text-gray-500 hidden lg:table-cell truncate">{inc.project}</td>
                  <td className="px-3 sm:px-4 py-3">
                    <span className={`text-[10px] sm:text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap ${SEV[inc.severity] ?? ""}`}>{inc.severity}</span>
                  </td>
                  <td className="px-3 sm:px-4 py-3 hidden sm:table-cell">
                    <div className={`flex items-center gap-1 text-[10px] sm:text-xs font-semibold truncate ${STATUS_COLOR[inc.status] ?? ""}`}>
                      <StatusIcon size={12} className="flex-shrink-0" />
                      <span className="truncate">{inc.status}</span>
                    </div>
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-400">
                  {showLoading ? "Loading incidents…" : "No incidents recorded"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
