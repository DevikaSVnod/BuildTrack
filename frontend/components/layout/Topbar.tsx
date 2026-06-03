"use client";
import { Bell } from "lucide-react";
import SearchBar from "./SearchBar";
import { useState } from "react";
import { useCurrentUser, userInitials } from "@/hooks/useCurrentUser";

export default function Topbar() {
  const user = useCurrentUser();
  const [showNotifications, setShowNotifications] = useState(false);

  const notifications = [
    { id: 1, text: "Task 'Steel Erection' is due in 2 days", time: "1h ago" },
    { id: 2, text: "New document uploaded to Bridge Expansion", time: "3h ago" },
    { id: 3, text: "Priya Nair updated Commercial Tower status", time: "5h ago" },
  ];

  return (
    <header className="h-16 bg-white border-b border-gray-100 flex items-center gap-4 px-6 sticky top-0 z-20">
      {/* Search bar — takes most of the space */}
      <div className="flex-1">
        <SearchBar />
      </div>

      {/* Right side */}
      <div className="flex items-center gap-3 flex-shrink-0">
        {/* Notifications */}
        <div className="relative">
          <button
            onClick={() => setShowNotifications(!showNotifications)}
            className="relative p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <Bell size={20} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-secondary rounded-full" />
          </button>

          {showNotifications && (
            <div className="absolute right-0 top-full mt-2 w-80 bg-white rounded-xl shadow-xl border border-gray-100 z-50">
              <div className="px-4 py-3 border-b border-gray-100">
                <h3 className="font-semibold text-gray-900 text-sm">Notifications</h3>
              </div>
              <div className="divide-y divide-gray-50">
                {notifications.map((n) => (
                  <div key={n.id} className="px-4 py-3 hover:bg-gray-50 cursor-pointer">
                    <p className="text-sm text-gray-700">{n.text}</p>
                    <p className="text-xs text-gray-400 mt-1">{n.time}</p>
                  </div>
                ))}
              </div>
              <div className="px-4 py-2 border-t border-gray-100">
                <button
                  onClick={() => setShowNotifications(false)}
                  className="text-xs text-primary font-medium hover:underline"
                >
                  View all notifications
                </button>
              </div>
            </div>
          )}
        </div>

        {/* User avatar */}
        <div className="flex items-center gap-2.5 pl-3 border-l border-gray-200">
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
      </div>
    </header>
  );
}
