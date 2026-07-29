/**
 * BuildTrack host configuration for the Global Search widget.
 * Other products copy this file and swap content types / routes.
 */
import type { GlobalSearchConfig } from "./types";
import { getToken } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const buildTrackSearchConfig: GlobalSearchConfig = {
  apiBaseUrl: `${API_URL}/api`,
  getAuthToken: getToken,
  recentStorageKey: "buildtrack_recent_searches",
  contentTypes: {
    project: {
      id: "project",
      label: "Project",
      pluralLabel: "Projects",
      listPage: "/projects",
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    task: {
      id: "task",
      label: "Task",
      pluralLabel: "Site Activities",
      listPage: "/tasks",
      color: "text-amber-600",
      bg: "bg-amber-50",
    },
    document: {
      id: "document",
      label: "Document",
      pluralLabel: "Documents",
      listPage: "/documents",
      color: "text-red-600",
      bg: "bg-red-50",
    },
    team: {
      id: "team",
      label: "Personnel",
      pluralLabel: "Workforce",
      listPage: "/team",
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
    handover: {
      id: "handover",
      label: "Handover Doc",
      pluralLabel: "Handover Docs",
      listPage: "/documents",
      color: "text-teal-600",
      bg: "bg-teal-50",
    },
    drawing: {
      id: "drawing",
      label: "Drawing",
      pluralLabel: "Drawings & Specs",
      listPage: "/drawings",
      color: "text-indigo-600",
      bg: "bg-indigo-50",
    },
    safety: {
      id: "safety",
      label: "Safety Incident",
      pluralLabel: "Safety & HSE",
      listPage: "/safety",
      color: "text-rose-600",
      bg: "bg-rose-50",
    },
    attendance: {
      id: "attendance",
      label: "Attendance",
      pluralLabel: "Attendance",
      listPage: "/team?tab=attendance",
      color: "text-green-600",
      bg: "bg-green-50",
    },
    report: {
      id: "report",
      label: "Report",
      pluralLabel: "Reports & Budget",
      listPage: "/dashboard",
      color: "text-rose-600",
      bg: "bg-rose-50",
    },
    timeline: {
      id: "timeline",
      label: "Timeline",
      pluralLabel: "Timeline & Phases",
      listPage: "/timeline",
      color: "text-cyan-600",
      bg: "bg-cyan-50",
    },
    equipment: {
      id: "equipment",
      label: "Equipment",
      pluralLabel: "Equipment",
      listPage: "/assets?tab=equipment",
      color: "text-orange-600",
      bg: "bg-orange-50",
    },
    vendor: {
      id: "vendor",
      label: "Vendor",
      pluralLabel: "Vendors",
      listPage: "/assets?tab=vendors",
      color: "text-sky-600",
      bg: "bg-sky-50",
    },
    material: {
      id: "material",
      label: "Material",
      pluralLabel: "Material Deliveries",
      listPage: "/assets?tab=materials",
      color: "text-lime-700",
      bg: "bg-lime-50",
    },
  },
  exampleQueries: [
    "Show pending handover documents",
    "How many chairs in CI-003-C?",
    "What buildings are on site plan AM-789-C?",
    "Bridge inspection findings",
  ],
};

export const BUILDTRACK_RECENT_KEY = buildTrackSearchConfig.recentStorageKey!;
