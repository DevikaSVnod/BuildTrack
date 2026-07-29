"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import Topbar from "@/components/layout/Topbar";
import { isAuthenticated } from "@/lib/auth";
import { PREFETCH_ROUTES, prefetchRoute } from "@/lib/prefetch";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
    }
  }, [router]);

  // Warm route JS + data after login. Prioritize Documents/Drawings; stagger
  // heavily so Azure Search/SQL are not stampeded on first paint.
  useEffect(() => {
    const timers: number[] = [];
    const priority = ["/documents", "/drawings", "/projects", "/dashboard"];
    const rest = PREFETCH_ROUTES.filter((h) => !priority.includes(h));
    const ordered = [...priority.filter((h) => PREFETCH_ROUTES.includes(h)), ...rest];

    const startTimer = window.setTimeout(() => {
      ordered.forEach((href, index) => {
        router.prefetch(href);
        timers.push(
          window.setTimeout(() => prefetchRoute(href), index * 700),
        );
      });
    }, 1500);
    return () => {
      window.clearTimeout(startTimer);
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, [router]);

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 ml-64 flex flex-col min-h-screen min-w-0">
        <Topbar />
        <main className="flex-1 p-6 min-w-0 max-w-full overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
