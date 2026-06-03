import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BuildTrack — Construction Project Management",
  description: "Manage construction projects smarter with BuildTrack",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-background text-app-text antialiased">{children}</body>
    </html>
  );
}
