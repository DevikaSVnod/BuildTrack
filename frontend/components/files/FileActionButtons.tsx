"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Eye, Download, Loader2 } from "lucide-react";
import { downloadFile, type FileLookup, type FileResource } from "@/lib/fileAccess";

const FilePreviewModal = dynamic(() => import("@/components/files/FilePreviewModal"), {
  ssr: false,
});

interface FileActionButtonsProps {
  resource: FileResource;
  lookup: FileLookup;
  title: string;
  filename: string;
  fileType?: string;
  className?: string;
}

export default function FileActionButtons({
  resource,
  lookup,
  title,
  filename,
  fileType,
  className = "",
}: FileActionButtonsProps) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [busy, setBusy] = useState<"view" | "download" | null>(null);

  const handleDownload = async () => {
    setBusy("download");
    try {
      await downloadFile(resource, lookup, filename);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Download failed";
      window.alert(message);
    } finally {
      setBusy(null);
    }
  };

  const handleView = () => {
    // PNG/PDF preview in modal; DWG and other types show download prompt (no pop-up).
    setPreviewOpen(true);
  };

  return (
    <>
      <div className={`flex items-center gap-1.5 justify-end ${className}`}>
        <button
          type="button"
          onClick={handleView}
          disabled={busy !== null}
          title="View"
          className="p-1.5 text-gray-400 hover:text-primary rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50"
        >
          {busy === "view" ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
        </button>
        <button
          type="button"
          onClick={handleDownload}
          disabled={busy !== null}
          title="Download"
          className="p-1.5 text-gray-400 hover:text-primary rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50"
        >
          {busy === "download" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Download size={14} />
          )}
        </button>
      </div>

      <FilePreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={title}
        resource={resource}
        lookup={lookup}
        fileType={fileType}
        onDownload={handleDownload}
      />
    </>
  );
}
