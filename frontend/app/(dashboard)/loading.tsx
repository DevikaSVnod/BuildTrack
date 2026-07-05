export default function DashboardLoading() {
  return (
    <div className="space-y-6 animate-pulse" aria-label="Loading page">
      <div className="space-y-2">
        <div className="h-8 w-64 rounded-lg bg-gray-200" />
        <div className="h-4 w-40 rounded bg-gray-100" />
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-20 rounded-xl bg-gray-100" />
        ))}
      </div>
      <div className="h-10 w-full max-w-md rounded-lg bg-gray-100" />
      <div className="h-72 rounded-xl bg-gray-100" />
    </div>
  );
}
