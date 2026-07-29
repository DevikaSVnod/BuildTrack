/** Shared types for Global Search widget (product API contract). */
export interface SearchResultItem {
  id: string;
  title: string;
  snippet: string;
  content_type: string;
  url: string;
  metadata?: Record<string, unknown>;
  score?: number;
}

export interface SearchResponse {
  ai_answer: string;
  results: SearchResultItem[];
  suggested_questions: string[];
  search_time_ms: number;
  total_results: number;
  is_question?: boolean;
  sources_searched?: string[];
}

export interface SearchRequest {
  query: string;
  filter_type?: string;
  top_k?: number;
  source_ids?: string[];
}

export type ContentTypeConfig = {
  id: string;
  label: string;
  pluralLabel: string;
  listPage: string;
  color: string;
  bg: string;
};

export type GlobalSearchConfig = {
  apiBaseUrl: string;
  getAuthToken?: () => string | null;
  contentTypes: Record<string, ContentTypeConfig>;
  exampleQueries?: string[];
  recentStorageKey?: string;
  onOpenResult?: (item: SearchResultItem) => void;
};
