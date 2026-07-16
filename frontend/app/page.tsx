"use client";

import Link from "next/link";
import { ArrowRight, Menu, X } from "lucide-react";
import { useState } from "react";

import styles from "./page.module.css";

const brandColumns = [
  [
    { mark: "⊞", name: "Microsoft" },
    { mark: "S", name: "Shopify" },
    { mark: "◉", name: "GitHub" },
  ],
  [
    { mark: "∞", name: "Meta" },
    { mark: "in", name: "LinkedIn" },
    { mark: "◖◗", name: "Discord" },
  ],
  [
    { mark: "G", name: "Google" },
    { mark: "#", name: "Slack" },
    { mark: "N", name: "Notion" },
  ],
  [
    { mark: "➤", name: "Telegram" },
    { mark: "▶", name: "YouTube" },
    { mark: "◇", name: "Dropbox" },
  ],
];

function CosmicBackdrop() {
  return (
    <div className={styles.cosmos} aria-hidden="true">
      <span className={styles.starsFar} />
      <span className={styles.starsNear} />
      <span className={styles.auroraLeft} />
      <span className={styles.auroraRight} />
      <span className={styles.auroraTop} />
      <span className={styles.shootingStar} />
    </div>
  );
}

function Header() {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = () => setMenuOpen(false);

  return (
    <header className={styles.header}>
      <Link className={styles.brand} href="/" onClick={closeMenu}>
        <img src="/images/teamora-ai-logo-mark.svg" alt="" />
        <span>Teamora AI</span>
      </Link>

      <div className={styles.headerActions}>
        <Link className={styles.loginLink} href="/auth?mode=login">
          Log in
        </Link>
        <Link className={styles.startButton} href="/auth?mode=signup">
          Get started
        </Link>
        <button
          className={styles.menuButton}
          type="button"
          aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-controls="landing-mobile-nav"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X size={19} /> : <Menu size={20} />}
        </button>
      </div>

      {menuOpen ? (
        <nav id="landing-mobile-nav" className={styles.mobileNav} aria-label="Account navigation">
          <div className={styles.mobileNavFooter}>
            <Link className={styles.loginLink} href="/auth?mode=login" onClick={closeMenu}>
              Log in
            </Link>
            <Link className={styles.startButton} href="/auth?mode=signup" onClick={closeMenu}>
              Get started
            </Link>
          </div>
        </nav>
      ) : null}
    </header>
  );
}

export default function HomePage() {
  return (
    <div className={styles.landing}>
      <Header />
      <main>
        <section id="product" className={styles.hero}>
          <CosmicBackdrop />
          <div className={styles.heroContent}>
            <h1 className={styles.heroTitle}>
              Your AI team.
              <span>Ready to work.</span>
            </h1>
            <p className={styles.heroDescription}>
              Connect your tools, delegate work, and let specialized AI teammates handle marketing, sales, support and daily operations.
            </p>
            <div className={styles.heroActions}>
              <Link className={styles.heroPrimary} href="/auth?mode=signup">
                Start
                <ArrowRight size={21} strokeWidth={1.8} />
              </Link>
            </div>
          </div>

          <div className={styles.brandShowcase}>
            <p className={styles.brandIntro}>
              One AI workspace for the tools modern teams use every day.
            </p>
            <div className={styles.brandRail} aria-hidden="true">
              {brandColumns.map((brands, columnIndex) => (
                <div className={styles.brandWindow} key={columnIndex}>
                  <div className={styles.brandStack}>
                    {[...brands, brands[0]].map((brand, brandIndex) => (
                      <div className={styles.brandItem} key={`${brand.name}-${brandIndex}`}>
                        <span className={styles.brandMark}>{brand.mark}</span>
                        <span className={styles.brandWord}>{brand.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

      </main>
    </div>
  );
}
