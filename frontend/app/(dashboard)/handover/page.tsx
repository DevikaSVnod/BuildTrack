"use client";
import { useEffect, useState } from "react";
import { BookOpen, CheckCircle2, Clock, AlertCircle, Download, Upload } from "lucide-react";
import { operationalApi } from "@/lib/api";

interface HandoverDoc {
  id: number;
  title: string;
  category: string;
  project: string;
  status: string;
  date: string;
  signedBy: string;
}

const STATUS_STYLE: Record<string, { cls: string; icon: typeof CheckCircle2 }> = {
  Signed:        { cls: "bg-green-100 text-green-700", icon: CheckCircle2 },
  Submitted:     { cls: "bg-blue-100  text-blue-700",  icon: Clock        },
  "Under Review":{ cls: "bg-amber-100 text-amber-700", icon: Clock        },
  Pending:       { cls: "bg-gray-100  text-gray-600",  icon: AlertCircle  },
};

export default function HandoverPage() {
  const [docs, setDocs] = useState<HandoverDoc[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    operationalApi.handover()
      .then((r) => setDocs(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Handover Documentation</h1>
          <p className="text-gray-500 text-sm mt-1">Document Management System · Project Closeout</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors">
          <Upload size={15} /> Upload Document
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Total Docs",    value: docs.length, cls: "text-primary",   bg: "bg-primary/10" },
          { label: "Signed",        value: docs.filter((d) => d.status === "Signed").length, cls: "text-green-600", bg: "bg-green-50" },
          { label: "Under Review",  value: docs.filter((d) => d.status === "Under Review").length, cls: "text-amber-600", bg: "bg-amber-50" },
          { label: "Pending",       value: docs.filter((d) => d.status === "Pending").length, cls: "text-gray-600", bg: "bg-gray-50" },
        ].map(({ label, value, cls, bg }) => (
          <div key={label} className={`rounded-xl p-5 border border-gray-100 ${bg}`}>
            <p className="text-sm text-gray-600">{label}</p>
            <p className={`text-3xl font-black mt-1 ${cls}`}>{loading ? "—" : value}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-50">
          <h2 className="font-semibold text-gray-900">Handover Document Register</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              <th className="text-left px-6 py-3">Document Title</th>
              <th className="text-left px-6 py-3">Category</th>
              <th className="text-left px-6 py-3 hidden md:table-cell">Project</th>
              <th className="text-left px-6 py-3">Status</th>
              <th className="text-left px-6 py-3 hidden lg:table-cell">Date</th>
              <th className="px-6 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {docs.map((d) => {
              const s = STATUS_STYLE[d.status] || STATUS_STYLE.Pending;
              const Icon = s.icon;
              return (
                <tr key={d.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-primary/5 rounded-lg">
                        <BookOpen size={14} className="text-primary" />
                      </div>
                      <p className="text-sm font-medium text-gray-900 truncate max-w-xs">{d.title}</p>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-xs font-medium px-2.5 py-1 bg-gray-100 text-gray-600 rounded-full">{d.category}</span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500 hidden md:table-cell">{d.project}</td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ${s.cls}`}>
                      <Icon size={11} /> {d.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-400 hidden lg:table-cell">{d.date}</td>
                  <td className="px-6 py-4">
                    <button className="p-1.5 text-gray-400 hover:text-primary rounded-lg hover:bg-gray-100 transition-colors">
                      <Download size={14} />
                    </button>
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
