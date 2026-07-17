import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import { PricingSection } from "../pricing-section";
import styles from "./page.module.css";

export const metadata = {
  title: "Pricing | Teamora AI",
  description: "Start, Plus, Pro, and Custom workspace plans for Teamora AI.",
};

export default function PricingPage() {
  return (
    <main className={styles.page}>
      <h1 className={styles.srOnly}>Teamora AI pricing</h1>
      <header className={styles.header}>
        <Link className={styles.brand} href="/" aria-label="Teamora AI home">
          <img src="/images/teamora-ai-logo-mark.svg" alt="" />
          <span>Teamora AI</span>
        </Link>
        <nav className={styles.actions} aria-label="Pricing navigation">
          <Link href="/dashboard">
            <ArrowLeft size={16} aria-hidden="true" />
            Back to workspace
          </Link>
        </nav>
      </header>

      <PricingSection />

      <footer className={styles.footer}>
        <ShieldCheck size={17} aria-hidden="true" />
        <span>Need a custom rollout? Contact sales@teamorai.uz.</span>
      </footer>
    </main>
  );
}
