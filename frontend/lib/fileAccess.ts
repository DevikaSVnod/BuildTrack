import apiClient from "./api";

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

export async function loadPreviewBlob(
  resource: FileResource,
  lookup: FileLookup
): Promise<string> {
  const { blob, contentType } = await fetchFileBlob(resource, lookup, false);
  return URL.createObjectURL(new Blob([blob], { type: contentType }));
}
