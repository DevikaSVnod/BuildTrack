"use client";

import { useEffect, useState } from "react";
import { getCurrentUser } from "@/lib/auth";
import type { User } from "@/types";

/** Avoid hydration mismatch: user is null until client mount. */
export function useCurrentUser() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    setUser(getCurrentUser());
  }, []);

  return user;
}

export function userInitials(fullName?: string | null): string {
  if (!fullName) return "—";
  return fullName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
