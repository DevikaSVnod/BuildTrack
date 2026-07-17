"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Layers, CheckCircle2, Clock, XCircle, Search, Trash2, Loader2 } from "lucide-react";
import { operationalApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";
import { downloadFile } from "@/lib/fileAccess";
import { cn } from "@/lib/utils";

const FileActionButtons = dynamic(() => import("@/components/files/FileActionButtons"), {
  ssr: false,
  loading: () => <div className="h-7 w-14 rounded bg-gray-100 animate-pulse" />,
});
const Modal = dynamic(() => import("@/components/ui/Modal"), { ssr: false });
const DrawingUpload = dynamic(() => import("@/components/drawings/DrawingUpload"), { ssr: false });
const FilePreviewModal = dynamic(() => import("@/components/files/FilePreviewModal"), { ssr: false });

interface Drawing {
  id: number;
  drawingNo: string;
  title: string;
  discipline: string;
  rev: string;
  project: string;
  status: string;
  uploadedBy: string;
  file_type?: string;
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
  const {
    data: drawings,
    loading,
    refreshing,
    reload,
  } = usePageData<Drawing[]>("drawings", () => operationalApi.drawings().then((r) => r.data));
  const [showUpload, setShowUpload] = useState(false);
  const [previewDrawing, setPreviewDrawing] = useState<Drawing | null>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const searchParams = useSearchParams();
  const rows = drawings ?? [];

  useEffect(() => {
    const open = searchParams.get("open");
    if (open !== "view" || rows.length === 0) return;
    const drawingId = searchParams.get("drawingId");
    const drawingNo = searchParams.get("drawingNo");
    const match = drawingId
      ? rows.find((d) => d.id === Number(drawingId))
      : drawingNo
        ? rows.find((d) => d.drawingNo.toLowerCase() === drawingNo.toLowerCase())
        : undefined;
    if (match) {
      setPreviewDrawing(match);
      setHighlightId(match.id);
    }
  }, [searchParams, rows]);

  const handleDelete = async (id: number, drawingNo: string) => {
    if (!confirm(`Delete drawing ${drawingNo}? This cannot be undone.`)) return;
    try {
      await operationalApi.deleteDrawing(id);
      reload();
    } catch {
      alert("Could not delete this drawing. Please try again.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Drawings & Specifications</h1>
          <p className="text-gray-500 text-sm mt-1">Document Management System · Drawing Register</p>
        </div>
        <button
          type="button"
          onClick={() => setShowUpload(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <Layers size={15} /> Upload Drawing
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Drawings",  value: rows.length, color: "text-primary",   bg: "bg-primary/10"  },
          { label: "Approved",        value: rows.filter((d) => d.status === "Approved").length, color: "text-green-600", bg: "bg-green-50"    },
          { label: "Under Review",    value: rows.filter((d) => d.status === "Under Review").length, color: "text-amber-600", bg: "bg-amber-50"    },
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
        {refreshing && !loading && (
          <div className="flex items-center gap-2 px-4 py-2 text-xs text-gray-400 border-b border-gray-50">
            <Loader2 size={12} className="animate-spin text-primary" />
            Updating…
          </div>
        )}
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
            {loading && rows.length === 0 ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  <td colSpan={7} className="px-6 py-4">
                    <div className="h-4 bg-gray-100 rounded animate-pulse" />
                  </td>
                </tr>
              ))
            ) : (
            rows.map((d) => {
              const s = STATUS_STYLE[d.status] || STATUS_STYLE["Under Review"];
              const StatusIcon = s.icon;
              return (
                <tr key={d.id} className={cn("hover:bg-gray-50 transition-colors", highlightId === d.id && "bg-primary/5 ring-2 ring-inset ring-primary/30")}>
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
                      <FileActionButtons
                        resource="drawings"
                        lookup={{ kind: "drawingNo", drawingNo: d.drawingNo }}
                        title={`${d.drawingNo} – ${d.title}`}
                        filename={`${d.drawingNo}_${d.title}.${(d.file_type || "png").toLowerCase()}`}
                        fileType={d.file_type || "PNG"}
                      />
                      <button
                        type="button"
                        onClick={() => handleDelete(d.id, d.drawingNo)}
                        title="Delete"
                        className="p-1.5 text-gray-400 hover:text-danger rounded-lg hover:bg-red-50 transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })
            )}
          </tbody>
        </table>
      </div>

      <Modal open={showUpload} onClose={() => setShowUpload(false)} title="Upload Drawing" size="lg">
        <DrawingUpload
          onUploaded={() => {
            setShowUpload(false);
            reload();
          }}
          onCancel={() => setShowUpload(false)}
        />
      </Modal>

      {previewDrawing && (
        <FilePreviewModal
          open={!!previewDrawing}
          onClose={() => setPreviewDrawing(null)}
          title={`${previewDrawing.drawingNo} – ${previewDrawing.title}`}
          resource="drawings"
          lookup={{ kind: "drawingNo", drawingNo: previewDrawing.drawingNo }}
          fileType={previewDrawing.file_type || "PNG"}
          onDownload={async () => {
            await downloadFile(
              "drawings",
              { kind: "drawingNo", drawingNo: previewDrawing.drawingNo },
              `${previewDrawing.drawingNo}_${previewDrawing.title}.${(previewDrawing.file_type || "png").toLowerCase()}`
            );
          }}
        />
      )}
    </div>
  );
}
