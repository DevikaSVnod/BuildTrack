import { readPageCache } from "./pageCache";
import { projectsApi } from "./api";
import type { Project } from "@/types";

/** Reuse the projects list cache when another page already loaded it. */
export function cachedProjectsOrFetch(): Promise<Project[]> {
  const cached = readPageCache<Project[]>("projects");
  if (cached?.length) return Promise.resolve(cached);
  // Dashboard already fetched projects — reuse instead of another Azure Search round-trip.
  const dash = readPageCache<{ projects?: Project[] }>("dashboard");
  if (dash?.projects?.length) return Promise.resolve(dash.projects);
  return projectsApi.list().then((r) => r.data);
}
