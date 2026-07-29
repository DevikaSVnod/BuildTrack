"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Package, Wrench, Truck, CheckCircle2, MapPin, AlertCircle,
} from "lucide-react";
import { assetsApi } from "@/lib/api";
import { usePageData } from "@/hooks/usePageData";
import { cn } from "@/lib/utils";

type Tab = "equipment" | "vendors" | "materials";

interface EquipmentRow {
  id: number;
  asset_tag: string;
  name: string;
  category: string;
  project_name: string | null;
  status: string;
  vendor_name: string | null;
  location: string | null;
  last_service_date: string | null;
  notes: string | null;
}

interface VendorRow {
  id: number;
  name: string;
  category: string;
  contact_email: string | null;
  phone: string | null;
  rating: number | null;
  status: string;
  notes: string | null;
}

interface MaterialRow {
  id: number;
  delivery_ref: string;
  material_name: string;
  quantity: number;
  unit: string;
  project_name: string | null;
  vendor_name: string | null;
  status: string;
  expected_date: string | null;
  delivered_date: string | null;
  notes: string | null;
}

interface AssetsOverview {
  equipment: EquipmentRow[];
  vendors: VendorRow[];
  materials: MaterialRow[];
  metrics: {
    equipment_total: number;
    equipment_on_site: number;
    vendors_total: number;
    vendors_active: number;
    materials_total: number;
    materials_open: number;
    materials_delivered: number;
  };
  source: { id: string; label: string; database: string };
}

const STATUS_PILL: Record<string, string> = {
  "On Site": "bg-green-100 text-green-700",
  Active: "bg-green-100 text-green-700",
  Delivered: "bg-green-100 text-green-700",
  Maintenance: "bg-amber-100 text-amber-700",
  "In Transit": "bg-amber-100 text-amber-700",
  Ordered: "bg-blue-100 text-blue-700",
  Shipped: "bg-blue-100 text-blue-700",
  Idle: "bg-gray-100 text-gray-600",
  Inactive: "bg-gray-100 text-gray-600",
};

function statusClass(status: string) {
  return STATUS_PILL[status] || "bg-gray-100 text-gray-600";
}

export default function AssetsPage() {
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<Tab>("equipment");
  const { data, loading } = usePageData<AssetsOverview>("assets-overview", async () => {
    const res = await assetsApi.overview();
    return res.data;
  });

  useEffect(() => {
    const t = searchParams.get("tab");
    if (t === "vendors" || t === "materials" || t === "equipment") setTab(t);
  }, [searchParams]);

  const metrics = data?.metrics;
  const showLoading = loading && !data;

  const METRICS = [
    {
      label: "Equipment on site",
      value: metrics?.equipment_on_site ?? "—",
      sub: metrics ? `${metrics.equipment_total} total` : undefined,
      icon: Wrench,
      color: "text-orange-600",
      bg: "bg-orange-50",
    },
    {
      label: "Active vendors",
      value: metrics?.vendors_active ?? "—",
      sub: metrics ? `${metrics.vendors_total} total` : undefined,
      icon: Truck,
      color: "text-sky-600",
      bg: "bg-sky-50",
    },
    {
      label: "Open deliveries",
      value: metrics?.materials_open ?? "—",
      sub: metrics ? `${metrics.materials_delivered} delivered` : undefined,
      icon: Package,
      color: "text-lime-700",
      bg: "bg-lime-50",
    },
    {
      label: "Data source",
      value: "Azure SQL",
      sub: data?.source.database ?? "buildtrack_assets",
      icon: CheckCircle2,
      color: "text-primary",
      bg: "bg-primary/10",
    },
  ];

  const TABS: { id: Tab; label: string; count?: number }[] = [
    { id: "equipment", label: "Equipment", count: data?.equipment.length },
    { id: "vendors", label: "Vendors", count: data?.vendors.length },
    { id: "materials", label: "Material Deliveries", count: data?.materials.length },
  ];

  return (
    <div className="space-y-6 min-w-0 max-w-full">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold text-gray-900">Site Assets & Procurement</h1>
        <p className="text-gray-500 text-sm mt-1">
          Equipment, vendors, and material deliveries from the assets database
        </p>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {METRICS.map(({ label, value, sub, icon: Icon, color, bg }) => (
          <div
            key={label}
            className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-3 min-w-0"
          >
            <div className={`p-2.5 rounded-xl flex-shrink-0 ${bg}`}>
              <Icon size={18} className={color} />
            </div>
            <div className="min-w-0">
              <p className="text-xs sm:text-sm text-gray-500 truncate">{label}</p>
              <p className="text-xl sm:text-2xl font-bold text-gray-900">
                {showLoading ? "—" : value}
              </p>
              {sub && <p className="text-[11px] text-gray-400 truncate">{sub}</p>}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {TABS.map(({ id, label, count }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
              tab === id
                ? "border-primary text-primary"
                : "border-transparent text-gray-500 hover:text-gray-800"
            )}
          >
            {label}
            {count != null && (
              <span className="ml-2 text-xs text-gray-400">{count}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "equipment" && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden min-w-0">
          <table className="w-full table-fixed">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th className="text-left px-3 sm:px-4 py-3 w-[100px]">Tag</th>
                <th className="text-left px-3 sm:px-4 py-3">Name</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[14%] hidden md:table-cell">Category</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[20%] hidden lg:table-cell">Project</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[16%] hidden xl:table-cell">Location</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[100px]">Status</th>
              </tr>
            </thead>
            <tbody>
              {showLoading && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">
                    Loading equipment…
                  </td>
                </tr>
              )}
              {!showLoading && (data?.equipment.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">
                    <AlertCircle className="inline mr-2" size={16} />
                    No equipment records
                  </td>
                </tr>
              )}
              {data?.equipment.map((row) => (
                <tr key={row.id} className="border-b border-gray-50 hover:bg-gray-50/80">
                  <td className="px-3 sm:px-4 py-3 text-sm font-mono font-semibold text-gray-800">
                    {row.asset_tag}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-900 min-w-0">
                    <p className="font-medium truncate">{row.name}</p>
                    {row.vendor_name && (
                      <p className="text-xs text-gray-400 truncate">{row.vendor_name}</p>
                    )}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-600 hidden md:table-cell truncate">
                    {row.category}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-600 hidden lg:table-cell truncate">
                    {row.project_name || "—"}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-500 hidden xl:table-cell truncate">
                    {row.location ? (
                      <span className="inline-flex items-center gap-1">
                        <MapPin size={12} /> {row.location}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 sm:px-4 py-3">
                    <span
                      className={cn(
                        "inline-block px-2 py-0.5 rounded-md text-xs font-medium",
                        statusClass(row.status)
                      )}
                    >
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "vendors" && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden min-w-0">
          <table className="w-full table-fixed">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th className="text-left px-3 sm:px-4 py-3">Vendor</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[18%] hidden md:table-cell">Category</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[22%] hidden lg:table-cell">Contact</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[80px]">Rating</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[100px]">Status</th>
              </tr>
            </thead>
            <tbody>
              {showLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    Loading vendors…
                  </td>
                </tr>
              )}
              {data?.vendors.map((row) => (
                <tr key={row.id} className="border-b border-gray-50 hover:bg-gray-50/80">
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-900 min-w-0">
                    <p className="font-medium truncate">{row.name}</p>
                    {row.notes && (
                      <p className="text-xs text-gray-400 truncate">{row.notes}</p>
                    )}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-600 hidden md:table-cell truncate">
                    {row.category}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-600 hidden lg:table-cell min-w-0">
                    <p className="truncate">{row.contact_email || "—"}</p>
                    {row.phone && <p className="text-xs text-gray-400">{row.phone}</p>}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm font-semibold text-gray-800">
                    {row.rating != null ? row.rating.toFixed(1) : "—"}
                  </td>
                  <td className="px-3 sm:px-4 py-3">
                    <span
                      className={cn(
                        "inline-block px-2 py-0.5 rounded-md text-xs font-medium",
                        statusClass(row.status)
                      )}
                    >
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "materials" && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden min-w-0">
          <table className="w-full table-fixed">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <th className="text-left px-3 sm:px-4 py-3 w-[100px]">Ref</th>
                <th className="text-left px-3 sm:px-4 py-3">Material</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[100px] hidden md:table-cell">Qty</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[18%] hidden lg:table-cell">Project</th>
                <th className="text-left px-3 sm:px-4 py-3 w-[100px]">Status</th>
              </tr>
            </thead>
            <tbody>
              {showLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    Loading deliveries…
                  </td>
                </tr>
              )}
              {data?.materials.map((row) => (
                <tr key={row.id} className="border-b border-gray-50 hover:bg-gray-50/80">
                  <td className="px-3 sm:px-4 py-3 text-sm font-mono font-semibold text-gray-800">
                    {row.delivery_ref}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-900 min-w-0">
                    <p className="font-medium truncate">{row.material_name}</p>
                    {row.vendor_name && (
                      <p className="text-xs text-gray-400 truncate">{row.vendor_name}</p>
                    )}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-600 hidden md:table-cell">
                    {row.quantity} {row.unit}
                  </td>
                  <td className="px-3 sm:px-4 py-3 text-sm text-gray-600 hidden lg:table-cell truncate">
                    {row.project_name || "—"}
                  </td>
                  <td className="px-3 sm:px-4 py-3">
                    <span
                      className={cn(
                        "inline-block px-2 py-0.5 rounded-md text-xs font-medium",
                        statusClass(row.status)
                      )}
                    >
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
