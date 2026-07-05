"use client";
import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Plus, Building2, Sparkles } from "lucide-react";
import Button from "@/components/ui/Button";
import ProjectCard from "@/components/projects/ProjectCard";
import { projectsApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";
import type { Project } from "@/types";

const Modal = dynamic(() => import("@/components/ui/Modal"), { ssr: false });
const ProjectForm = dynamic(() => import("@/components/projects/ProjectForm"), { ssr: false });

const FILTERS = ["all", "Planning", "In Progress", "Completed", "On Hold"] as const;

export default function ProjectsPage() {
  const [filter, setFilter] = useState<string>("all");
  const cacheKey = filter === "all" ? "projects" : `projects-${filter}`;
  const { data: projects, loading, reload } = usePageData<Project[]>(
    cacheKey,
    () => projectsApi.list(filter === "all" ? undefined : filter).then((r) => r.data),
    [filter],
  );
  const list = projects ?? [];
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState("");
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const searchParams = useSearchParams();
  const highlightRef = useRef<HTMLDivElement>(null);

  // Handle ?highlightId= from search navigation
  useEffect(() => {
    const id = searchParams.get("highlightId");
    if (id) {
      setHighlightId(Number(id));
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 600);
      const timer = setTimeout(() => setHighlightId(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  const handleCreate = async (data: Partial<Project>) => {
    await projectsApi.create(data);
    setShowModal(false);
    reload();
  };

  const showSkeleton = loading && list.length === 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Projects</h1>
          <p className="text-gray-500 text-sm mt-1">
            {showSkeleton ? "Loading projects…" : `${list.length} projects found`}
          </p>
        </div>
        <Button onClick={() => setShowModal(true)} className="gap-2">
          <Plus size={16} />
          New Project
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filter === f
                ? "bg-primary text-white"
                : "bg-white text-gray-600 border border-gray-200 hover:border-primary hover:text-primary"
            }`}
          >
            {f === "all" ? "All Projects" : f}
          </button>
        ))}
      </div>

      {/* Grid */}
      {showSkeleton ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border h-52 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-12 text-red-500">{error}</div>
      ) : list.length === 0 ? (
        <div className="text-center py-20">
          <Building2 size={48} className="text-gray-200 mx-auto mb-4" />
          <h3 className="font-semibold text-gray-500 mb-2">No projects found</h3>
          <p className="text-gray-400 text-sm mb-6">Create your first project to get started</p>
          <Button onClick={() => setShowModal(true)}>
            <Plus size={16} /> Create Project
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {list.map((p) => (
            <div
              key={p.id}
              ref={highlightId === p.id ? highlightRef : null}
              className={`rounded-xl transition-all duration-700 ${
                highlightId === p.id
                  ? "ring-2 ring-primary ring-offset-2 shadow-lg scale-[1.01]"
                  : ""
              }`}
            >
              {highlightId === p.id && (
                <div className="flex items-center gap-1.5 text-xs font-semibold text-primary bg-primary/10 rounded-t-xl px-3 py-1.5 border border-primary/20 border-b-0">
                  <Sparkles size={11} />
                  Search result
                </div>
              )}
              <ProjectCard project={p} />
            </div>
          ))}
        </div>
      )}

      <Modal open={showModal} onClose={() => setShowModal(false)} title="Create New Project" size="lg">
        <ProjectForm onSubmit={handleCreate} onCancel={() => setShowModal(false)} />
      </Modal>
    </div>
  );
}
