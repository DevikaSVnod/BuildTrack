"use client";
import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { Plus, Users, Sparkles, HardHat, ShieldCheck, ClipboardCheck, UserPlus } from "lucide-react";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import TeamMemberCard from "@/components/team/TeamMemberCard";
import AttendanceRegister, { type AttendanceRow } from "@/components/workforce/AttendanceRegister";
import Input from "@/components/ui/Input";
import { teamApi, operationalApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";
import { cachedProjectsOrFetch } from "@/lib/cachedFetch";
import type { TeamMember, Project } from "@/types";

type TeamPageData = { members: TeamMember[]; projects: Project[] };
type Tab = "personnel" | "attendance";

export default function TeamPage() {
  const { data, loading, reload } = usePageData<TeamPageData>(
    "team-page",
    async () => {
      const [m, p] = await Promise.all([teamApi.list(), cachedProjectsOrFetch()]);
      return { members: m.data, projects: p };
    },
  );
  const { data: attendance, loading: attendanceLoading } = usePageData<AttendanceRow[]>(
    "attendance",
    () => operationalApi.attendance().then((r) => r.data),
  );
  const members = data?.members ?? [];
  const projects = data?.projects ?? [];
  const attendanceRows = attendance ?? [];
  const [activeTab, setActiveTab] = useState<Tab>("personnel");
  const [showModal, setShowModal] = useState(false);
  const [highlightUserId, setHighlightUserId] = useState<number | null>(null);
  const searchParams = useSearchParams();
  const highlightRef = useRef<HTMLDivElement>(null);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    company_name: "",
    role: "Site Engineer",
    project_id: "",
  });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");

  const fetchData = () => reload();

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab === "attendance") setActiveTab("attendance");

    const id = searchParams.get("userId");
    if (id) {
      setHighlightUserId(Number(id));
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 700);
      const timer = setTimeout(() => setHighlightUserId(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  const uniqueMembers = Array.from(
    new Map(members.map((m) => [m.user_id, m])).values()
  );

  const handleRemove = async (id: number) => {
    if (!confirm("Remove this team member?")) return;
    await teamApi.remove(id);
    fetchData();
  };

  const set = (key: string, val: string) => setForm((f) => ({ ...f, [key]: val }));

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true);
    setAddError("");
    try {
      const { authApi } = await import("@/lib/api");
      const regRes = await authApi.register({
        full_name: form.full_name,
        email: form.email,
        password: "Welcome@123",
        company_name: form.company_name,
        role: form.role,
      });
      const newUser = regRes.data.user;
      await teamApi.add({
        user_id: newUser.id,
        project_id: form.project_id ? parseInt(form.project_id) : undefined,
        role: form.role,
      });
      setShowModal(false);
      setForm({ full_name: "", email: "", company_name: "", role: "Site Engineer", project_id: "" });
      fetchData();
    } catch (err: any) {
      setAddError(err?.response?.data?.detail || "Failed to add member");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* LMS Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-widest text-primary bg-primary/10 px-2.5 py-0.5 rounded-full">
              LMS · Labour Management
            </span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Workforce Management</h1>
          <p className="text-gray-500 text-sm mt-1">
            {uniqueMembers.length} personnel registered across all projects
          </p>
        </div>
        <div className="flex items-center gap-3">
          <a href="/safety" className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-xl text-sm font-medium hover:bg-gray-200 transition-colors">
            <ShieldCheck size={15} /> Safety
          </a>
          {activeTab === "personnel" && (
            <Button onClick={() => setShowModal(true)}>
              <UserPlus size={16} /> Add Personnel
            </Button>
          )}
        </div>
      </div>

      <div className="border-b border-gray-200">
        <div className="flex gap-1">
          {([
            { id: "personnel" as const, label: "Personnel", count: uniqueMembers.length },
            { id: "attendance" as const, label: "Attendance", count: attendanceRows.length },
          ]).map(({ id, label, count }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === id
                  ? "border-primary text-primary"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {label}
              {count > 0 && <span className="ml-1.5 text-xs text-gray-400">({count})</span>}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "attendance" ? (
        <AttendanceRegister rows={attendanceRows} loading={attendanceLoading && attendanceRows.length === 0} />
      ) : (
        <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Total Personnel",  value: uniqueMembers.length,                                                icon: Users,         color: "text-primary",   bg: "bg-primary/10" },
          { label: "Project Managers", value: uniqueMembers.filter((m) => m.user?.role === "Project Manager").length, icon: HardHat,       color: "text-blue-600",  bg: "bg-blue-50"    },
          { label: "Site Engineers",   value: uniqueMembers.filter((m) => m.user?.role === "Site Engineer").length,   icon: ClipboardCheck,color: "text-amber-600", bg: "bg-amber-50"   },
          { label: "Contractors",      value: uniqueMembers.filter((m) => m.user?.role === "Contractor").length,      icon: ShieldCheck,   color: "text-green-600", bg: "bg-green-50"   },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-3">
            <div className={`p-2.5 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={18} className={color} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-xl font-bold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Search highlight banner */}
      {highlightUserId && (
        <div ref={highlightRef} className="flex items-center gap-2 px-4 py-2.5 bg-primary/5 border border-primary/20 rounded-xl text-sm text-primary font-medium">
          <Sparkles size={14} />
          Navigated from search — team member highlighted below
        </div>
      )}

      {loading && uniqueMembers.length === 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border h-48 animate-pulse" />
          ))}
        </div>
      ) : uniqueMembers.length === 0 ? (
        <div className="text-center py-20">
          <Users size={48} className="text-gray-200 mx-auto mb-4" />
          <h3 className="font-semibold text-gray-500 mb-2">No team members yet</h3>
          <p className="text-gray-400 text-sm mb-6">Add team members to get started</p>
          <Button onClick={() => setShowModal(true)}>
            <Plus size={16} /> Add First Member
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {uniqueMembers.map((m) => (
            <div
              key={m.id}
              ref={highlightUserId === m.user_id ? highlightRef : null}
              className={`rounded-xl transition-all duration-700 ${
                highlightUserId === m.user_id
                  ? "ring-2 ring-purple-400 ring-offset-2 shadow-lg scale-[1.02]"
                  : ""
              }`}
            >
              {highlightUserId === m.user_id && (
                <div className="flex items-center gap-1.5 text-xs font-semibold text-purple-600 bg-purple-50 rounded-t-xl px-3 py-1.5 border border-purple-200 border-b-0">
                  <Sparkles size={11} />
                  Search result
                </div>
              )}
              <TeamMemberCard member={m} onRemove={handleRemove} />
            </div>
          ))}
        </div>
      )}
        </>
      )}

      <Modal open={showModal} onClose={() => setShowModal(false)} title="Add Team Member">
        <form onSubmit={handleAddMember} className="space-y-4">
          <Input
            label="Full Name *"
            value={form.full_name}
            onChange={(e) => set("full_name", e.target.value)}
            placeholder="John Smith"
            required
          />
          <Input
            label="Email *"
            type="email"
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
            placeholder="john@company.com"
            required
          />
          <Input
            label="Company"
            value={form.company_name}
            onChange={(e) => set("company_name", e.target.value)}
            placeholder="Construction Co."
          />
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-700">Role</label>
            <select
              value={form.role}
              onChange={(e) => set("role", e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            >
              <option value="Admin">Admin</option>
              <option value="Project Manager">Project Manager</option>
              <option value="Site Engineer">Site Engineer</option>
              <option value="Contractor">Contractor</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-700">Assign to Project (optional)</label>
            <select
              value={form.project_id}
              onChange={(e) => set("project_id", e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            >
              <option value="">No project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <p className="text-xs text-gray-400">Default password: Welcome@123</p>
          {addError && <p className="text-sm text-danger">{addError}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setShowModal(false)}>Cancel</Button>
            <Button type="submit" loading={adding}>Add Member</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
