import apiClient from "./api";
import type { SearchResultItem } from "@/types";

export type FileResource = "documents" | "drawings";

export type FileLookup =
  | { kind: "id"; id: number }
  | { kind: "drawingNo"; drawingNo: string };

function filePath(resource: FileResource, lookup: FileLookup, download = false): string {
  const qs = download ? "?download=true" : "";
  if (resource === "drawings" && lookup.kind === "drawingNo") {
    return `/files/drawings/by-no/${encodeURIComponent(lookup.drawingNo)}${qs}`;
  }
  return `/files/${resource}/${lookup.id}${qs}`;
}

const DRAWING_NO_RE = /^([A-Z]{2}-\d{3}-[A-Z0-9])\s*[–-]/i;

function idFromPageUrl(url: string, param: string): number | undefined {
  if (!url) return undefined;
  const match = url.match(new RegExp(`[?&]${param}=(\\d+)`));
  if (match) return Number(match[1]);
  try {
    const parsed = new URL(url, "http://local");
    const raw = parsed.searchParams.get(param);
    if (raw && /^\d+$/.test(raw)) return Number(raw);
  } catch {
    /* relative paths handled by regex above */
  }
  return undefined;
}

function fileTypeFromResult(result: SearchResultItem): string {
  const meta = result.metadata ?? {};
  const fromMeta = typeof meta.file_type === "string" ? meta.file_type : "";
  if (fromMeta) return fromMeta.toUpperCase();
  const ext = result.title.split(".").pop()?.toUpperCase();
  return ext && ext.length <= 5 ? ext : "PDF";
}

/** Map a search dropdown hit to a downloadable drawing/document file, if applicable. */
export function resolveSearchResultFile(
  result: SearchResultItem
): { resource: FileResource; lookup: FileLookup } | null {
  const meta = result.metadata ?? {};
  const ct = result.content_type;

  if (ct === "drawing") {
    const idFromKey = result.id.match(/^drawing-(\d+)$/);
    const drawingId =
      meta.drawing_id ??
      (idFromKey ? Number(idFromKey[1]) : undefined) ??
      idFromPageUrl(result.url, "drawingId");
    if (drawingId != null && !Number.isNaN(Number(drawingId))) {
      return { resource: "drawings", lookup: { kind: "id", id: Number(drawingId) } };
    }
    const drawingNo =
      (typeof meta.drawing_no === "string" && meta.drawing_no) ||
      result.title.match(DRAWING_NO_RE)?.[1];
    if (drawingNo) {
      return { resource: "drawings", lookup: { kind: "drawingNo", drawingNo } };
    }
    return null;
  }

  if (ct === "document" || ct === "handover") {
    const idFromKey = result.id.match(/^document-(\d+)$/);
    const docId =
      meta.doc_id ??
      (idFromKey ? Number(idFromKey[1]) : undefined) ??
      idFromPageUrl(result.url, "docId");
    if (docId != null && !Number.isNaN(Number(docId))) {
      return { resource: "documents", lookup: { kind: "id", id: Number(docId) } };
    }
  }

  return null;
}

export function isSearchResultFile(result: SearchResultItem): boolean {
  return resolveSearchResultFile(result) !== null;
}

export function canPreviewInline(fileType?: string): boolean {
  const t = (fileType || "PDF").toUpperCase();
  return ["PDF", "PNG", "JPG", "JPEG", "WEBP", "GIF"].includes(t);
}

export async function fetchFileBlob(
  resource: FileResource,
  lookup: FileLookup,
  download = false
): Promise<{ blob: Blob; contentType: string }> {
  const res = await apiClient.get(filePath(resource, lookup, download), {
    responseType: "blob",
  });
  const contentType =
    (res.headers["content-type"] as string | undefined) || "application/octet-stream";
  return { blob: res.data as Blob, contentType };
}

const previewCache = new Map<string, { url: string; at: number }>();
const PREVIEW_TTL_MS = 5 * 60 * 1000;

function previewCacheKey(resource: FileResource, lookup: FileLookup): string {
  if (lookup.kind === "drawingNo") {
    return `${resource}:no:${lookup.drawingNo.toLowerCase()}`;
  }
  return `${resource}:id:${lookup.id}`;
}

export function lookupKey(lookup: FileLookup): string {
  return lookup.kind === "drawingNo"
    ? `no:${lookup.drawingNo}`
    : `id:${lookup.id}`;
}

/** Reuse object URLs so reopening the same preview is instant. */
export async function loadPreviewBlob(
  resource: FileResource,
  lookup: FileLookup
): Promise<string> {
  const key = previewCacheKey(resource, lookup);
  const hit = previewCache.get(key);
  if (hit && Date.now() - hit.at < PREVIEW_TTL_MS) {
    return hit.url;
  }
  if (hit) {
    URL.revokeObjectURL(hit.url);
    previewCache.delete(key);
  }
  const { blob, contentType } = await fetchFileBlob(resource, lookup, false);
  const url = URL.createObjectURL(new Blob([blob], { type: contentType }));
  previewCache.set(key, { url, at: Date.now() });
  return url;
}

export async function openSearchResultFile(result: SearchResultItem): Promise<"tab" | "page"> {
  const fileRef = resolveSearchResultFile(result);
  if (!fileRef) {
    throw new Error("No uploaded file is linked to this search result.");
  }

  const fileType = fileTypeFromResult(result);
  if (canPreviewInline(fileType)) {
    await openFileInNewTab(fileRef.resource, fileRef.lookup);
    return "tab";
  }

  if (fileRef.resource === "documents" && fileRef.lookup.kind === "id") {
    return "page";
  }
  if (fileRef.resource === "drawings") {
    return "page";
  }

  await downloadFile(fileRef.resource, fileRef.lookup, result.title);
  return "tab";
}

export function searchResultFilePageUrl(result: SearchResultItem): string | null {
  const fileRef = resolveSearchResultFile(result);
  if (!fileRef) return null;
  if (fileRef.resource === "documents" && fileRef.lookup.kind === "id") {
    return `/documents?docId=${fileRef.lookup.id}&open=view`;
  }
  if (fileRef.resource === "drawings" && fileRef.lookup.kind === "id") {
    return `/drawings?drawingId=${fileRef.lookup.id}&open=view`;
  }
  if (fileRef.resource === "drawings" && fileRef.lookup.kind === "drawingNo") {
    return `/drawings?drawingNo=${encodeURIComponent(fileRef.lookup.drawingNo)}&open=view`;
  }
  return null;
}

export async function openFileInNewTab(
  resource: FileResource,
  lookup: FileLookup
): Promise<void> {
  const popup = window.open("about:blank", "_blank");
  if (!popup) {
    throw new Error("Pop-up blocked. Use Download instead.");
  }
  try {
    const { blob, contentType } = await fetchFileBlob(resource, lookup, false);
    const url = URL.createObjectURL(new Blob([blob], { type: contentType }));
    popup.location.href = url;
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    popup.close();
    throw err;
  }
}

export async function downloadFile(
  resource: FileResource,
  lookup: FileLookup,
  filename: string
): Promise<void> {
  const { blob, contentType } = await fetchFileBlob(resource, lookup, true);
  const url = URL.createObjectURL(new Blob([blob], { type: contentType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
