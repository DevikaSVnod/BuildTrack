import axios, { type AxiosRequestConfig, type AxiosResponse } from "axios";
import { getToken, clearAuth } from "./auth";
import type {
  User,
  Project,
  Task,
  TeamMember,
  Document,
  TokenResponse,
  SearchResponse,
} from "@/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const apiClient = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { "Content-Type": "application/json" },
  timeout: 60000,
});
apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    if (status === 401 || status === 403) {
      clearAuth();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<TokenResponse>("/auth/login", { email, password }),
  register: (data: {
    full_name: string;
    email: string;
    password: string;
    company_name?: string;
    role: string;
  }) => apiClient.post<TokenResponse>("/auth/register", data),
  me: () => apiClient.get<User>("/auth/me"),
};

// Projects
export const projectsApi = {
  list: (status?: string) =>
    apiClient.get<Project[]>("/projects/", {
      params: status && status !== "all" ? { status_filter: status } : {},
    }),
  get: (id: number) => apiClient.get<Project>(`/projects/${id}`),
  create: (data: Partial<Project>) => apiClient.post<Project>("/projects/", data),
  update: (id: number, data: Partial<Project>) =>
    apiClient.put<Project>(`/projects/${id}`, data),
  delete: (id: number) => apiClient.delete(`/projects/${id}`),
};

// Tasks
export const tasksApi = {
  list: (params?: { project_id?: number; status_filter?: string }) =>
    apiClient.get<Task[]>("/tasks/", { params }),
  create: (data: Partial<Task>) => apiClient.post<Task>("/tasks/", data),
  update: (id: number, data: Partial<Task>) =>
    apiClient.put<Task>(`/tasks/${id}`, data),
  delete: (id: number) => apiClient.delete(`/tasks/${id}`),
};

// Team
export const teamApi = {
  list: () => apiClient.get<TeamMember[]>("/team/"),
  add: (data: { user_id: number; project_id?: number; role?: string }) =>
    apiClient.post<TeamMember>("/team/", data),
  update: (id: number, data: { role?: string; project_id?: number }) =>
    apiClient.put<TeamMember>(`/team/${id}`, data),
  remove: (id: number) => apiClient.delete(`/team/${id}`),
};

// Documents
export const documentsApi = {
  list: (params?: { project_id?: number; file_type?: string }) =>
    apiClient.get<Document[]>("/documents/", { params }),
  upload: (file: File, projectId?: number) => {
    const formData = new FormData();
    formData.append("file", file);
    if (projectId) formData.append("project_id", String(projectId));
    return apiClient.post<Document>("/documents/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  delete: (id: number) => apiClient.delete(`/documents/${id}`),
};

// Operational / KPI data — served from Azure AI Search (SQL indexer output)
export const operationalApi = {
  handover: () => apiClient.get("/operational/handover"),
  drawings: () => apiClient.get("/operational/drawings"),
  uploadDrawing: (data: {
    file: File;
    previewFile?: File;
    drawingNo: string;
    title: string;
    discipline?: string;
    revision?: string;
    projectId?: number;
    status?: string;
    sheetNotes?: string;
  }) => {
    const formData = new FormData();
    formData.append("file", data.file);
    if (data.previewFile) formData.append("preview_file", data.previewFile);
    formData.append("drawing_no", data.drawingNo);
    formData.append("title", data.title);
    if (data.discipline) formData.append("discipline", data.discipline);
    if (data.revision) formData.append("revision", data.revision);
    if (data.projectId) formData.append("project_id", String(data.projectId));
    if (data.status) formData.append("status", data.status);
    if (data.sheetNotes) formData.append("sheet_notes", data.sheetNotes);
    return apiClient.post("/operational/drawings/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  deleteDrawing: (id: number) => apiClient.delete(`/operational/drawings/${id}`),
  safetyIncidents: () => apiClient.get("/operational/safety/incidents"),
  safetyMetrics: () => apiClient.get("/operational/safety/metrics"),
  attendance: () => apiClient.get("/operational/attendance"),
  timeline: () => apiClient.get("/operational/timeline"),
  budget: () => apiClient.get("/operational/reports/budget"),
  productivity: () => apiClient.get("/operational/reports/productivity"),
  milestones: () => apiClient.get("/operational/dashboard/milestones"),
  siteActivity: () => apiClient.get("/operational/dashboard/site-activity"),
};

// Site Assets & Procurement (buildtrack_assets)
export const assetsApi = {
  overview: () => apiClient.get("/assets/overview"),
};

function looksLikeQuestion(q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return false;
  if (s.endsWith("?")) return true;
  return /^(what|which|who|where|when|how|why|show|list|find|tell|give|are there|is there|do we|does|can you|any)\b/.test(s);
}

// Search
export const searchApi = {
  /** Fast: returns Azure Search results only (no AI). ~300-500ms */
  searchFast: (query: string, filterType?: string, topK?: number) => {
    const k = topK ?? (looksLikeQuestion(query) ? 10 : 8);
    return apiClient.post<SearchResponse>("/search/results", {
      query,
      filter_type: filterType || "all",
      top_k: k,
    });
  },
  /** AI answer: called in background after results are shown. */
  searchAI: (
    query: string,
    filterType?: string,
    topK?: number,
    signal?: AbortSignal,
  ) => {
    const k = topK ?? (looksLikeQuestion(query) ? 10 : 8);
    return apiClient.post<SearchResponse>(
      "/search/answer",
      {
        query,
        filter_type: filterType || "all",
        top_k: k,
      },
      { signal },
    );
  },
  /** Trigger Azure SQL Indexer (syncs SQL view → Azure AI Search) */
  triggerSqlIndexer: () => apiClient.post("/search/index"),
  sqlIndexerStatus: () => apiClient.get("/search/index/status"),
  /** @deprecated use triggerSqlIndexer */
  reindex: () => apiClient.post("/search/index"),
};

// Users (for dropdowns)
export const usersApi = {
  list: () => apiClient.get<User[]>("/auth/users").catch(() => ({ data: [] as User[] })),
};

export default apiClient;
