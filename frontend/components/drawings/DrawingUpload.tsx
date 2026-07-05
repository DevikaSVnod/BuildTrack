"use client";

import { useEffect, useRef, useState } from "react";
import { Upload, X, Layers } from "lucide-react";
import Button from "@/components/ui/Button";
import { operationalApi, projectsApi } from "@/lib/api";
import type { Project } from "@/types";

const DISCIPLINES = ["Structural", "Architectural", "MEP", "Civil", "Electrical"];
const STATUSES = ["Under Review", "Approved", "Superseded"];

interface DrawingUploadProps {
  onUploaded: () => void;
  onCancel: () => void;
}

export default function DrawingUpload({ onUploaded, onCancel }: DrawingUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [previewFile, setPreviewFile] = useState<File | null>(null);
  const [drawingNo, setDrawingNo] = useState("");
  const [title, setTitle] = useState("");
  const [discipline, setDiscipline] = useState("Architectural");
  const [revision, setRevision] = useState("Rev A");
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("Under Review");
  const [sheetNotes, setSheetNotes] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const previewInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    projectsApi.list().then((r) => setProjects(r.data)).catch(() => {});
  }, []);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  };

  const handleUpload = async () => {
    if (!file || !drawingNo.trim() || !title.trim()) return;
    setUploading(true);
    setError("");
    try {
      await operationalApi.uploadDrawing({
        file,
        previewFile: previewFile || undefined,
        drawingNo: drawingNo.trim(),
        title: title.trim(),
        discipline,
        revision,
        projectId: projectId ? parseInt(projectId, 10) : undefined,
        status,
        sheetNotes: sheetNotes.trim() || undefined,
      });
      onUploaded();
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } } };
      setError(ax?.response?.data?.detail || "Upload failed. Please try again.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-4">
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
          accept=".dwg,.png,.pdf,.jpg,.jpeg"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        {file ? (
          <div className="flex items-center justify-center gap-3">
            <Layers size={24} className="text-primary" />
            <div className="text-left">
              <p className="font-medium text-gray-900 text-sm">{file.name}</p>
              <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setFile(null);
              }}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X size={14} className="text-gray-400" />
            </button>
          </div>
        ) : (
          <>
            <Upload size={32} className="text-gray-300 mx-auto mb-3" />
            <p className="font-medium text-gray-700 text-sm">Drop a drawing or click to browse</p>
            <p className="text-xs text-gray-400 mt-1">DWG, PNG, PDF, JPG up to 50MB</p>
          </>
        )}
      </div>

      {file?.name.toLowerCase().endsWith(".dwg") && (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">
            Optional PNG/JPG preview (auto-generated from DWG if omitted)
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => previewInputRef.current?.click()}
              className="px-3 py-2 text-sm border border-gray-200 rounded-lg hover:border-primary"
            >
              {previewFile ? previewFile.name : "Choose preview image"}
            </button>
            {previewFile && (
              <button
                type="button"
                onClick={() => setPreviewFile(null)}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                Remove
              </button>
            )}
          </div>
          <input
            ref={previewInputRef}
            type="file"
            className="hidden"
            accept=".png,.jpg,.jpeg"
            onChange={(e) => setPreviewFile(e.target.files?.[0] || null)}
          />
          <p className="text-xs text-gray-500">
            The server converts DWG to PNG for search automatically. Upload a preview only
            if you want to override the auto-generated image.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Drawing No. *</label>
          <input
            value={drawingNo}
            onChange={(e) => setDrawingNo(e.target.value)}
            placeholder="e.g. AR-011-A"
            className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Revision</label>
          <input
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Title *</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Level 2 Floor Plan"
          className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Discipline</label>
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
          >
            {DISCIPLINES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Project</label>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
          >
            <option value="">No project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          Searchable layout notes (recommended for floor plans)
        </label>
        <textarea
          value={sheetNotes}
          onChange={(e) => setSheetNotes(e.target.value)}
          rows={4}
          placeholder="Describe rooms, zones, and circulation — e.g. Kitchen east of living room; master bedroom with ensuite..."
          className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary resize-y"
        />
        <p className="text-xs text-gray-500">
          Optional. Text is also auto-extracted from the file (vision for PNG, strings for DWG).
        </p>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex justify-end gap-3">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          onClick={handleUpload}
          loading={uploading}
          disabled={!file || !drawingNo.trim() || !title.trim()}
        >
          Upload Drawing
        </Button>
      </div>
    </div>
  );
}
