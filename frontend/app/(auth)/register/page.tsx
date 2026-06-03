"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { HardHat, Mail, Lock, User, Building } from "lucide-react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { authApi } from "@/lib/api";
import { setAuthData } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    company_name: "",
    role: "Site Engineer",
  });

  const set = (key: string, val: string) => setForm((f) => ({ ...f, [key]: val }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agreed) {
      setError("Please accept the terms and conditions");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await authApi.register(form);
      setAuthData(res.data);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Registration failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary via-primary-600 to-primary-800 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-secondary rounded-2xl mb-4 shadow-lg">
            <HardHat size={28} className="text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">BuildTrack</h1>
          <p className="text-primary-200 mt-1 text-sm">Construction Project Management</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-2xl p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-1">Create your account</h2>
          <p className="text-gray-500 text-sm mb-6">Start managing projects smarter today</p>

          {error && (
            <div className="bg-red-50 border border-red-100 text-red-600 text-sm rounded-lg px-4 py-3 mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Full Name *"
              type="text"
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              placeholder="John Smith"
              leftIcon={<User size={16} />}
              required
            />
            <Input
              label="Email Address *"
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              placeholder="john@company.com"
              leftIcon={<Mail size={16} />}
              required
            />
            <Input
              label="Password *"
              type="password"
              value={form.password}
              onChange={(e) => set("password", e.target.value)}
              placeholder="Min. 8 characters"
              leftIcon={<Lock size={16} />}
              required
            />
            <Input
              label="Company Name"
              type="text"
              value={form.company_name}
              onChange={(e) => set("company_name", e.target.value)}
              placeholder="Your Construction Company"
              leftIcon={<Building size={16} />}
            />
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">Role *</label>
              <select
                value={form.role}
                onChange={(e) => set("role", e.target.value)}
                required
                className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
              >
                <option value="Admin">Admin</option>
                <option value="Project Manager">Project Manager</option>
                <option value="Site Engineer">Site Engineer</option>
                <option value="Contractor">Contractor</option>
              </select>
            </div>

            <label className="flex items-start gap-2 cursor-pointer mt-2">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
                className="w-4 h-4 mt-0.5 rounded border-gray-300 text-primary focus:ring-primary flex-shrink-0"
              />
              <span className="text-sm text-gray-600">
                I agree to the{" "}
                <button type="button" className="text-primary hover:underline font-medium">
                  Terms of Service
                </button>{" "}
                and{" "}
                <button type="button" className="text-primary hover:underline font-medium">
                  Privacy Policy
                </button>
              </span>
            </label>

            <Button type="submit" className="w-full" size="lg" loading={loading}>
              Create Account
            </Button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-sm text-gray-500">
              Already have an account?{" "}
              <Link href="/login" className="text-primary font-medium hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
