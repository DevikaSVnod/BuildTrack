"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import Modal from "@/components/ui/Modal";
import {
  canPreviewInline,
  loadPreviewBlob,
  type FileLookup,
  type FileResource,
} from "@/lib/fileAccess";

interface FilePreviewModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  resource: FileResource;
  lookup: FileLookup;
  fileType?: string;
  onDownload?: () => void;
}

export default function FilePreviewModal({
  open,
  onClose,
  title,
  resource,
  lookup,
  fileType,
  onDownload,
}: FilePreviewModalProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setPreviewUrl(null);
      setError(null);
      return;
    }

    if (!canPreviewInline(fileType)) {
      setPreviewUrl(null);
      setLoading(false);
      setError(null);
      return;
    }

    let revoked: string | null = null;
    setLoading(true);
    setError(null);

    loadPreviewBlob(resource, lookup)
      .then((url) => {
        revoked = url;
        setPreviewUrl(url);
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Could not load file";
        setError(message);
      })
      .finally(() => setLoading(false));

    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [open, resource, lookup, fileType]);

  const previewable = canPreviewInline(fileType);

  return (
    <Modal open={open} onClose={onClose} title={title} size="xl">
      {loading && (
        <div className="flex items-center justify-center gap-2 py-16 text-gray-500">
          <Loader2 size={20} className="animate-spin" />
          Loading preview...
        </div>
      )}

      {!loading && error && (
        <div className="text-center py-12">
          <p className="text-sm text-red-600 mb-4">{error}</p>
          {onDownload && (
            <button
              onClick={onDownload}
              className="text-sm font-medium text-primary hover:underline"
            >
              Try download instead
            </button>
          )}
        </div>
      )}

      {!loading && !error && previewUrl && previewable && fileType?.toUpperCase() === "PDF" && (
        <iframe
          src={previewUrl}
          title={title}
          className="w-full h-[70vh] rounded-lg border border-gray-100 bg-gray-50"
        />
      )}

      {!loading && !error && previewUrl && previewable && fileType?.toUpperCase() !== "PDF" && (
        <img
          src={previewUrl}
          alt={title}
          className="max-h-[70vh] w-full object-contain rounded-lg border border-gray-100 bg-gray-50"
        />
      )}

      {!loading && !error && !previewable && (
        <div className="text-center py-12">
          <p className="text-sm text-gray-600 mb-2">
            Inline preview is not available for {(fileType || "this file type").toUpperCase()} files.
          </p>
          <p className="text-xs text-gray-500 mb-4">
            {fileType?.toUpperCase() === "DWG"
              ? "Download the drawing to open it in AutoCAD or another CAD viewer."
              : "Download the file to open it in the appropriate application."}
          </p>
          {onDownload && (
            <button
              onClick={onDownload}
              className="px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90"
            >
              Download file
            </button>
          )}
        </div>
      )}
    </Modal>
  );
}
