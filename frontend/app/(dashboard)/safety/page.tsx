"use client";
import { useEffect, useState } from "react";
import { ShieldCheck, AlertTriangle, CheckCircle2, HardHat, FileWarning } from "lucide-react";
import { operationalApi } from "@/lib/api";

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

export default function SafetyPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [metrics, setMetrics] = useState<SafetyMetrics>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      operationalApi.safetyIncidents(),
      operationalApi.safetyMetrics(),
    ]).then(([inc, met]) => {
      setIncidents(inc.data);
      setMetrics(met.data);
    }).catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const SAFETY_METRICS = [
    { label: "Safe Working Days", value: metrics.safe_working_days ?? "—", icon: ShieldCheck, color: "text-green-600", bg: "bg-green-50" },
    { label: "Open Incidents", value: metrics.open_incidents ?? "—", icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "PPE Compliance", value: metrics.ppe_compliance_pct != null ? `${metrics.ppe_compliance_pct}%` : "—", icon: HardHat, color: "text-primary", bg: "bg-primary/10" },
    { label: "Pending Inspections", value: metrics.pending_inspections ?? "—", icon: FileWarning, color: "text-amber-600", bg: "bg-amber-50" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Safety & HSE Register</h1>
          <p className="text-gray-500 text-sm mt-1">Data from Azure AI Search (SQL indexer)</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-xl text-sm font-semibold hover:bg-red-700 transition-colors">
          <AlertTriangle size={15} /> Report Incident
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {SAFETY_METRICS.map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex items-center gap-4">
            <div className={`p-3 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={20} className={color} />
            </div>
            <div>
              <p className="text-sm text-gray-500">{label}</p>
              <p className="text-2xl font-bold text-gray-900">{loading ? "—" : value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-gradient-to-r from-green-600 to-green-500 rounded-2xl p-6 text-white flex items-center justify-between">
        <div>
          <p className="text-green-100 text-sm font-medium">Site Safety Score</p>
          <p className="text-5xl font-black mt-1">{loading ? "—" : metrics.safety_score}<span className="text-2xl">/100</span></p>
          <p className="text-green-100 text-sm mt-2">
            {metrics.pending_inspections != null
              ? `${metrics.pending_inspections} pending inspections`
              : "Safety metrics from search index"}
          </p>
        </div>
        <ShieldCheck size={80} className="text-white/20" />
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-50">
          <h2 className="font-semibold text-gray-900">Incident & Observation Log</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="text-left px-6 py-3">Date</th>
              <th className="text-left px-6 py-3">Type</th>
              <th className="text-left px-6 py-3">Description</th>
              <th className="text-left px-6 py-3 hidden md:table-cell">Project</th>
              <th className="text-left px-6 py-3">Severity</th>
              <th className="text-left px-6 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {incidents.length > 0 ? incidents.map((inc) => {
              const StatusIcon = STATUS_ICON[inc.status] || CheckCircle2;
              return (
                <tr key={inc.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 text-sm text-gray-500 whitespace-nowrap">{inc.date || "—"}</td>
                  <td className="px-6 py-4 text-sm font-medium text-gray-900 whitespace-nowrap">{inc.type}</td>
                  <td className="px-6 py-4 text-sm text-gray-600 max-w-xs truncate">{inc.description}</td>
                  <td className="px-6 py-4 text-sm text-gray-500 hidden md:table-cell whitespace-nowrap">{inc.project}</td>
                  <td className="px-6 py-4">
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${SEV[inc.severity] ?? ""}`}>{inc.severity}</span>
                  </td>
                  <td className="px-6 py-4">
                    <div className={`flex items-center gap-1.5 text-xs font-semibold ${STATUS_COLOR[inc.status] ?? ""}`}>
                      <StatusIcon size={13} />{inc.status}
                    </div>
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={6} className="px-6 py-10 text-center text-sm text-gray-400">
                  {loading ? "Loading incidents…" : "No incidents in search index"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
