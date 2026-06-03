import Cookies from "js-cookie";
import type { User, TokenResponse } from "@/types";

const TOKEN_KEY = "buildtrack_token";
const USER_KEY = "buildtrack_user";

export function setAuthData(data: TokenResponse): void {
  Cookies.set(TOKEN_KEY, data.access_token, { expires: 1, sameSite: "strict" });
  if (typeof window !== "undefined") {
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  }
}

export function getToken(): string | null {
  return Cookies.get(TOKEN_KEY) || null;
}

export function getCurrentUser(): User | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem(USER_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored) as User;
  } catch {
    return null;
  }
}

export function clearAuth(): void {
  Cookies.remove(TOKEN_KEY);
  if (typeof window !== "undefined") {
    localStorage.removeItem(USER_KEY);
  }
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
