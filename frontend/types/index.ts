export type UserRole = "Admin" | "Project Manager" | "Site Engineer" | "Contractor";

export interface User {
  id: number;
  full_name: string;
  email: string;
  company_name?: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export type ProjectStatus = "Planning" | "In Progress" | "Completed" | "On Hold";

export interface Project {
  id: number;
  name: string;
  description?: string;
  status: ProjectStatus;
  start_date?: string;
  end_date?: string;
  budget?: number;
  location?: string;
  progress: number;
  project_manager_id?: number;
  project_manager?: User;
  task_count: number;
  team_size: number;
  created_at: string;
}

export type TaskStatus = "To Do" | "In Progress" | "Review" | "Done";
export type TaskPriority = "Low" | "Medium" | "High";

export interface Task {
  id: number;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  project_id?: number;
  project_name?: string;
  assignee_id?: number;
  assignee?: User;
  due_date?: string;
  created_at: string;
}

export interface TeamMember {
  id: number;
  user_id: number;
  project_id?: number;
  project_name?: string;
  role?: string;
  joined_at: string;
  user?: User;
  active_projects_count: number;
  tasks_count: number;
}

export interface Document {
  id: number;
  name: string;
  file_type?: string;
  file_url?: string;
  project_id?: number;
  project_name?: string;
  uploaded_by?: number;
  uploader?: User;
  uploader_name?: string;
  file_size: number;
  created_at: string;
}

export interface SearchResultMetadata {
  // Project / shared
  status?: string;
  project?: string;
  // Task
  priority?: string;
  project_id?: number;
  project_name?: string;
  task_id?: number;
  // Document
  file_type?: string;
  file_size?: number;
  file_size_display?: string;
  doc_id?: number;
  // Team
  role?: string;
  email?: string;
  user_id?: number;
  // Handover
  category?: string;
  signed_by?: string;
  // Drawing
  drawing_id?: number;
  drawing_no?: string;
  discipline?: string;
  revision?: string;
  content_source?: string;
  source?: string;
  blob_chunk?: string;
  // Safety
  incident_type?: string;
  severity?: string;
  reported_by?: string;
  inc_id?: number;
  // Attendance
  name?: string;
  [key: string]: unknown;
}

export interface SearchResultItem {
  id: string;
  title: string;
  snippet: string;
  content_type: "project" | "task" | "document" | "team" | "handover" | "drawing" | "safety" | "attendance" | string;
  url: string;
  metadata?: SearchResultMetadata;
  score?: number;
}

export interface SearchResponse {
  ai_answer: string;
  results: SearchResultItem[];
  suggested_questions: string[];
  search_time_ms: number;
  total_results: number;
  is_question?: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface ApiError {
  detail: string;
}

export interface DashboardStats {
  total_projects: number;
  active_tasks: number;
  team_members: number;
  documents_count: number;
  project_status_breakdown: Record<string, number>;
  task_completion_trend: Array<{ date: string; completed: number; created: number }>;
}
