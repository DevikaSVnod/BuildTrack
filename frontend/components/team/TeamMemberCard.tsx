import { Mail, Briefcase, Building2, CheckSquare } from "lucide-react";
import type { TeamMember } from "@/types";
import { getInitials, ROLE_COLORS, cn } from "@/lib/utils";

interface TeamMemberCardProps {
  member: TeamMember;
  onRemove?: (id: number) => void;
}

const AVATAR_COLORS = [
  "bg-blue-600", "bg-purple-600", "bg-emerald-600",
  "bg-rose-600",  "bg-amber-600",  "bg-primary",
];

export default function TeamMemberCard({ member, onRemove }: TeamMemberCardProps) {
  const user = member.user;
  if (!user) return null;

  const roleColor  = ROLE_COLORS[user.role] || "bg-gray-100 text-gray-600";
  const avatarBg   = AVATAR_COLORS[user.id % AVATAR_COLORS.length];
  const isActive   = (member.active_projects_count ?? 0) > 0;

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-all duration-200 flex flex-col">
      {/* Top row */}
      <div className="flex items-start gap-3">
        <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center text-white font-bold text-base flex-shrink-0", avatarBg)}>
          {getInitials(user.full_name)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-gray-900 truncate">{user.full_name}</h3>
            <span className={cn(
              "inline-block w-2 h-2 rounded-full flex-shrink-0",
              isActive ? "bg-green-400" : "bg-gray-300"
            )} title={isActive ? "Active" : "Inactive"} />
          </div>
          <span className={cn("inline-block text-[11px] px-2 py-0.5 rounded-full font-semibold mt-1", roleColor)}>
            {user.role}
          </span>
        </div>
        {onRemove && (
          <button
            onClick={() => onRemove(member.id)}
            className="text-gray-300 hover:text-red-400 transition-colors text-lg leading-none"
            title="Remove"
          >
            ×
          </button>
        )}
      </div>

      {/* Details */}
      <div className="mt-4 space-y-1.5">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Mail size={12} className="flex-shrink-0 text-gray-400" />
          <span className="truncate">{user.email}</span>
        </div>
        {user.company_name && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Briefcase size={12} className="flex-shrink-0 text-gray-400" />
            <span className="truncate">{user.company_name}</span>
          </div>
        )}
      </div>

      {/* Stats footer */}
      <div className="mt-4 pt-4 border-t border-gray-50 grid grid-cols-2 gap-2">
        <div className="flex items-center gap-2 bg-primary/5 rounded-lg px-3 py-2">
          <Building2 size={13} className="text-primary flex-shrink-0" />
          <div>
            <p className="text-sm font-bold text-primary leading-none">{member.active_projects_count ?? 0}</p>
            <p className="text-[10px] text-gray-400 mt-0.5">Projects</p>
          </div>
        </div>
        <div className="flex items-center gap-2 bg-amber-50 rounded-lg px-3 py-2">
          <CheckSquare size={13} className="text-amber-600 flex-shrink-0" />
          <div>
            <p className="text-sm font-bold text-amber-600 leading-none">{member.tasks_count ?? 0}</p>
            <p className="text-[10px] text-gray-400 mt-0.5">Tasks</p>
          </div>
        </div>
      </div>
    </div>
  );
}
