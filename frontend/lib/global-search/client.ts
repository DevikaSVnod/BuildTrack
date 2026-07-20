import axios, { type AxiosInstance } from "axios";
import type { SearchRequest, SearchResponse } from "./types";

export function createSearchClient(options: {
  apiBaseUrl: string;
  getAuthToken?: () => string | null;
  timeoutMs?: number;
}): {
  client: AxiosInstance;
  searchResults: (body: SearchRequest) => Promise<SearchResponse>;
  searchAnswer: (body: SearchRequest) => Promise<SearchResponse>;
  searchCombined: (body: SearchRequest) => Promise<SearchResponse>;
} {
  const client = axios.create({
    baseURL: options.apiBaseUrl.replace(/\/$/, ""),
    headers: { "Content-Type": "application/json" },
    timeout: options.timeoutMs ?? 60000,
  });

  client.interceptors.request.use((config) => {
    const token = options.getAuthToken?.();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  const post = async (path: string, body: SearchRequest) => {
    const { data } = await client.post<SearchResponse>(path, body);
    return data;
  };

  return {
    client,
    searchResults: (body) => post("/search/results", body),
    searchAnswer: (body) => post("/search/answer", body),
    searchCombined: (body) => post("/search/", body),
  };
}
