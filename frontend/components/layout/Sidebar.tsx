"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Building2, ClipboardList,
  Users, FolderOpen, Calendar,
  HardHat, LogOut, ShieldCheck,
  Layers, Package,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { clearAuth } from "@/lib/auth";
import { prefetchRoute } from "@/lib/prefetch";
import { useRouter } from "next/navigation";
import { useCurrentUser, userInitials } from "@/hooks/useCurrentUser";

type NavItem = { href: string; label: string; icon: typeof LayoutDashboard };

const SECTIONS: { heading?: string; items: NavItem[] }[] = [
  {
    items: [
      { href: "/dashboard", label: "Dashboard",        icon: LayoutDashboard },
      { href: "/projects",  label: "Projects",         icon: Building2 },
    ],
  },
  {
    heading: "OPERATIONS",
    items: [
      { href: "/tasks",     label: "Site Activities",  icon: ClipboardList },
      { href: "/timeline",  label: "Timeline",         icon: Calendar },
    ],
  },
  {
    heading: "LMS · LABOUR",
    items: [
      { href: "/team",        label: "Workforce",      icon: Users },
      { href: "/safety",      label: "Safety & HSE",   icon: ShieldCheck },
    ],
  },
  {
    heading: "ASSETS · PROCUREMENT",
    items: [
      { href: "/assets",      label: "Site Assets",    icon: Package },
    ],
  },
  {
    heading: "DMS · DOCUMENTS",
    items: [
      { href: "/documents",   label: "Document Control", icon: FolderOpen },
      { href: "/drawings",    label: "Drawings & Specs",  icon: Layers },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useCurrentUser();

  const handleLogout = () => {
    clearAuth();
    router.push("/login");
  };

  const handleNavIntent = (href: string) => {
    router.prefetch(href);
    prefetchRoute(href);
  };

  return (
    <aside className="w-64 h-screen bg-primary flex flex-col fixed left-0 top-0 z-30 overflow-hidden">
      {/* Logo — fixed at top */}
      <div className="flex-shrink-0 flex items-center gap-3 px-6 py-5 border-b border-white/10">
        <div className="p-2 bg-secondary rounded-lg">
          <HardHat size={20} className="text-white" />
        </div>
        <div>
          <span className="text-white font-bold text-lg leading-none">BuildTrack</span>
          <p className="text-blue-200 text-[10px] mt-0.5 uppercase tracking-widest font-medium">
            Construction PM
          </p>
        </div>
      </div>

      {/* Navigation — scrollable middle */}
      <nav
        className={cn(
          "flex-1 min-h-0 px-3 py-4 overflow-y-auto overflow-x-hidden space-y-4",
          "[&::-webkit-scrollbar]:w-2",
          "[&::-webkit-scrollbar-track]:bg-transparent",
          "[&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:bg-white/30",
          "hover:[&::-webkit-scrollbar-thumb]:bg-white/45",
          "[scrollbar-width:thin]",
          "[scrollbar-color:rgba(255,255,255,0.35)_transparent]"
        )}
        aria-label="Main navigation"
      >
        {SECTIONS.map((section, si) => (
          <div key={si}>
            {section.heading && (
              <p className="text-[10px] font-bold text-blue-300/60 uppercase tracking-widest px-3 mb-1">
                {section.heading}
              </p>
            )}
            <div className="space-y-0.5">
              {section.items.map(({ href, label, icon: Icon }) => {
                const active =
                  pathname === href ||
                  (href !== "/dashboard" && pathname.startsWith(href + "/"));
                return (
                  <Link
                    key={href}
                    href={href}
                    onMouseEnter={() => handleNavIntent(href)}
                    onFocus={() => handleNavIntent(href)}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150",
                      active
                        ? "bg-white/15 text-white"
                        : "text-blue-200 hover:bg-white/10 hover:text-white"
                    )}
                  >
                    <Icon size={16} className="flex-shrink-0" />
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}

      </nav>

      {/* User profile — fixed at bottom */}
      <div className="flex-shrink-0 px-4 py-4 border-t border-white/10 bg-primary">
        <div className="flex items-center gap-3 px-3 py-2 rounded-lg">
          <div
            className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
            suppressHydrationWarning
          >
            {userInitials(user?.full_name)}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white text-sm font-medium truncate" suppressHydrationWarning>
              {user?.full_name ?? "…"}
            </p>
            <p className="text-blue-300 text-xs truncate" suppressHydrationWarning>
              {user?.role ?? ""}
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="text-blue-300 hover:text-white transition-colors"
            title="Logout"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
}
