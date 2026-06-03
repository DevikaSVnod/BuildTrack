"use client";
import { useEffect, useState } from "react";
import { ClipboardCheck, UserCheck, UserX, TrendingUp, Download } from "lucide-react";
import { operationalApi } from "@/lib/api";

interface AttendanceRow {
  id: number;
  name: string;
  role: string;
  status: string;
  project: string;
}

const STATUS_STYLE: Record<string, string> = {
  Present: "bg-green-100 text-green-700",
  Absent:  "bg-red-100   text-red-700",
  Late:    "bg-amber-100 text-amber-700",
};

export default function AttendancePage() {
  const [rows, setRows] = useState<AttendanceRow[]>([]);

  useEffect(() => {
    operationalApi.attendance().then((r) => setRows(r.data)).catch(() => {});
  }, []);

  const present = rows.filter((a) => a.status === "Present").length;
  const absent  = rows.filter((a) => a.status === "Absent").length;
  const rate    = rows.length ? Math.round((present / rows.length) * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Attendance Register</h1>
          <p className="text-gray-500 text-sm mt-1">
            Labour Management System · {new Date().toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors">
          <Download size={15} /> Export Report
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Total Workforce", value: rows.length, icon: ClipboardCheck, color: "text-primary",    bg: "bg-primary/10"  },
          { label: "Present Today",   value: present,     icon: UserCheck,      color: "text-green-600",  bg: "bg-green-50"    },
          { label: "Absent / Leave",  value: absent,      icon: UserX,          color: "text-red-600",    bg: "bg-red-50"      },
          { label: "Attendance Rate", value: `${rate}%`,  icon: TrendingUp,     color: "text-amber-600",  bg: "bg-amber-50"    },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex items-center gap-4">
            <div className={`p-3 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={20} className={color} />
            </div>
            <div>
              <p className="text-sm text-gray-500">{label}</p>
              <p className="text-2xl font-bold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-50">
          <h2 className="font-semibold text-gray-900">Today&apos;s Attendance Log</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="text-left px-6 py-3">Employee</th>
              <th className="text-left px-6 py-3">Project</th>
              <th className="text-left px-6 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rows.map((a) => (
              <tr key={a.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-xs font-bold">
                      {a.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900">{a.name}</p>
                      <p className="text-xs text-gray-400">{a.role}</p>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">{a.project}</td>
                <td className="px-6 py-4">
                  <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${STATUS_STYLE[a.status] || ""}`}>{a.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
