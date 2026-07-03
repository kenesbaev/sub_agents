import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rebly AI",
  description: "Hire a compact AI business team for Instagram and Telegram automation.",
  icons: {
    icon: "/images/rebly-logo-mark.svg",
    shortcut: "/images/rebly-logo-mark.svg",
    apple: "/images/rebly-logo-mark.svg",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
