import { readPageCache } from "./pageCache";
import { projectsApi } from "./api";
import type { Project } from "@/types";

/** Reuse the projects list cache when another page already loaded it. */
export function cachedProjectsOrFetch(): Promise<Project[]> {
  const cached = readPageCache<Project[]>("projects");
  if (cached) return Promise.resolve(cached);
  return projectsApi.list().then((r) => r.data);
}
