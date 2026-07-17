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

const themeBootstrap = `
  (() => {
    try {
      const stored = localStorage.getItem("rebly-theme");
      const mode = stored === "light" || stored === "auto" ? stored : "dark";
      const dark = mode === "dark" || (mode === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      document.documentElement.style.colorScheme = dark ? "dark" : "light";
    } catch {
      document.documentElement.dataset.theme = "dark";
      document.documentElement.style.colorScheme = "dark";
    }
  })();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
