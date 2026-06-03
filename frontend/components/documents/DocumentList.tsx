"use client";
import { FileText, File, Table, Image, Trash2, ExternalLink, Sparkles } from "lucide-react";
import type { Document } from "@/types";
import { formatDate, formatFileSize, cn } from "@/lib/utils";

interface DocumentListProps {
  documents: Document[];
  onDelete?: (id: number) => void;
  highlightId?: number | null;
}

const FILE_ICONS: Record<string, { icon: typeof FileText; color: string; bg: string }> = {
  PDF: { icon: FileText, color: "text-red-600", bg: "bg-red-50" },
  DWG: { icon: File, color: "text-blue-600", bg: "bg-blue-50" },
  XLSX: { icon: Table, color: "text-green-600", bg: "bg-green-50" },
  PNG: { icon: Image, color: "text-purple-600", bg: "bg-purple-50" },
  JPG: { icon: Image, color: "text-purple-600", bg: "bg-purple-50" },
  JPEG: { icon: Image, color: "text-purple-600", bg: "bg-purple-50" },
};

export default function DocumentList({ documents, onDelete, highlightId }: DocumentListProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">
              Name
            </th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3">
              Project
            </th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3 hidden md:table-cell">
              Uploaded By
            </th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3 hidden lg:table-cell">
              Date
            </th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-6 py-3 hidden lg:table-cell">
              Size
            </th>
            <th className="px-6 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {documents.map((doc) => {
            const fileInfo = FILE_ICONS[doc.file_type?.toUpperCase() || ""] || {
              icon: File,
              color: "text-gray-500",
              bg: "bg-gray-50",
            };
            const Icon = fileInfo.icon;
            const isHighlighted = highlightId === doc.id;
            return (
              <tr
                key={doc.id}
                className={cn(
                  "hover:bg-gray-50 transition-all duration-700",
                  isHighlighted && "bg-primary/5 ring-2 ring-inset ring-primary/30"
                )}
              >
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className={cn("p-2 rounded-lg flex-shrink-0", fileInfo.bg)}>
                      <Icon size={16} className={fileInfo.color} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-gray-900 truncate max-w-xs">
                          {doc.name}
                        </p>
                        {isHighlighted && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-primary bg-primary/10 px-1.5 py-0.5 rounded-full">
                            <Sparkles size={9} /> Search result
                          </span>
                        )}
                      </div>
                      <span className={cn("text-xs font-medium", fileInfo.color)}>
                        {doc.file_type}
                      </span>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-gray-600">{doc.project_name || "—"}</span>
                </td>
                <td className="px-6 py-4 hidden md:table-cell">
                  <span className="text-sm text-gray-600">
                    {doc.uploader?.full_name || "—"}
                  </span>
                </td>
                <td className="px-6 py-4 hidden lg:table-cell">
                  <span className="text-sm text-gray-500">{formatDate(doc.created_at)}</span>
                </td>
                <td className="px-6 py-4 hidden lg:table-cell">
                  <span className="text-sm text-gray-500">{formatFileSize(doc.file_size)}</span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2 justify-end">
                    {doc.file_url && (
                      <a
                        href={doc.file_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 text-gray-400 hover:text-primary rounded-lg hover:bg-gray-100 transition-colors"
                      >
                        <ExternalLink size={15} />
                      </a>
                    )}
                    {onDelete && (
                      <button
                        onClick={() => onDelete(doc.id)}
                        className="p-1.5 text-gray-400 hover:text-danger rounded-lg hover:bg-red-50 transition-colors"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
          {documents.length === 0 && (
            <tr>
              <td colSpan={6} className="text-center py-12 text-gray-400 text-sm">
                No documents uploaded yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
