"use client";
import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import {
  Upload, FileText, Sparkles, FolderOpen,
  Layers, BookOpen, Link2,
} from "lucide-react";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import DocumentList from "@/components/documents/DocumentList";
import DocumentUpload from "@/components/documents/DocumentUpload";
import { documentsApi, projectsApi } from "@/lib/api";
import type { Document, Project } from "@/types";

const FILE_TYPES = ["All", "PDF", "DWG", "XLSX", "JPG", "PNG"];

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [projectFilter, setProjectFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("All");
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const searchParams = useSearchParams();
  const highlightRef = useRef<HTMLDivElement>(null);

  const fetchDocs = async () => {
    setLoading(true);
    try {
      const [d, p] = await Promise.all([documentsApi.list(), projectsApi.list()]);
      setDocuments(d.data);
      setProjects(p.data);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDocs(); }, []);

  useEffect(() => {
    const id = searchParams.get("docId");
    if (id) {
      setHighlightId(Number(id));
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 700);
      const timer = setTimeout(() => setHighlightId(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this document?")) return;
    await documentsApi.delete(id);
    fetchDocs();
  };

  const filtered = documents.filter((d) => {
    const matchProject = projectFilter === "all" || String(d.project_id) === projectFilter;
    const matchType = typeFilter === "All" || d.file_type?.toUpperCase() === typeFilter;
    return matchProject && matchType;
  });

  return (
    <div className="space-y-6">

      {/* DMS Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-widest text-purple-700 bg-purple-100 px-2.5 py-0.5 rounded-full">
              DMS · Document Management
            </span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Document Control</h1>
          <p className="text-gray-500 text-sm mt-1">{documents.length} files across all projects</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <a
            href="/drawings"
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-xl text-sm font-medium hover:bg-gray-200 transition-colors"
          >
            <Layers size={15} /> Drawings
          </a>
          <a
            href="/handover"
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-xl text-sm font-medium hover:bg-gray-200 transition-colors"
          >
            <BookOpen size={15} /> Handover
          </a>
          <Button onClick={() => setShowUpload(true)}>
            <Upload size={16} /> Upload
          </Button>
        </div>
      </div>

      {/* DMS KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {([
          { label: "Total Documents", value: documents.length, icon: FolderOpen, color: "text-primary",   bg: "bg-primary/10" },
          { label: "PDFs",            value: documents.filter((d) => d.file_type?.toUpperCase() === "PDF").length,  icon: FileText, color: "text-red-600",   bg: "bg-red-50"     },
          { label: "Drawings (DWG)",  value: documents.filter((d) => d.file_type?.toUpperCase() === "DWG").length,  icon: Layers,   color: "text-blue-600",  bg: "bg-blue-50"    },
          { label: "Spreadsheets",    value: documents.filter((d) => d.file_type?.toUpperCase() === "XLSX").length, icon: Link2,    color: "text-green-600", bg: "bg-green-50"   },
        ] as const).map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-3">
            <div className={`p-2.5 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={18} className={color} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-xl font-bold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <select
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
          className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="all">All Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <div className="flex gap-1 flex-wrap">
          {FILE_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                typeFilter === t
                  ? "bg-primary text-white"
                  : "bg-white text-gray-600 border border-gray-200 hover:border-primary"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Search highlight banner */}
      {highlightId && (
        <div
          ref={highlightRef}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary/5 border border-primary/20 rounded-xl text-sm text-primary font-medium"
        >
          <Sparkles size={14} />
          Navigated from search — document highlighted below
        </div>
      )}

      {loading ? (
        <div className="bg-white rounded-xl border h-64 animate-pulse" />
      ) : filtered.length === 0 ? (
        <div className="text-center py-20">
          <FileText size={48} className="text-gray-200 mx-auto mb-4" />
          <h3 className="font-semibold text-gray-500 mb-2">No documents found</h3>
          <p className="text-gray-400 text-sm mb-6">Upload your first document to get started</p>
          <Button onClick={() => setShowUpload(true)}>
            <Upload size={16} /> Upload Document
          </Button>
        </div>
      ) : (
        <DocumentList documents={filtered} onDelete={handleDelete} highlightId={highlightId} />
      )}

      <Modal open={showUpload} onClose={() => setShowUpload(false)} title="Upload Document">
        <DocumentUpload
          onUploaded={() => { setShowUpload(false); fetchDocs(); }}
          onCancel={() => setShowUpload(false)}
        />
      </Modal>
    </div>
  );
}
