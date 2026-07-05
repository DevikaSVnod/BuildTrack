"use client";
import SearchBar from "./SearchBar";
import { useCurrentUser, userInitials } from "@/hooks/useCurrentUser";

export default function Topbar() {
  const user = useCurrentUser();

  return (
    <header className="h-16 bg-white border-b border-gray-100 flex items-center gap-4 px-6 sticky top-0 z-20 min-w-0 overflow-visible">
      <div className="flex-1 min-w-0">
        <SearchBar />
      </div>

      <div className="flex items-center gap-2.5 flex-shrink-0 pl-3 border-l border-gray-200">
        <div
          className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-white text-xs font-bold"
          suppressHydrationWarning
        >
          {userInitials(user?.full_name)}
        </div>
        <div className="hidden md:block">
          <p className="text-sm font-medium text-gray-900 leading-none" suppressHydrationWarning>
            {user?.full_name ?? "…"}
          </p>
          <p className="text-xs text-gray-500 mt-0.5" suppressHydrationWarning>
            {user?.role ?? ""}
          </p>
        </div>
      </div>
    </header>
  );
}
