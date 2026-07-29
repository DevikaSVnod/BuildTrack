"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import Modal from "@/components/ui/Modal";
import {
  canPreviewInline,
  loadPreviewBlob,
  lookupKey,
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
  // Parents pass inline lookup objects — stabilize so we don't re-download on every render.
  const lookupStable = useMemo(() => lookupKey(lookup), [lookup]);
  const fileTypeKey = (fileType || "").toUpperCase();

  useEffect(() => {
    if (!open) {
      setPreviewUrl(null);
      setError(null);
      setLoading(false);
      return;
    }

    if (!canPreviewInline(fileType)) {
      setPreviewUrl(null);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    loadPreviewBlob(resource, lookup)
      .then((url) => {
        if (!cancelled) setPreviewUrl(url);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "Could not load file";
        setError(message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      // Do not revoke — previewCache reuses the object URL across opens.
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- lookupStable stands in for lookup identity
  }, [open, resource, lookupStable, fileTypeKey]);

  const previewable = canPreviewInline(fileType);

  return (
    <Modal open={open} onClose={onClose} title={title} size="xl">
      {loading && (
        <div className="flex items-center gap-2 justify-center py-16 text-gray-500">
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

      {!loading &&
        !error &&
        previewUrl &&
        previewable &&
        ["PNG", "JPG", "JPEG", "WEBP", "GIF"].includes(fileType?.toUpperCase() || "") && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={previewUrl}
            alt={title}
            className="max-h-[70vh] mx-auto rounded-lg border border-gray-100"
          />
        )}

      {!loading && !error && !previewable && (
        <div className="text-center py-12">
          <p className="text-sm text-gray-500 mb-4">
            Inline preview is not available for {fileType || "this file type"}.
          </p>
          {onDownload && (
            <button
              onClick={onDownload}
              className="text-sm font-medium text-primary hover:underline"
            >
              Download file
            </button>
          )}
        </div>
      )}
    </Modal>
  );
}
