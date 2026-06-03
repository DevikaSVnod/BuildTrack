import Link from "next/link";
import {
  HardHat, Building2, CheckSquare, Users, FileText,
  Search, ArrowRight, Star, Shield, Zap, BarChart2,
  ChevronRight,
} from "lucide-react";

const FEATURES = [
  {
    icon: Building2,
    title: "Project Tracking",
    description: "Track every project from planning to completion with real-time progress updates, milestone tracking, and budget management.",
    color: "bg-blue-50 text-blue-600",
  },
  {
    icon: Users,
    title: "Team Management",
    description: "Manage your entire construction crew — assign roles, track workloads, and keep everyone aligned on project goals.",
    color: "bg-purple-50 text-purple-600",
  },
  {
    icon: FileText,
    title: "Document Control",
    description: "Centralize all project documents — blueprints, contracts, reports — with version control and instant access.",
    color: "bg-green-50 text-green-600",
  },
  {
    icon: Search,
    title: "AI-Powered Search",
    description: "Ask natural language questions about your projects. Get instant AI answers powered by Azure OpenAI and semantic search.",
    color: "bg-amber-50 text-amber-600",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Create Your Project",
    description: "Set up projects with budgets, timelines, locations, and team assignments in minutes.",
  },
  {
    step: "02",
    title: "Track & Collaborate",
    description: "Assign tasks, upload documents, and monitor progress with your entire team in real time.",
  },
  {
    step: "03",
    title: "Get AI Insights",
    description: "Use natural language search to query project data and get instant AI-generated answers.",
  },
];

const STATS = [
  { value: "500+", label: "Projects Managed" },
  { value: "10,000+", label: "Tasks Tracked" },
  { value: "200+", label: "Teams Using BuildTrack" },
  { value: "99.9%", label: "Uptime" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Navbar */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-md border-b border-gray-100">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary rounded-xl">
              <HardHat size={20} className="text-secondary" />
            </div>
            <span className="font-bold text-xl text-primary">BuildTrack</span>
          </div>
          <div className="hidden md:flex items-center gap-6">
            <a href="#features" className="text-sm text-gray-600 hover:text-primary transition-colors">Features</a>
            <a href="#how-it-works" className="text-sm text-gray-600 hover:text-primary transition-colors">How It Works</a>
            <Link href="/login" className="text-sm text-gray-600 hover:text-primary transition-colors">Sign In</Link>
            <Link
              href="/register"
              className="bg-primary text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-primary-600 transition-colors"
            >
              Get Started Free
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-32 pb-20 px-6 bg-gradient-to-b from-primary/5 to-white">
        <div className="max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-secondary/10 text-secondary font-semibold text-sm px-4 py-1.5 rounded-full mb-6 border border-secondary/20">
            <Zap size={14} />
            AI-Powered Construction Management
          </div>
          <h1 className="text-5xl md:text-6xl font-extrabold text-gray-900 leading-tight mb-6">
            Manage Construction Projects{" "}
            <span className="text-primary">Smarter</span>
          </h1>
          <p className="text-xl text-gray-500 max-w-2xl mx-auto mb-10 leading-relaxed">
            BuildTrack combines powerful project management with AI-powered search to keep your construction
            projects on track, on budget, and on time.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href="/register"
              className="inline-flex items-center gap-2 bg-primary text-white font-semibold px-8 py-4 rounded-xl hover:bg-primary-600 transition-all shadow-lg shadow-primary/25 text-base"
            >
              Get Started Free
              <ArrowRight size={18} />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 border border-gray-200 text-gray-700 font-semibold px-8 py-4 rounded-xl hover:border-primary hover:text-primary transition-all text-base"
            >
              Sign In
              <ChevronRight size={18} />
            </Link>
          </div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="py-14 bg-primary">
        <div className="max-w-5xl mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            {STATS.map((stat) => (
              <div key={stat.label} className="text-center">
                <p className="text-3xl font-extrabold text-white mb-1">{stat.value}</p>
                <p className="text-primary-200 text-sm">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 px-6 bg-white">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
              Everything you need to manage construction projects
            </h2>
            <p className="text-gray-500 max-w-2xl mx-auto">
              From site surveys to project completion — BuildTrack covers every stage of your
              construction project lifecycle.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {FEATURES.map((feature) => (
              <div
                key={feature.title}
                className="p-6 rounded-2xl border border-gray-100 hover:border-primary/20 hover:shadow-lg transition-all duration-300 group"
              >
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${feature.color}`}>
                  <feature.icon size={24} />
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-2 group-hover:text-primary transition-colors">
                  {feature.title}
                </h3>
                <p className="text-gray-500 leading-relaxed">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-20 px-6 bg-gray-50">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
              Get started in 3 simple steps
            </h2>
            <p className="text-gray-500">Set up your construction management platform in minutes.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {HOW_IT_WORKS.map((step, i) => (
              <div key={step.step} className="relative">
                <div className="bg-white rounded-2xl p-6 border border-gray-100 shadow-sm h-full">
                  <span className="text-5xl font-extrabold text-primary/10">{step.step}</span>
                  <h3 className="text-lg font-semibold text-gray-900 mt-2 mb-3">{step.title}</h3>
                  <p className="text-gray-500 text-sm leading-relaxed">{step.description}</p>
                </div>
                {i < HOW_IT_WORKS.length - 1 && (
                  <div className="hidden md:flex absolute top-8 -right-4 text-gray-200">
                    <ArrowRight size={20} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-6 bg-primary">
        <div className="max-w-3xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-white/10 text-white font-medium text-sm px-4 py-1.5 rounded-full mb-6">
            <Star size={14} />
            Trusted by 200+ construction teams
          </div>
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
            Ready to streamline your construction projects?
          </h2>
          <p className="text-primary-200 mb-8 text-lg">
            Join hundreds of construction teams already using BuildTrack to deliver projects
            faster, smarter, and within budget.
          </p>
          <Link
            href="/register"
            className="inline-flex items-center gap-2 bg-secondary text-white font-bold px-8 py-4 rounded-xl hover:bg-secondary-600 transition-all shadow-lg text-base"
          >
            Start Building for Free
            <ArrowRight size={18} />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-gray-400 py-12 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col md:flex-row items-start justify-between gap-8">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <div className="p-2 bg-primary rounded-xl">
                  <HardHat size={18} className="text-secondary" />
                </div>
                <span className="font-bold text-white text-lg">BuildTrack</span>
              </div>
              <p className="text-sm max-w-xs">
                The complete construction project management platform for modern teams.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-8">
              <div>
                <h4 className="text-white font-semibold mb-3 text-sm">Product</h4>
                <ul className="space-y-2 text-sm">
                  {["Features", "Pricing", "Security", "Roadmap"].map((item) => (
                    <li key={item}>
                      <a href="#" className="hover:text-white transition-colors">{item}</a>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-white font-semibold mb-3 text-sm">Company</h4>
                <ul className="space-y-2 text-sm">
                  {["About", "Blog", "Careers", "Contact"].map((item) => (
                    <li key={item}>
                      <a href="#" className="hover:text-white transition-colors">{item}</a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
          <div className="mt-10 pt-6 border-t border-gray-800 flex flex-col md:flex-row items-center justify-between gap-4">
            <p className="text-xs">© 2024 BuildTrack. All rights reserved.</p>
            <div className="flex gap-4 text-xs">
              <a href="#" className="hover:text-white transition-colors">Privacy Policy</a>
              <a href="#" className="hover:text-white transition-colors">Terms of Service</a>
              <a href="#" className="hover:text-white transition-colors">Cookie Policy</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
