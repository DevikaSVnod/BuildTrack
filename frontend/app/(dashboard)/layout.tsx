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

  // Warm route JS bundles after login; stagger API prefetches to avoid request bursts.
  useEffect(() => {
    const timers: number[] = [];
    const startTimer = window.setTimeout(() => {
      PREFETCH_ROUTES.forEach((href, index) => {
        router.prefetch(href);
        timers.push(
          window.setTimeout(() => prefetchRoute(href), index * 400),
        );
      });
    }, 2000);
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
