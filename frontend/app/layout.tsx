import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Teamora AI",
  description: "Build a connected AI team for sales, marketing, support, and automation.",
  icons: {
    icon: "/images/teamora-ai-logo-mark.svg",
    shortcut: "/images/teamora-ai-logo-mark.svg",
    apple: "/images/teamora-ai-logo-mark.svg",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
