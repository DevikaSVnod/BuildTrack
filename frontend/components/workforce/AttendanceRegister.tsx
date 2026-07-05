"use client";
import { ClipboardCheck, UserCheck, UserX, TrendingUp } from "lucide-react";

export interface AttendanceRow {
  id: number;
  name: string;
  role: string;
  status: string;
  project: string;
}

const STATUS_STYLE: Record<string, string> = {
  Present: "bg-green-100 text-green-700",
  Absent: "bg-red-100 text-red-700",
  Late: "bg-amber-100 text-amber-700",
};

interface AttendanceRegisterProps {
  rows: AttendanceRow[];
  loading?: boolean;
}

export default function AttendanceRegister({ rows, loading }: AttendanceRegisterProps) {
  const present = rows.filter((a) => a.status === "Present").length;
  const absent = rows.filter((a) => a.status === "Absent").length;
  const rate = rows.length ? Math.round((present / rows.length) * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "On Register", value: loading ? "—" : rows.length, icon: ClipboardCheck, color: "text-primary", bg: "bg-primary/10" },
          { label: "Present Today", value: loading ? "—" : present, icon: UserCheck, color: "text-green-600", bg: "bg-green-50" },
          { label: "Absent / Leave", value: loading ? "—" : absent, icon: UserX, color: "text-red-600", bg: "bg-red-50" },
          { label: "Attendance Rate", value: loading ? "—" : `${rate}%`, icon: TrendingUp, color: "text-amber-600", bg: "bg-amber-50" },
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
          <h2 className="font-semibold text-gray-900">Today&apos;s Attendance</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {new Date().toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
          </p>
        </div>
        {loading && rows.length === 0 ? (
          <div className="p-8 space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-12 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="px-6 py-10 text-center text-sm text-gray-400">No attendance records for today</p>
        ) : (
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
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${STATUS_STYLE[a.status] || ""}`}>
                      {a.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
