"use client";
import Link from "next/link";
import { Building2, CheckSquare, FileText, Users, ExternalLink } from "lucide-react";
import type { SearchResultItem } from "@/types";

interface SearchResultsProps {
  results: SearchResultItem[];
}

const TYPE_CONFIG = {
  project: {
    icon: Building2,
    color: "text-primary",
    bg: "bg-primary/10",
    label: "Project",
  },
  task: {
    icon: CheckSquare,
    color: "text-amber-600",
    bg: "bg-amber-50",
    label: "Task",
  },
  document: {
    icon: FileText,
    color: "text-red-600",
    bg: "bg-red-50",
    label: "Document",
  },
  team: {
    icon: Users,
    color: "text-purple-600",
    bg: "bg-purple-50",
    label: "Team",
  },
};

export default function SearchResults({ results }: SearchResultsProps) {
  if (results.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-400 text-sm">No results found</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {results.map((result) => {
        const config = TYPE_CONFIG[result.content_type] || TYPE_CONFIG.project;
        const Icon = config.icon;
        return (
          <Link
            key={result.id}
            href={result.url}
            className="block bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md hover:border-primary/20 transition-all duration-200 group"
          >
            <div className="flex items-start gap-4">
              <div className={`p-2.5 rounded-xl flex-shrink-0 ${config.bg}`}>
                <Icon size={18} className={config.color} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${config.bg} ${config.color} mb-1 inline-block`}>
                      {config.label}
                    </span>
                    <h4 className="font-semibold text-gray-900 text-sm group-hover:text-primary transition-colors">
                      {result.title}
                    </h4>
                  </div>
                  <ExternalLink size={14} className="text-gray-300 group-hover:text-primary flex-shrink-0 mt-1 transition-colors" />
                </div>
                <p className="text-sm text-gray-500 mt-1 line-clamp-2">{result.snippet}</p>
                {result.score !== undefined && result.score > 0 && (
                  <div className="mt-2 flex items-center gap-1">
                    <div className="h-1 bg-gray-100 rounded-full w-16">
                      <div
                        className="h-1 bg-primary rounded-full"
                        style={{ width: `${Math.min(result.score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400">
                      {(result.score * 100).toFixed(0)}% match
                    </span>
                  </div>
                )}
              </div>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
