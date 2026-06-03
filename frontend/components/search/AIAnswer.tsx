import { Sparkles, Clock } from "lucide-react";

interface AIAnswerProps {
  answer: string;
  searchTimeMs: number;
  totalResults: number;
}

export default function AIAnswer({ answer, searchTimeMs, totalResults }: AIAnswerProps) {
  return (
    <div className="bg-gradient-to-br from-primary/5 via-primary/3 to-secondary/5 border border-primary/15 rounded-2xl p-6">
      <div className="flex items-start gap-4">
        <div className="p-2.5 bg-primary rounded-xl flex-shrink-0">
          <Sparkles size={18} className="text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-3">
            <h3 className="font-semibold text-primary text-sm">AI Answer</h3>
            <div className="flex items-center gap-1 text-xs text-gray-400 ml-auto">
              <Clock size={11} />
              <span>{searchTimeMs}ms · {totalResults} results</span>
            </div>
          </div>
          <p className="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap">{answer}</p>
        </div>
      </div>
    </div>
  );
}
