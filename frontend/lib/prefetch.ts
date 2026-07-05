import { operationalApi, documentsApi, projectsApi } from "./api";
import { writePageCache } from "./pageCache";

const inflight = new Map<string, Promise<unknown>>();

function prefetchOnce<T>(key: string, fetcher: () => Promise<T>): void {
  if (inflight.has(key)) return;
  const cached = typeof window !== "undefined" && sessionStorage.getItem(`bt:page:${key}`);
  if (cached) return;

  const promise = fetcher()
    .then((data) => {
      writePageCache(key, data);
      return data;
    })
    .catch(() => {
      // Prefetch is best-effort — never surface API failures to the UI.
      return undefined;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, promise);
}

const ROUTE_PREFETCH: Record<string, () => void> = {
  "/dashboard": () =>
    prefetchOnce("dashboard", async () => {
      const { projectsApi, tasksApi, teamApi, documentsApi, operationalApi } = await import("./api");
      const [budget, safety, milestones, siteActivity] = await Promise.all([
        operationalApi.budget().then((r) => r.data),
        operationalApi.safetyMetrics().then((r) => r.data),
        operationalApi.milestones().then((r) => r.data),
        operationalApi.siteActivity().then((r) => r.data),
      ]);
      return { budget, safety, milestones, siteActivity };
    }),
  "/projects": () =>
    prefetchOnce("projects", () => import("./api").then((m) => m.projectsApi.list().then((r) => r.data))),
  "/documents": () =>
    prefetchOnce("documents-page", async () => {
      const [docs, projects] = await Promise.all([
        documentsApi.list().then((r) => r.data),
        projectsApi.list().then((r) => r.data),
      ]);
      return { documents: docs, projects };
    }),
  "/team": () => {
    prefetchOnce("team-page", async () => {
      const { teamApi } = await import("./api");
      const { cachedProjectsOrFetch } = await import("./cachedFetch");
      const [m, p] = await Promise.all([teamApi.list(), cachedProjectsOrFetch()]);
      return { members: m.data, projects: p };
    });
    prefetchOnce("attendance", () => operationalApi.attendance().then((r) => r.data));
  },
  "/safety": () =>
    prefetchOnce("safety", async () => {
      const [incidents, metrics] = await Promise.all([
        operationalApi.safetyIncidents().then((r) => r.data),
        operationalApi.safetyMetrics().then((r) => r.data),
      ]);
      writePageCache("safety-metrics", metrics);
      return incidents;
    }),
  "/drawings": () =>
    prefetchOnce("drawings", () => operationalApi.drawings().then((r) => r.data)),
  "/tasks": () =>
    prefetchOnce("tasks", () => import("./api").then((m) => m.tasksApi.list().then((r) => r.data))),
  "/timeline": () =>
    prefetchOnce("timeline", () => operationalApi.timeline().then((r) => r.data)),
};

export function prefetchRoute(href: string): void {
  if (typeof window === "undefined") return;
  const fn = ROUTE_PREFETCH[href];
  if (fn) fn();
}

export const PREFETCH_ROUTES = Object.keys(ROUTE_PREFETCH);
