"use client";
import { Sparkles, Search } from "lucide-react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SearchPage() {
  const router = useRouter();

  // Redirect to dashboard — search is now in the top bar
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <div className="p-4 bg-primary/10 rounded-2xl mb-4">
        <Sparkles size={32} className="text-primary" />
      </div>
      <h2 className="text-xl font-semibold text-gray-900 mb-2">AI Search is in the top bar</h2>
      <p className="text-gray-500 text-sm">Redirecting you to the dashboard...</p>
    </div>
  );
}
