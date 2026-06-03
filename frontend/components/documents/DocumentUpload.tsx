"use client";
import { useState, useRef } from "react";
import { Upload, X, FileText } from "lucide-react";
import Button from "@/components/ui/Button";
import { documentsApi, projectsApi } from "@/lib/api";
import type { Project } from "@/types";
import { useEffect } from "react";

interface DocumentUploadProps {
  onUploaded: () => void;
  onCancel: () => void;
}

export default function DocumentUpload({ onUploaded, onCancel }: DocumentUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [projectId, setProjectId] = useState<string>("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    projectsApi.list().then((r) => setProjects(r.data)).catch(() => {});
  }, []);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await documentsApi.upload(file, projectId ? parseInt(projectId) : undefined);
      onUploaded();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Upload failed. Please try again.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-all"
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept=".pdf,.dwg,.xlsx,.xls,.png,.jpg,.jpeg,.doc,.docx"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        {file ? (
          <div className="flex items-center justify-center gap-3">
            <FileText size={24} className="text-primary" />
            <div className="text-left">
              <p className="font-medium text-gray-900 text-sm">{file.name}</p>
              <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X size={14} className="text-gray-400" />
            </button>
          </div>
        ) : (
          <>
            <Upload size={32} className="text-gray-300 mx-auto mb-3" />
            <p className="font-medium text-gray-700 text-sm">
              Drop a file here or click to browse
            </p>
            <p className="text-xs text-gray-400 mt-1">PDF, DWG, XLSX, PNG, JPG up to 50MB</p>
          </>
        )}
      </div>

      {/* Project selector */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Assign to Project (optional)</label>
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
        >
          <option value="">No project</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex justify-end gap-3">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button onClick={handleUpload} loading={uploading} disabled={!file}>
          Upload Document
        </Button>
      </div>
    </div>
  );
}
