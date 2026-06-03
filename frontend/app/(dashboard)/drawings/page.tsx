"use client";
import { useEffect, useState } from "react";
import { Layers, Download, Eye, CheckCircle2, Clock, XCircle, Search } from "lucide-react";
import { operationalApi } from "@/lib/api";

interface Drawing {
  id: number;
  drawingNo: string;
  title: string;
  discipline: string;
  rev: string;
  project: string;
  status: string;
  uploadedBy: string;
}

const DISC_COLORS: Record<string, string> = {
  Structural:    "bg-blue-100 text-blue-700",
  Architectural: "bg-purple-100 text-purple-700",
  MEP:           "bg-green-100 text-green-700",
  Civil:         "bg-amber-100 text-amber-700",
  Electrical:    "bg-red-100 text-red-700",
};

const STATUS_STYLE: Record<string, { color: string; icon: typeof CheckCircle2 }> = {
  Approved:      { color: "text-green-600",  icon: CheckCircle2 },
  "Under Review":{ color: "text-amber-600",  icon: Clock       },
  Superseded:    { color: "text-gray-400",   icon: XCircle     },
};

const DISCIPLINES = ["All", "Structural", "Architectural", "MEP", "Civil", "Electrical"];

export default function DrawingsPage() {
  const [drawings, setDrawings] = useState<Drawing[]>([]);

  useEffect(() => {
    operationalApi.drawings().then((r) => setDrawings(r.data)).catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Drawings & Specifications</h1>
          <p className="text-gray-500 text-sm mt-1">Document Management System · Drawing Register</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors">
          <Layers size={15} /> Upload Drawing
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Drawings",  value: drawings.length, color: "text-primary",   bg: "bg-primary/10"  },
          { label: "Approved",        value: drawings.filter((d) => d.status === "Approved").length, color: "text-green-600", bg: "bg-green-50"    },
          { label: "Under Review",    value: drawings.filter((d) => d.status === "Under Review").length, color: "text-amber-600", bg: "bg-amber-50"    },
        ].map(({ label, value, color, bg }) => (
          <div key={label} className={`rounded-xl p-4 ${bg} border border-gray-100`}>
            <p className="text-sm text-gray-600">{label}</p>
            <p className={`text-3xl font-black mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            placeholder="Search drawing no. or title..."
            className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {DISCIPLINES.map((d) => (
            <button key={d} className="px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-gray-200 text-gray-600 hover:border-primary hover:text-primary transition-colors">
              {d}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="text-left px-6 py-3">Drawing No.</th>
              <th className="text-left px-6 py-3">Title</th>
              <th className="text-left px-6 py-3">Discipline</th>
              <th className="text-left px-6 py-3 hidden md:table-cell">Revision</th>
              <th className="text-left px-6 py-3 hidden lg:table-cell">Project</th>
              <th className="text-left px-6 py-3">Status</th>
              <th className="px-6 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {drawings.map((d) => {
              const s = STATUS_STYLE[d.status] || STATUS_STYLE["Under Review"];
              const StatusIcon = s.icon;
              return (
                <tr key={d.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 text-sm font-mono font-semibold text-primary">{d.drawingNo}</td>
                  <td className="px-6 py-4 text-sm font-medium text-gray-900 max-w-xs truncate">{d.title}</td>
                  <td className="px-6 py-4">
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${DISC_COLORS[d.discipline] || ""}`}>
                      {d.discipline}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500 hidden md:table-cell">{d.rev}</td>
                  <td className="px-6 py-4 text-sm text-gray-500 hidden lg:table-cell">{d.project}</td>
                  <td className="px-6 py-4">
                    <div className={`flex items-center gap-1.5 text-xs font-semibold ${s.color}`}>
                      <StatusIcon size={12} /> {d.status}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-1.5 justify-end">
                      <button className="p-1.5 text-gray-400 hover:text-primary rounded-lg hover:bg-gray-100 transition-colors">
                        <Eye size={14} />
                      </button>
                      <button className="p-1.5 text-gray-400 hover:text-primary rounded-lg hover:bg-gray-100 transition-colors">
                        <Download size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
