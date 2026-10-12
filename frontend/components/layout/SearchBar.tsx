"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Search, Sparkles, Building2, CheckSquare,
  FileText, Users, X, Clock, ArrowRight, Loader2, ExternalLink,
  LayoutDashboard, ChevronRight, BookOpen, Layers,
  ShieldCheck, ClipboardCheck, TrendingUp, Calendar,
  Package, Truck, Wrench,
} from "lucide-react";
import { searchApi } from "@/lib/api";
import type { SearchResponse, SearchResultItem } from "@/types";
import { cn } from "@/lib/utils";
import { getCurrentUser } from "@/lib/auth";
import {
  isSearchResultFile,
  openSearchResultFile,
  resolveSearchResultFile,
  searchResultFilePageUrl,
} from "@/lib/fileAccess";
import { BUILDTRACK_RECENT_KEY, buildTrackSearchConfig } from "@/lib/global-search";

const RECENT_KEY = BUILDTRACK_RECENT_KEY;
const USS_URL = process.env.NEXT_PUBLIC_USS_URL || "http://localhost:8000";
type SearchEngine = "azure" | "universal";

function stripMarkup(value) {
  return String(value || "").replace(/<\/?em>/gi, "").replace(/<[^>]+>/g, "").trim();
}

function safeAppPath(hit) {
  const raw = String(hit.source_url || hit.source_ref?.url || "");
  const kind = hit.entity_type || "document";
  const fallback =
    kind === "drawing" ? "/drawings"
    : kind === "document" || kind === "handover" ? "/documents"
    : kind === "team" || kind === "attendance" ? "/team"
    : kind === "task" ? "/tasks"
    : kind === "safety" ? "/safety"
    : kind === "timeline" ? "/timeline"
    : kind === "project" ? "/projects"
    : "/dashboard";
  if (!raw || raw.includes("blob.core.windows.net")) return fallback;
  if (raw.startsWith("http://localhost:3000")) return raw.slice("http://localhost:3000".length) || fallback;
  if (raw.startsWith("http://") || raw.startsWith("https://")) return fallback;
  return raw.startsWith("/") ? raw : fallback;
}

function mapUniversalHit(hit) {
  const external = String(hit.source_ref?.external_id || "");
  const drawingId = external.match(/^drawing-(\d+)$/)?.[1];
  const documentId = external.match(/^document-(\d+)$/)?.[1];
  return {
    id: drawingId ? `drawing-${drawingId}` : documentId ? `document-${documentId}` : String(hit.id),
    title: hit.title || hit.id,
    snippet: stripMarkup(hit.snippet || ""),
    content_type: hit.entity_type || "document",
    url: safeAppPath(hit),
    score: hit.score,
    metadata: {
      ...(hit.metadata || {}),
      source: hit.source,
      record_key: external,
      ...(drawingId ? { drawing_id: Number(drawingId) } : {}),
      ...(documentId ? { doc_id: Number(documentId) } : {}),
    },
  };
}

async function searchUniversalIndex(body) {
  const res = await fetch(`${USS_URL}/v1/search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-USS-Tenant-Id": "client_a",
      "X-USS-User-Id": "demo",
      "X-USS-Principals": "user:demo,role:pm",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error("Universal Search is not reachable");
  }
  const data = await res.json();
  return { data, results: (data.results || []).map(mapUniversalHit) };
}

async function searchUniversal(query: string): Promise<SearchResponse> {
  const started = performance.now();
  const main = await searchUniversalIndex({
    query,
    mode: "bm25",
    highlight: true,
    page: 1,
    page_size: 20,
  });
  let ai_answer = "";
  try {
    const answerRes = await fetch(`${USS_URL}/v1/answer`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-USS-Tenant-Id": "client_a",
        "X-USS-User-Id": "demo",
        "X-USS-Principals": "user:demo,role:pm",
      },
      body: JSON.stringify({ query, mode: "bm25", max_passages: 4 }),
    });
    if (answerRes.ok) {
      const answer = await answerRes.json();
      if (answer.answer_status === "generated" && answer.answer) {
        ai_answer = answer.answer;
      }
    }
  } catch {
    // Leave the answer empty when the answer model is off.
  }
  return {
    ai_answer,
    results: main.results,
    suggested_questions: [],
    search_time_ms: main.data.took_ms ?? Math.round(performance.now() - started),
    total_results: Math.max(main.data.total ?? 0, main.results.length),
  };
}

function getRecent(): string[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; }
}
function saveRecent(q: string) {
  if (typeof window === "undefined") return;
  const list = [q, ...getRecent().filter((s) => s !== q)].slice(0, 3);
  localStorage.setItem(RECENT_KEY, JSON.stringify(list));
}

function renderAiAnswer(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-gray-900">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return part;
  });
}

type FilterType = "all" | "project" | "task" | "document" | "team" | "handover" | "drawing" | "safety" | "attendance";

const TYPE_CONFIG: Record<string, {
  icon: typeof Building2;
  color: string;
  bg: string;
  label: string;
  pluralLabel: string;
  listPage: string;
}> = {
  project:    { icon: Building2,      color: "text-blue-600",   bg: "bg-blue-50",    label: "Project",        pluralLabel: "Projects",         listPage: "/projects"   },
  task:       { icon: CheckSquare,    color: "text-amber-600",  bg: "bg-amber-50",   label: "Task",           pluralLabel: "Site Activities",  listPage: "/tasks"      },
  document:   { icon: FileText,       color: "text-red-600",    bg: "bg-red-50",     label: "Document",       pluralLabel: "Documents",        listPage: "/documents"  },
  team:       { icon: Users,          color: "text-purple-600", bg: "bg-purple-50",  label: "Personnel",      pluralLabel: "Workforce",        listPage: "/team"       },
  handover:   { icon: BookOpen,       color: "text-teal-600",   bg: "bg-teal-50",    label: "Handover Doc",   pluralLabel: "Handover Docs",    listPage: "/documents"  },
  drawing:    { icon: Layers,         color: "text-indigo-600", bg: "bg-indigo-50",  label: "Drawing",        pluralLabel: "Drawings & Specs", listPage: "/drawings"   },
  safety:     { icon: ShieldCheck,    color: "text-rose-600",   bg: "bg-rose-50",    label: "Safety Incident",pluralLabel: "Safety & HSE",     listPage: "/safety"     },
  attendance: { icon: ClipboardCheck, color: "text-green-600",  bg: "bg-green-50",   label: "Attendance",     pluralLabel: "Attendance",       listPage: "/team?tab=attendance" },
  report:     { icon: TrendingUp,     color: "text-rose-600",   bg: "bg-rose-50",    label: "Report",         pluralLabel: "Reports & Budget", listPage: "/dashboard"    },
  timeline:   { icon: Calendar,       color: "text-cyan-600",   bg: "bg-cyan-50",    label: "Timeline",       pluralLabel: "Timeline & Phases",listPage: "/timeline"   },
  equipment:  { icon: Wrench,         color: "text-orange-600", bg: "bg-orange-50",  label: "Equipment",      pluralLabel: "Equipment",        listPage: "/assets?tab=equipment"  },
  vendor:     { icon: Truck,          color: "text-sky-600",    bg: "bg-sky-50",     label: "Vendor",         pluralLabel: "Vendors",          listPage: "/assets?tab=vendors"  },
  material:   { icon: Package,        color: "text-lime-700",   bg: "bg-lime-50",    label: "Material",       pluralLabel: "Material Deliveries", listPage: "/assets?tab=materials" },
  event:      { icon: Calendar,       color: "text-violet-600", bg: "bg-violet-50",  label: "Event",          pluralLabel: "Events",           listPage: "/dashboard"  },
  event_agenda: { icon: Calendar,     color: "text-fuchsia-600", bg: "bg-fuchsia-50", label: "Event Agenda", pluralLabel: "Event Agendas",    listPage: "/dashboard"  },
  event_information: { icon: Calendar, color: "text-violet-700", bg: "bg-violet-50", label: "Event Info",   pluralLabel: "Event Information", listPage: "/dashboard"  },
  schema_sql: { icon: Calendar, color: "text-emerald-700", bg: "bg-emerald-50", label: "SQL Result", pluralLabel: "SQL Results", listPage: "/dashboard" },
  space_project: { icon: Building2, color: "text-blue-700", bg: "bg-blue-50", label: "Space Project", pluralLabel: "Space Projects", listPage: "/dashboard" },
  occupational_review: { icon: ShieldCheck, color: "text-rose-600", bg: "bg-rose-50", label: "Occupational Review", pluralLabel: "Occupational Reviews", listPage: "/safety" },
  environmental_review: { icon: ShieldCheck, color: "text-teal-700", bg: "bg-teal-50", label: "Environmental Review", pluralLabel: "Environmental Reviews", listPage: "/safety" },
  incident: { icon: ShieldCheck, color: "text-rose-700", bg: "bg-rose-50", label: "Incident", pluralLabel: "Incidents", listPage: "/safety" },
  employment: { icon: Users, color: "text-purple-600", bg: "bg-purple-50", label: "Employment", pluralLabel: "Employment", listPage: "/team" },
  contract: { icon: FileText, color: "text-indigo-600", bg: "bg-indigo-50", label: "Contract", pluralLabel: "Contracts", listPage: "/documents" },
  dashboard_project: { icon: LayoutDashboard, color: "text-cyan-700", bg: "bg-cyan-50", label: "Dashboard Project", pluralLabel: "Dashboard Projects", listPage: "/dashboard" },
  dms_document: { icon: FileText, color: "text-red-700", bg: "bg-red-50", label: "DMS Document", pluralLabel: "DMS Documents", listPage: "/documents" },
  dms_document_file: { icon: FileText, color: "text-orange-700", bg: "bg-orange-50", label: "DMS File", pluralLabel: "DMS Files", listPage: "/documents" },
  space_attachment: { icon: FileText, color: "text-slate-700", bg: "bg-slate-50", label: "Attachment", pluralLabel: "Attachments", listPage: "/documents" },
  space_user: { icon: Users, color: "text-violet-700", bg: "bg-violet-50", label: "Space User", pluralLabel: "Space Users", listPage: "/team" },
  labour_attendance: { icon: ClipboardCheck, color: "text-green-700", bg: "bg-green-50", label: "Labour Attendance", pluralLabel: "Labour Attendance", listPage: "/team" },
  checkpoint_submission: { icon: ClipboardCheck, color: "text-amber-700", bg: "bg-amber-50", label: "Checkpoint", pluralLabel: "Checkpoints", listPage: "/dashboard" },
  bms_project: { icon: Building2, color: "text-sky-700", bg: "bg-sky-50", label: "BMS Project", pluralLabel: "BMS Projects", listPage: "/projects" },
  tool: { icon: Wrench, color: "text-slate-600", bg: "bg-slate-50", label: "Tool", pluralLabel: "Tools", listPage: "/dashboard" },
};

const NAV_SHORTCUTS = [
  { icon: LayoutDashboard, label: "Dashboard",  href: "/dashboard",  color: "text-gray-600"    },
  { icon: Building2,       label: "Projects",   href: "/projects",   color: "text-blue-600"    },
  { icon: CheckSquare,     label: "Activities", href: "/tasks",      color: "text-amber-600"   },
  { icon: Users,           label: "Workforce",  href: "/team",       color: "text-purple-600"  },
  { icon: FileText,        label: "Documents",  href: "/documents",  color: "text-red-600"     },
  { icon: Layers,          label: "Drawings",   href: "/drawings",   color: "text-indigo-600"  },
  { icon: ShieldCheck,     label: "Safety",     href: "/safety",     color: "text-rose-600"    },
  { icon: Package,         label: "Assets",     href: "/assets",     color: "text-lime-700"    },
];

const EXAMPLES = [
  "Show pending handover documents",
  "What are the next steps for pending handover documents?",
  "Safety violations on Metro Station",
  "Approved structural drawings",
  "Who are the project managers?",
  "High priority tasks on Highway Bridge",
  "What is the budget utilization?",
  "List projects with zero progress",
  "Who is on the workforce for Commercial Tower?",
  "Documents uploaded for Highway Bridge Expansion",
];

const RESULTS_DEBOUNCE_MS = 280;
/** Wait until typing pauses before calling the LLM (avoids partial-query hallucinations). */
const AI_DEBOUNCE_MS = 1200;
const MIN_SEARCH_CHARS = 2;
const MIN_AI_CHARS = 4;

function shouldFetchAIAnswer(q: string): boolean {
  const t = q.trim();
  if (t.length < MIN_AI_CHARS) return false;
  if (looksLikeQuestion(t)) return true;
  // Keyword searches: need a meaningful phrase, not a single partial word
  if (t.includes(" ")) return t.length >= 6;
  return t.length >= 10;
}

function looksLikeQuestion(q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return false;
  if (s.endsWith("?")) return true;
  return /^(what|which|who|where|when|how|why|show|list|find|tell|give|are there|is there|do we|does|can you|any)\b/.test(s);
}

// ── Client-side result cache (session memory) ─────────────────────────────────
// Bump when search sources/index shape changes so stale session hits are dropped.
const RESULT_CACHE_VERSION = "space-v1";
const resultCache = new Map<string, SearchResponse>();
const MAX_CACHE = 50;

function cacheKey(q: string) {
  return `${RESULT_CACHE_VERSION}::${q.trim().toLowerCase()}`;
}

function getCached(q: string) { return resultCache.get(cacheKey(q)) ?? null; }

function setCached(q: string, data: SearchResponse) {
  if (resultCache.size >= MAX_CACHE) {
    resultCache.delete(resultCache.keys().next().value as string);
  }
  resultCache.set(cacheKey(q), data);
}

// ── Component ─────────────────────────────────────────────────────────────────
function isCurrentUserQuery(q: string): boolean {
  const t = q.toLowerCase().trim();
  return /\b(current(ly)?\s+(logged[- ]in|logged in|signed[- ]in)|who am i|logged[- ]in user|current user|my (profile|account|name|role|info)|i am logged|am i logged)\b/.test(t)
    || t === "who am i" || t === "who i am" || t === "current user" || t === "logged in user";
}

/** List/filter queries should show every match, not a 3-item preview cap. */
function isFilterListQuery(q: string): boolean {
  const t = q.toLowerCase().trim();
  return (
    /\b(with|at|having|equals?)\s+\d+\s*%?\s*progress\b/.test(t)
    || /\b(zero|no)\s+progress\b/.test(t)
    || /\bprogress\s*(?:of|at|is|=)\s*\d+\b/.test(t)
    || /\b(all|every|list|show)\s+(projects|tasks|documents|phases|timeline)\b/.test(t)
    || /\b(projects|tasks)\s+(on hold|in progress|completed|planning|open|done)\b/.test(t)
  );
}

export default function SearchBar() {
  const engine: SearchEngine = "azure";
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loadingResults, setLoadingResults] = useState(false);
  const [loadingAI, setLoadingAI] = useState(false);
  const [showMoreInfo, setShowMoreInfo] = useState(false);
  const [sessionAnswer, setSessionAnswer] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<FilterType>("all");
  const [searchError, setSearchError] = useState<string | null>(null);
  const [openingFileId, setOpeningFileId] = useState<string | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const resultsDebounceRef = useRef<ReturnType<typeof setTimeout>>();
  const aiDebounceRef = useRef<ReturnType<typeof setTimeout>>();
  const activeQueryRef = useRef("");
  const aiSeqRef = useRef(0);
  const aiAbortRef = useRef<AbortController | null>(null);

  const clearAIAnswer = useCallback(() => {
    aiAbortRef.current?.abort();
    aiSeqRef.current += 1;
    setLoadingAI(false);
    setResults((prev) =>
      prev ? { ...prev, ai_answer: "", suggested_questions: [] } : prev
    );
  }, []);

  useEffect(() => { setRecent(getRecent()); }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        panelRef.current && !panelRef.current.contains(e.target as Node) &&
        inputRef.current && !inputRef.current.contains(e.target as Node)
      ) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); inputRef.current?.blur(); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // ── Phase 1: fast Azure Search results ────────────────────────────────────
  const fetchAIAnswer = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (!shouldFetchAIAnswer(trimmed)) return;

    const seq = ++aiSeqRef.current;
    aiAbortRef.current?.abort();
    const controller = new AbortController();
    aiAbortRef.current = controller;

    setLoadingAI(true);
    try {
      const res = await searchApi.searchAI(trimmed, undefined, undefined, controller.signal);
      if (seq !== aiSeqRef.current) return;
      if (activeQueryRef.current.trim() !== trimmed) return;

      setResults((prev) => {
        if (!prev || activeQueryRef.current.trim() !== trimmed) return prev;
        const merged: SearchResponse = {
          ...prev,
          ai_answer: res.data.ai_answer || prev.ai_answer || "",
          suggested_questions: res.data.suggested_questions,
          // Prefer /answer results even when empty (AI said "not found").
          // Do not fall back to Phase-1 hits via falsy `.length` checks.
          results: Array.isArray(res.data.results) ? res.data.results : prev.results,
          total_results:
            typeof res.data.total_results === "number"
              ? res.data.total_results
              : prev.total_results,
          search_time_ms: res.data.search_time_ms,
          is_question: res.data.is_question ?? prev.is_question,
        };
        setCached(trimmed, merged);
        return merged;
      });
      setShowMoreInfo(false);
    } catch (err: unknown) {
      const canceled =
        controller.signal.aborted ||
        (typeof err === "object" &&
          err !== null &&
          "code" in err &&
          (err as { code?: string }).code === "ERR_CANCELED");
      if (canceled) return;
      // Keep dropdown useful even if /answer fails — build a short local summary.
      if (seq !== aiSeqRef.current) return;
      setResults((prev) => {
        if (!prev || activeQueryRef.current.trim() !== trimmed) return prev;
        if (prev.ai_answer) return prev;
        const top = (prev.results || []).slice(0, 4);
        const lines = top.map((r) => {
          const db = r.metadata?.database_label ? ` (${r.metadata.database_label})` : "";
          return `• ${r.title}${db}`;
        });
        const fallback =
          lines.length > 0
            ? `Based on your search, here is what I found:\n${lines.join("\n")}`
            : "I found matching records, but the AI answer service is temporarily unavailable.";
        const merged = { ...prev, ai_answer: fallback };
        setCached(trimmed, merged);
        return merged;
      });
    } finally {
      if (seq === aiSeqRef.current) setLoadingAI(false);
    }
  }, []);

  const scheduleAIAnswer = useCallback(
    (q: string, immediate = false) => {
      clearTimeout(aiDebounceRef.current);
      aiAbortRef.current?.abort();

      const trimmed = q.trim();
      if (!shouldFetchAIAnswer(trimmed)) {
        setLoadingAI(false);
        return;
      }

      // Show the AI panel immediately so users know an answer is coming.
      setLoadingAI(true);

      const run = () => {
        if (activeQueryRef.current.trim() !== trimmed) return;
        fetchAIAnswer(trimmed);
      };

      if (immediate || looksLikeQuestion(trimmed)) {
        run();
      } else {
        aiDebounceRef.current = setTimeout(run, AI_DEBOUNCE_MS);
      }
    },
    [fetchAIAnswer],
  );

  const fetchResults = useCallback(
    async (q: string, opts?: { immediateAI?: boolean }) => {
      const trimmed = q.trim();
      if (!trimmed) {
        setResults(null);
        setSessionAnswer(null);
        setSearchError(null);
        return;
      }
      setShowMoreInfo(false);
      setSessionAnswer(null);
      setSearchError(null);
      clearAIAnswer();

      if (isCurrentUserQuery(trimmed)) {
        const u = getCurrentUser();
        if (u) {
          setSessionAnswer(
            `You are logged in as **${u.full_name}** (${u.role ?? "User"})${u.company_name ? ` · ${u.company_name}` : ""}.\nEmail: ${u.email}`
          );
          setResults(null);
          setLoadingResults(false);
          return;
        }
      }

      if (engine === "universal") {
        setLoadingResults(true);
        try {
          const data = await searchUniversal(trimmed);
          if (activeQueryRef.current.trim() !== trimmed) return;
          setResults(data);
          saveRecent(trimmed);
          setRecent(getRecent());
        } catch {
          if (activeQueryRef.current.trim() === trimmed) {
            setResults(null);
            setSearchError("Universal Search failed. Start it on port 8000, or switch back to Azure.");
          }
        } finally {
          setLoadingResults(false);
        }
        return;
      }

      const cached = getCached(trimmed);
      if (cached) {
        if (opts?.immediateAI && cached.ai_answer) {
          setResults(cached);
          setLoadingResults(false);
          return;
        }
        setResults({ ...cached, ai_answer: "", suggested_questions: [] });
        setLoadingResults(false);
        scheduleAIAnswer(trimmed, opts?.immediateAI);
        return;
      }

      setLoadingResults(true);
      try {
        const res = await searchApi.searchFast(trimmed);
        if (activeQueryRef.current.trim() !== trimmed) return;
        const data = res.data;
        setResults(data);
        setCached(trimmed, data);
        saveRecent(trimmed);
        setRecent(getRecent());
        scheduleAIAnswer(trimmed, opts?.immediateAI);
      } catch {
        if (activeQueryRef.current.trim() === trimmed) {
          setResults(null);
          setSearchError("Search failed. Check your connection or sign in again.");
        }
      } finally {
        setLoadingResults(false);
      }
    },
    [clearAIAnswer, engine, scheduleAIAnswer],
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    activeQueryRef.current = val;
    setQuery(val);
    setOpen(true);
    setActiveFilter("all");
    clearTimeout(resultsDebounceRef.current);
    clearTimeout(aiDebounceRef.current);
    clearAIAnswer();

    if (val.trim().length >= MIN_SEARCH_CHARS) {
      resultsDebounceRef.current = setTimeout(
        () => fetchResults(val),
        RESULTS_DEBOUNCE_MS,
      );
    } else {
      setResults(null);
      setLoadingResults(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    clearTimeout(resultsDebounceRef.current);
    clearTimeout(aiDebounceRef.current);
    activeQueryRef.current = query;
    setOpen(true);
    setActiveFilter("all");
    if (query.trim()) {
      fetchResults(query, { immediateAI: true });
    }
  };

  const navigate = (url: string) => {
    setOpen(false);
    setQuery("");
    router.push(url);
  };

  const handleResultClick = async (result: SearchResultItem) => {
    const fileRef = resolveSearchResultFile(result);
    if (fileRef) {
      if (openingFileId) return;
      setOpeningFileId(result.id);
      try {
        const mode = await openSearchResultFile(result);
        if (mode === "page") {
          const pageUrl = searchResultFilePageUrl(result);
          if (pageUrl) {
            setOpen(false);
            setQuery("");
            router.push(pageUrl);
          }
        }
        saveRecent(query.trim());
      } catch (err: unknown) {
        const pageUrl = searchResultFilePageUrl(result);
        if (pageUrl) {
          setOpen(false);
          setQuery("");
          router.push(pageUrl);
          return;
        }
        const message = err instanceof Error ? err.message : "Could not open file";
        window.alert(message);
      } finally {
        setOpeningFileId(null);
      }
      return;
    }

    if (result.url?.startsWith("http")) {
      const page = result.content_type === "drawing" ? "/drawings" : "/documents";
      setOpen(false);
      setQuery("");
      router.push(page);
      return;
    }

    setOpen(false);
    setQuery("");
    router.push(result.url);
  };

  const handleExampleClick = (q: string) => {
    activeQueryRef.current = q;
    setQuery(q);
    setOpen(true);
    fetchResults(q, { immediateAI: true });
  };

  const clearQuery = () => {
    activeQueryRef.current = "";
    clearTimeout(resultsDebounceRef.current);
    clearTimeout(aiDebounceRef.current);
    clearAIAnswer();
    setQuery("");
    setResults(null);
    setSearchError(null);
    setLoadingResults(false);
    setActiveFilter("all");
    inputRef.current?.focus();
  };

  // Detect the most relevant content type from the query text
  function isDrawingContentQuery(q: string): boolean {
    const t = q.toLowerCase();
    if (/\b(st|ar|me|ci|el)-\d{3}-[a-z]\b/i.test(q)) {
      if (/\b(pile|piling|diameter|dimension|layout|spacing|foundation|what|which|how|on drawing)\b/.test(t)) return true;
      if (t.trim().endsWith("?")) return true;
    }
    return /\bon\s+(drawing|sheet)\b/.test(t);
  }

  function isDocumentContentQuery(q: string): boolean {
    if (isDrawingContentQuery(q)) return true;
    const t = q.toLowerCase();
    if (/\b(file size|file type|how big|how large|uploaded by|uploaded on)\b/.test(t)) return false;
    if (/\bproject\s+report\b/.test(t)) return true;
    if (/\b(in|from|inside|within)\s+(the\s+)?[\w\s-]+\s+(report|document|pdf|file|docx)\b/.test(t)) return true;
    const asksContent = /\b(mention|mentioned|say|state|describe|detail|content|conclusion|recommendation|measure|section|what|which|how|summarize|explain|find)\b/.test(t);
    const namesFile = /\b(report|document|pdf|docx|xlsx|file|manual|spec|specification)\b/.test(t);
    return namesFile && (asksContent || t.trim().endsWith("?"));
  }

  function getPrimaryType(q: string, resultList?: SearchResultItem[]): string | null {
    const t = q.toLowerCase();

    // Content-inside-file questions → Documents or Drawings first
    if (isDrawingContentQuery(q)) return "drawing";
    if (isDocumentContentQuery(q)) return "document";

    const blobDrawingHit = resultList?.some(
      (r) =>
        r.content_type === "drawing" &&
        (r.metadata?.content_source === "blob_rag" || r.metadata?.source === "blob_rag")
    );
    if (blobDrawingHit && (t.includes("?") || /\b(what|which|how|pile|diameter|drawing)\b/.test(t))) {
      return "drawing";
    }

    const blobDocHit = resultList?.some(
      (r) =>
        r.content_type === "document" &&
        (r.metadata?.content_source === "blob_rag" || r.metadata?.source === "blob_rag")
    );
    if (blobDocHit && (t.includes("?") || /\b(what|which|how|mention|report|document)\b/.test(t))) {
      return "document";
    }

    if (/\b(agenda|agendas|event agenda|meeting agenda)\b/.test(t)) return "event_agenda";
    if (/\b(event|events|meeting|meetings)\b/.test(t)) return "event";
    if (/\b(team|member|members|workforce|personnel|staff|who is|who are|manager|engineer|contractor)\b/.test(t)) return "team";
    if (/\b(task|tasks|activit|activity|work item|job)\b/.test(t)) return "task";
    if (/\b(timeline|phase|phases|milestone|milestones|schedule|gantt|steel erection|foundation|platform upgrade|deck|utility relocation|digital signage|final testing|design.*permit)\b/.test(t)) return "timeline";
    if (/\b(document|documents|doc|file|pdf|xlsx|docx)\b/.test(t)) return "document";
    if (/\b(handover|handover doc|handover document)\b/.test(t)) return "handover";
    if (/\b(drawing|drawings|spec|specs|blueprint)\b/.test(t)) return "drawing";
    if (/\b(safety|incident|violation|hse|hazard|near miss|ppe|inspection)\b/.test(t)) return "safety";
    if (/\b(attendance|present|absent|check.?in|check.?out|hours worked)\b/.test(t)) return "attendance";
    if (/\b(budget|utilisation|utilization|spent|expenditure|cost|financial|₹|crore|productivity|completion rate|reports?)\b/.test(t)) return "report";
    if (/\b(project|projects)\b/.test(t) && !/\breport\b/.test(t)) {
      // Schema-SQL Space Project rows use content_type schema_sql / space_project
      if (resultList?.some((r) => r.content_type === "schema_sql")) return "schema_sql";
      if (resultList?.some((r) => r.content_type === "space_project")) return "space_project";
      return "project";
    }
    return null;
  }

  // Group results by type, optionally filtered
  const allGrouped = results
    ? Object.entries(
        results.results.reduce<Record<string, SearchResultItem[]>>((acc, r) => {
          acc[r.content_type] = [...(acc[r.content_type] || []), r];
          return acc;
        }, {})
      ).map(([type, items]) => {
        if (type !== "document") return [type, items] as const;
        const sorted = [...items].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
        return [type, sorted] as const;
      })
    : [];

  // Always detect primary type from query and reorder groups accordingly
  const detectedPrimaryType = getPrimaryType(query, results?.results);

  const sortedGrouped = (() => {
    if (!detectedPrimaryType) return allGrouped;
    const idx = allGrouped.findIndex(([type]) => type === detectedPrimaryType);
    if (idx <= 0) return allGrouped;
    const reordered = [...allGrouped];
    const [pulled] = reordered.splice(idx, 1);
    reordered.unshift(pulled);
    return reordered;
  })();

  // Keep Space ProjectId cross-DB hops visible (HSE / Incident / LMS / …)
  const hasSpaceLinkedHits = Boolean(
    results?.results.some(
      (r) =>
        r.metadata?.related_via === "space_project_id" ||
        r.metadata?.related_via === "space_attachment_id" ||
        r.metadata?.related_via === "space_user_id" ||
        r.metadata?.retrieval === "cross_db_space"
    )
  );

  // Show "More Info" collapse when a primary type is detected (question OR keyword phrase)
  const shouldCollapse =
    !!detectedPrimaryType && sortedGrouped.length > 1 && !hasSpaceLinkedHits;

  const grouped = activeFilter === "all"
    ? sortedGrouped
    : sortedGrouped.filter(([type]) => type === activeFilter);

  const totalResults = results?.results.length ?? 0;
  const filterCounts = results?.results.reduce<Record<string, number>>((acc, r) => {
    acc[r.content_type] = (acc[r.content_type] || 0) + 1;
    return acc;
  }, {}) ?? {};

  const isLoading = loadingResults;
  const showFullPageLoader = isLoading && !results && !sessionAnswer;

  return (
    <div className="relative flex-1 max-w-2xl min-w-0">
      {/* Search input */}
      <form onSubmit={handleSubmit}>
        <div className="relative">
          {isLoading ? (
            <Loader2 size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-primary animate-spin" />
          ) : (
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          )}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleChange}
            onFocus={() => setOpen(true)}
            placeholder="Search projects, tasks, documents, team..."
            className={cn(
              "w-full pl-9 pr-8 py-2.5 text-sm bg-gray-50 border rounded-xl transition-all duration-200",
              "focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary focus:bg-white focus:shadow-md",
              open ? "border-primary/40 bg-white shadow-sm" : "border-gray-200"
            )}
          />
          {query && (
            <button
              type="button"
              onClick={clearQuery}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 text-gray-300 hover:text-gray-500 rounded"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </form>

      {/* Dropdown */}
      {open && (
        <div
          ref={panelRef}
          className="absolute top-full left-0 right-0 mt-2 bg-white rounded-2xl shadow-2xl border border-gray-100 z-[100] overflow-hidden"
          style={{ maxHeight: "82vh", overflowY: "auto" }}
        >
          {/* ── Loading (only when no results to show yet) ── */}
          {showFullPageLoader && (
            <div className="p-6 text-center">
              <Loader2 size={22} className="text-primary animate-spin mx-auto mb-2" />
              <p className="text-sm text-gray-400">Searching...</p>
            </div>
          )}

          {/* ── Search error ── */}
          {searchError && !showFullPageLoader && (
            <div className="p-6 text-center">
              <p className="text-sm text-red-600 font-medium">{searchError}</p>
              <p className="text-xs text-gray-400 mt-1">Press Enter to try again</p>
            </div>
          )}

          {/* ── Query entered but waiting (e.g. debounce cleared on Enter) ── */}
          {query.trim() && !showFullPageLoader && !searchError && !results && !sessionAnswer && !isLoading && (
            <div className="p-6 text-center">
              <Loader2 size={22} className="text-primary animate-spin mx-auto mb-2" />
              <p className="text-sm text-gray-400">Searching for &ldquo;{query.trim()}&rdquo;…</p>
            </div>
          )}

          {/* ── Session answer (current user / login info) ── */}
          {sessionAnswer && !showFullPageLoader && (
            <div className="p-4">
              <div className="bg-gradient-to-r from-primary/5 to-secondary/5 border border-primary/15 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <div className="p-1.5 bg-primary rounded-lg flex-shrink-0">
                    <Users size={14} className="text-white" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-primary mb-1">Logged-in User</p>
                    {sessionAnswer.split("\n").map((line, i) => (
                      <p key={i} className="text-sm text-gray-700 leading-relaxed">
                        {line.replace(/\*\*(.*?)\*\*/g, "$1")}
                      </p>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Results ── */}
          {results && (
            <div>
              {isLoading && (
                <div className="px-4 pt-3 pb-1 flex items-center gap-2 text-xs text-gray-400">
                  <Loader2 size={12} className="animate-spin text-primary" />
                  Updating results…
                </div>
              )}
              {/* Filter tabs — dynamic based on what's in results */}
              {totalResults > 0 && (
                <div className="flex items-center gap-1 px-4 pt-3 pb-0 overflow-x-auto">
                  {/* "All" tab */}
                  <button
                    onClick={() => setActiveFilter("all")}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all",
                      activeFilter === "all"
                        ? "bg-primary text-white shadow-sm"
                        : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                    )}
                  >
                    All results
                    <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full", activeFilter === "all" ? "bg-white/20 text-white" : "bg-gray-200 text-gray-600")}>
                      {totalResults}
                    </span>
                  </button>
                  {/* One tab per content type present in results */}
                  {Object.entries(filterCounts).map(([type, count]) => {
                    const cfg = TYPE_CONFIG[type];
                    if (!cfg || count === 0) return null;
                    const Icon = cfg.icon;
                    return (
                      <button
                        key={type}
                        onClick={() => setActiveFilter(type as FilterType)}
                        className={cn(
                          "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all",
                          activeFilter === type
                            ? "bg-primary text-white shadow-sm"
                            : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                        )}
                      >
                        <Icon size={11} />
                        {cfg.pluralLabel}
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full", activeFilter === type ? "bg-white/20 text-white" : "bg-gray-200 text-gray-600")}>
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* AI answer — shown directly above results */}
              {activeFilter === "all" && (loadingAI || results.ai_answer) && (
                <div className="px-4 pt-2 pb-1">
                  <div className="bg-gradient-to-r from-primary/5 to-secondary/5 border border-primary/15 rounded-xl p-4">
                    {loadingAI && !results.ai_answer ? (
                      <div className="flex items-start gap-3">
                        <div className="p-1.5 bg-primary/20 rounded-lg flex-shrink-0 animate-pulse">
                          <Sparkles size={14} className="text-primary/40" />
                        </div>
                        <div className="flex-1 space-y-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-primary/60">
                              {results?.is_question ? "Finding answer…" : "Generating AI summary…"}
                            </span>
                            <Loader2 size={11} className="text-primary animate-spin" />
                          </div>
                          <div className="h-3 bg-gray-200 rounded animate-pulse w-4/5" />
                          <div className="h-3 bg-gray-200 rounded animate-pulse w-3/5" />
                        </div>
                      </div>
                    ) : results.ai_answer ? (
                      <div className="flex items-start gap-3">
                        <div className="p-1.5 bg-primary rounded-lg flex-shrink-0">
                          <Sparkles size={14} className="text-white" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-semibold text-primary">AI Answer</span>
                            <span className="text-xs text-gray-400">{results.search_time_ms}ms</span>
                          </div>
                          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
                            {renderAiAnswer(results.ai_answer)}
                          </p>
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              )}

              {/* Grouped result cards */}
              {grouped.length > 0 && (
                <div className="px-4 pb-2 pt-2">
                  {grouped.map(([type, items], groupIndex) => {
                    if (shouldCollapse && activeFilter === "all" && !showMoreInfo && groupIndex > 0) return null;

                    const cfg = TYPE_CONFIG[type] ?? TYPE_CONFIG.project;
                    const Icon = cfg.icon;
                    const isWorkforceQuery = /\b(total\s+)?(workforce|personnel)\b/i.test(query);
                    const showAllMatches = isFilterListQuery(query) || (isWorkforceQuery && type === "team");
                    const previewLimit =
                      activeFilter === "all"
                        ? showAllMatches
                          ? items.length
                          : type === "team" && isWorkforceQuery
                            ? 8
                            : 3
                        : items.length;
                    const showItems = activeFilter === "all" ? items.slice(0, previewLimit) : items;
                    const hasMore = activeFilter === "all" && items.length > previewLimit;
                    return (
                      <div key={type} className="mb-3">
                        <div className="flex items-center justify-between mb-1.5 px-1">
                          <div className="flex items-center gap-1.5">
                            <Icon size={12} className={cfg.color} />
                            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                              {cfg.pluralLabel}
                            </span>
                          </div>
                          <button
                            onClick={() => navigate(cfg.listPage)}
                            className={cn("flex items-center gap-1 text-xs font-medium hover:underline transition-colors", cfg.color)}
                          >
                            View all {cfg.pluralLabel} <ChevronRight size={11} />
                          </button>
                        </div>
                        <div className="space-y-0.5">
                          {showItems.map((r) => {
                            const isFile = isSearchResultFile(r);
                            const isOpening = openingFileId === r.id;
                            return (
                            <button
                              key={r.id}
                              type="button"
                              onClick={() => handleResultClick(r)}
                              disabled={isOpening}
                              title={isFile ? "Open file in new tab" : undefined}
                              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-gray-50 transition-colors group text-left disabled:opacity-70"
                            >
                              <div className={cn("p-1.5 rounded-lg flex-shrink-0", cfg.bg)}>
                                <Icon size={13} className={cfg.color} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 min-w-0">
                                  <p className="text-sm font-medium text-gray-900 truncate group-hover:text-primary transition-colors">
                                    {r.title}
                                  </p>
                                  {r.metadata?.database_label ? (
                                    <span className="flex-shrink-0 text-[10px] font-medium uppercase tracking-wide text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                                      {String(r.metadata.database_label)}
                                    </span>
                                  ) : null}
                                  {r.metadata?.relationship === "same_project" ||
                                  r.metadata?.relationship === "same_attachment" ||
                                  r.metadata?.relationship === "same_user" ||
                                  r.metadata?.related_via === "space_project_id" ||
                                  r.metadata?.related_via === "space_attachment_id" ||
                                  r.metadata?.related_via === "space_user_id" ? (
                                    <span
                                      className="flex-shrink-0 text-[10px] font-medium uppercase tracking-wide text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded"
                                      title={
                                        r.metadata?.related_key
                                          ? `Linked across databases via project: ${r.metadata.related_key}`
                                          : "Linked across databases"
                                      }
                                    >
                                      Linked
                                    </span>
                                  ) : null}
                                </div>
                                <p className="text-xs text-gray-400 truncate mt-0.5">
                                  {(r.content_type === "document" || r.content_type === "drawing") &&
                                  (r.metadata?.content_source === "blob_rag" || r.metadata?.source === "blob_rag")
                                    ? r.snippet
                                    : r.content_type === "document" && r.metadata
                                    ? `${r.metadata.file_type ?? ""} · ${r.metadata.file_size_display ?? (r.metadata.file_size ? `${r.metadata.file_size} bytes` : "")} · ${r.metadata.uploader ?? ""}`
                                    : r.content_type === "handover" && r.metadata
                                    ? `${r.metadata.category ?? ""} · ${r.metadata.status ?? ""} · ${r.metadata.project ?? ""}`
                                    : r.content_type === "drawing" && r.metadata
                                    ? `${r.metadata.discipline ?? ""} · ${r.metadata.status ?? ""} · ${r.metadata.project ?? ""}`
                                    : r.content_type === "safety" && r.metadata
                                    ? `${r.metadata.incident_type ?? ""} · ${r.metadata.severity ?? ""} severity · ${r.metadata.status ?? ""}`
                                    : r.content_type === "attendance" && r.metadata
                                    ? `${r.metadata.role ?? ""} · ${r.metadata.status ?? ""} · ${r.metadata.project ?? ""}`
                                    : r.content_type === "equipment" && r.metadata
                                    ? `${r.metadata.category ?? ""} · ${r.metadata.status ?? ""} · ${r.metadata.project ?? ""}`
                                    : r.content_type === "vendor" && r.metadata
                                    ? `${r.metadata.category ?? ""} · ${r.metadata.status ?? ""} · rating ${r.metadata.rating ?? ""}`
                                    : r.content_type === "material" && r.metadata
                                    ? `${r.metadata.quantity ?? ""} ${r.metadata.unit ?? ""} · ${r.metadata.status ?? ""} · ${r.metadata.project ?? ""}`
                                    : r.snippet}
                                </p>
                              </div>
                              {isOpening ? (
                                <Loader2 size={13} className="text-primary flex-shrink-0 animate-spin" />
                              ) : isFile ? (
                                <ExternalLink size={13} className="text-gray-300 group-hover:text-primary flex-shrink-0 transition-colors" />
                              ) : (
                                <ArrowRight size={13} className="text-gray-200 group-hover:text-primary flex-shrink-0 transition-colors" />
                              )}
                            </button>
                            );
                          })}
                        </div>
                        {hasMore && (
                          <button
                            onClick={() => setActiveFilter(type as FilterType)}
                            className={cn("w-full text-center text-xs mt-1 py-1.5 rounded-xl hover:bg-gray-50 transition-colors font-medium", cfg.color)}
                          >
                            +{items.length - 3} more — show all
                          </button>
                        )}
                      </div>
                    );
                  })}

                  {/* Bottom — More Info / Show Less only */}
                  {shouldCollapse && activeFilter === "all" && (
                    <button
                      onClick={() => setShowMoreInfo((v) => !v)}
                      className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-primary border border-dashed border-gray-200 hover:border-primary/30 rounded-xl px-3 py-1.5 mt-1 transition-colors"
                    >
                      <ChevronRight size={12} className={showMoreInfo ? "rotate-90 transition-transform" : "transition-transform"} />
                      {showMoreInfo
                        ? "Show Less"
                        : `More Info (${grouped.slice(1).reduce((a, [, it]) => a + it.length, 0)} results in ${grouped.length - 1} other ${grouped.length - 1 === 1 ? "category" : "categories"})`
                      }
                    </button>
                  )}
                </div>
              )}

              {/* No results */}
              {grouped.length === 0 && (
                <div className="px-4 py-6 text-center">
                  <Search size={28} className="text-gray-200 mx-auto mb-2" />
                  <p className="text-sm text-gray-500 font-medium">No results for &ldquo;{query}&rdquo;</p>
                  <p className="text-xs text-gray-400 mt-1">Try a different keyword</p>
                </div>
              )}

              {/* Suggested follow-up questions */}
              {results.suggested_questions?.length > 0 && activeFilter === "all" && (
                <div className="border-t border-gray-50 px-4 py-3">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                    Suggested follow-ups
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {results.suggested_questions.slice(0, 3).map((q, i) => (
                      <button
                        key={i}
                        onClick={() => handleExampleClick(q)}
                        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-primary px-3 py-1.5 rounded-full bg-gray-50 hover:bg-primary/5 border border-gray-100 hover:border-primary/20 transition-all"
                      >
                        <Sparkles size={11} className="text-secondary flex-shrink-0" />
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Empty state (no query) ── */}
          {open && !isLoading && !results && !query.trim() && (
            <div className="p-4">
              {/* Quick nav grid */}
              <div className="mb-4">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">Browse</p>
                <div className="grid grid-cols-4 gap-1">
                  {NAV_SHORTCUTS.map(({ icon: Icon, label, href, color }) => (
                    <button
                      key={href}
                      onClick={() => navigate(href)}
                      className="flex flex-col items-center gap-1.5 px-2 py-3 rounded-xl hover:bg-gray-50 transition-colors group"
                    >
                      <div className="p-2 bg-gray-50 rounded-xl group-hover:bg-white group-hover:shadow-sm transition-all">
                        <Icon size={16} className={color} />
                      </div>
                      <span className="text-[11px] text-gray-500 group-hover:text-gray-800 font-medium">{label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Recent searches */}
              {recent.length > 0 && (
                <div className="mb-4">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">Recent</p>
                  <div className="space-y-0.5">
                    {recent.slice(0, 3).map((s, i) => (
                      <button
                        key={i}
                        onClick={() => handleExampleClick(s)}
                        className="w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-xl hover:bg-gray-50 transition-colors group"
                      >
                        <Clock size={13} className="text-gray-300 flex-shrink-0" />
                        <span className="text-sm text-gray-600 group-hover:text-primary transition-colors truncate flex-1">{s}</span>
                        <ArrowRight size={12} className="text-gray-200 group-hover:text-primary opacity-0 group-hover:opacity-100 transition-all" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Try asking */}
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">Try asking...</p>
                <div className="space-y-0.5">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => handleExampleClick(ex)}
                      className="w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-xl hover:bg-primary/5 transition-colors group"
                    >
                      <Sparkles size={13} className="text-secondary flex-shrink-0" />
                      <span className="text-sm text-gray-500 group-hover:text-primary transition-colors">{ex}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
