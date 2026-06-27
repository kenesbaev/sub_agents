"use client";

import Image from "next/image";
import Link from "next/link";
import { Bot, BriefcaseBusiness, Check, Moon, Send, Sparkles, Sun, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";

const plans = [
  {
    name: "Starter",
    price: "$6",
    suffix: "today",
    copy: "Your first Business AI workforce for Instagram and Telegram.",
    stats: ["1 team", "4 agents", "$20 credits"],
    features: ["Business AI team", "Tasks + activity", "Instagram + Telegram ready"],
    cta: "Start for $6"
  },
  {
    name: "Business",
    price: "$89",
    suffix: "/mo",
    copy: "More workflows, approval gates, and room to scale.",
    stats: ["3 teams", "12 agents", "$80 credits"],
    features: ["Multiple workspaces", "Priority automations", "Best value"],
    cta: "Scale up",
    popular: true
  },
  {
    name: "Agency",
    price: "$179",
    suffix: "/mo",
    copy: "Build a full AI department for client operations.",
    stats: ["10 teams", "40 agents", "$170 credits"],
    features: ["Client workspaces", "Dedicated support", "Advanced controls"],
    cta: "Go all in"
  }
];

function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("rebly-theme");
    const nextDark = stored === "dark";
    setDark(nextDark);
    document.documentElement.dataset.theme = nextDark ? "dark" : "light";
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    localStorage.setItem("rebly-theme", next ? "dark" : "light");
  }

  return (
    <button className="icon-button" type="button" onClick={toggle} aria-label="Toggle theme">
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

function Header() {
  return (
    <header className="site-header">
      <Link className="brand" href="/">
        <span className="brand-mark">
          <Bot size={20} />
        </span>
        <span>Rebly AI</span>
      </Link>
      <nav className="top-nav" aria-label="Main navigation">
        <a href="#how-it-works">How it works</a>
        <a href="#pricing">Pricing</a>
      </nav>
      <div className="header-actions">
        <ThemeToggle />
        <Link className="button" href="/auth?mode=login">
          Log in
        </Link>
        <Link className="button primary" href="/auth?mode=signup">
          Get started
        </Link>
      </div>
    </header>
  );
}

function MiniAvatar({ skin, hair, shirt }: { skin: string; hair: string; shirt: string }) {
  return <span className="mini-avatar" style={{ "--skin": skin, "--hair": hair, "--shirt": shirt } as React.CSSProperties} />;
}

export default function HomePage() {
  return (
    <div className="grid-page">
      <Header />
      <main>
        <section className="hero">
          <div className="hero-stack">
            <div className="speech">What task do you want to solve?</div>
            <Image className="hero-avatar" src="/images/coordinator.png" width={608} height={608} alt="Rebly AI coordinator" priority />
            <div className="nameplate">Coordinator</div>
            <div className="prompt-row">
              <div className="prompt-box">e.g. automate Instagram DMs and Telegram follow-ups...</div>
              <Link className="icon-button send-button" href="/auth?mode=signup" aria-label="Start">
                <Send size={24} />
              </Link>
            </div>
            <div className="chips">
              <span className="chip">
                <BriefcaseBusiness size={16} />
                Business AI
              </span>
              <span className="chip">
                <UsersRound size={16} />
                Instagram
              </span>
              <span className="chip">
                <Sparkles size={16} />
                Telegram
              </span>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="section">
          <div className="section-head">
            <p>How it works</p>
            <h2>Three simple steps to your AI team</h2>
          </div>
          <div className="steps">
            <article className="step">
              <span className="step-number">01</span>
              <div className="step-people">
                <MiniAvatar skin="#d89b72" hair="#172033" shirt="#1360aa" />
              </div>
              <h3>Subscribe</h3>
              <p>Choose a plan and open your Rebly AI workspace.</p>
            </article>
            <article className="step">
              <span className="step-number">02</span>
              <div className="step-people">
                <MiniAvatar skin="#9b6a4d" hair="#222634" shirt="#0c98a8" />
                <MiniAvatar skin="#d59668" hair="#243044" shirt="#6b70e8" />
                <MiniAvatar skin="#c78c63" hair="#151923" shirt="#94a3b8" />
              </div>
              <h3>Hire your team</h3>
              <p>Business AI agents coordinate Instagram and Telegram work.</p>
            </article>
            <article className="step">
              <span className="step-number">03</span>
              <div className="step-people">
                <MiniAvatar skin="#e0aa80" hair="#394150" shirt="#7c8cff" />
                <MiniAvatar skin="#d59668" hair="#7a4c36" shirt="#f0b84d" />
                <MiniAvatar skin="#8f6045" hair="#1f2937" shirt="#111827" />
              </div>
              <h3>Assign tasks</h3>
              <p>Track replies, follow-ups, and daily activity in one dashboard.</p>
            </article>
          </div>
        </section>

        <section id="pricing" className="section pricing-section">
          <div className="pricing-intro">
            <div className="pricing-avatar">
              <Image src="/images/coordinator.png" width={608} height={608} alt="" />
              <strong>Accountant</strong>
            </div>
            <div className="pricing-copy">
              <p>Pricing</p>
              <h2>Choose the right size for your team</h2>
              <span>Start small, then scale your AI workforce when your automation needs grow.</span>
            </div>
          </div>
          <div className="pricing-grid">
            {plans.map((plan) => (
              <article className={`price-card ${plan.popular ? "popular" : ""}`} key={plan.name}>
                {plan.popular && <span className="badge">Most popular</span>}
                <h3>{plan.name}</h3>
                <div className="price">
                  {plan.price} <span>{plan.suffix}</span>
                </div>
                <p>{plan.copy}</p>
                <div className="plan-stats">
                  {plan.stats.map((stat) => {
                    const [value, ...label] = stat.split(" ");
                    return (
                      <span key={stat}>
                        <strong>{value}</strong>
                        {label.join(" ")}
                      </span>
                    );
                  })}
                </div>
                <ul className="feature-list">
                  {plan.features.map((feature) => (
                    <li key={feature}>{feature}</li>
                  ))}
                </ul>
                <Link className={`button ${plan.popular ? "solid" : ""}`} href="/auth?mode=signup">
                  {plan.cta}
                  <Check size={16} />
                </Link>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

