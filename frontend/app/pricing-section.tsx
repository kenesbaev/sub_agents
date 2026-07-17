"use client";

import { ArrowRight, Check } from "lucide-react";
import { useState } from "react";

import styles from "./pricing-section.module.css";

type BillingCycle = "monthly" | "yearly";

type Plan = {
  key: "start" | "plus" | "pro" | "custom";
  name: string;
  monthlyPrice: string;
  yearlyPrice?: string;
  description: string;
  stats: string[];
  features: string[];
  cta: string;
  popular?: boolean;
  enterprise?: boolean;
};

const plans: Plan[] = [
  {
    key: "start",
    name: "Start",
    monthlyPrice: "$29",
    yearlyPrice: "$23",
    description: "For founders and small teams starting with an AI office.",
    stats: ["1 workspace", "5 agents", "50k credits"],
    features: ["Coordinator AI", "Shared chat + task history", "Telegram integration", "Activity log"],
    cta: "Request Start",
  },
  {
    key: "plus",
    name: "Plus",
    monthlyPrice: "$149",
    yearlyPrice: "$119",
    description: "For SMBs that want AI agents across sales, support and marketing.",
    stats: ["3 teams", "15 agents", "500k credits"],
    features: [
      "AI Teams workspace",
      "Activity log and approvals",
      "Advanced integrations",
      "Custom agent instructions",
      "Priority email support",
    ],
    cta: "Request Plus",
    popular: true,
  },
  {
    key: "pro",
    name: "Pro",
    monthlyPrice: "$399",
    yearlyPrice: "$319",
    description: "For agencies and operators managing AI work for multiple clients.",
    stats: ["10 clients", "40 agents", "2M credits"],
    features: [
      "Client workspaces",
      "Reusable AI team templates",
      "Advanced controls",
      "Role-based permissions",
      "Priority support",
    ],
    cta: "Request Pro",
  },
  {
    key: "custom",
    name: "Custom",
    monthlyPrice: "Custom",
    description: "For companies that need custom AI teams, security and onboarding.",
    stats: ["Custom teams", "SLA support", "SSO ready"],
    features: [
      "Dedicated success manager",
      "Custom integrations",
      "Private deployment options",
      "Advanced security and compliance",
      "Custom onboarding",
    ],
    cta: "Contact sales",
    enterprise: true,
  },
];

function PlanAction({ plan }: { plan: Plan }) {
  const subject = encodeURIComponent(`Teamora AI ${plan.name} plan request`);
  return (
    <a className={styles.cardAction} href={`mailto:sales@teamorai.uz?subject=${subject}`}>
      {plan.cta}
      <ArrowRight size={16} strokeWidth={2.25} aria-hidden="true" />
    </a>
  );
}

/**
 * Pricing presentation. Plan requests intentionally go to the billing team
 * until an authenticated checkout and webhook lifecycle are configured.
 */
export function PricingSection() {
  const [billingCycle, setBillingCycle] = useState<BillingCycle>("monthly");
  const isYearly = billingCycle === "yearly";

  return (
    <section className={styles.pricing} id="pricing" aria-labelledby="pricing-title">
      <div className={styles.inner}>
        <header className={styles.heading}>
          <p className={styles.eyebrow}>Pricing</p>
          <h2 id="pricing-title">
            An <span>AI team</span> that grows with you
          </h2>
          <p className={styles.description}>
            Choose the workspace capacity you need today and scale without rebuilding your AI office.
          </p>

          <div className={styles.billingControl} role="group" aria-label="Billing frequency">
            <button
              className={billingCycle === "monthly" ? styles.billingChoiceActive : styles.billingChoice}
              type="button"
              aria-pressed={billingCycle === "monthly"}
              onClick={() => setBillingCycle("monthly")}
            >
              Monthly
            </button>
            <button
              className={billingCycle === "yearly" ? styles.billingChoiceActive : styles.billingChoice}
              type="button"
              aria-pressed={billingCycle === "yearly"}
              onClick={() => setBillingCycle("yearly")}
            >
              Yearly
            </button>
            <span className={styles.saving}>Save 20%</span>
          </div>
          {isYearly ? <p className={styles.billingHint}>Yearly prices are shown per month, billed annually.</p> : null}
        </header>

        <div className={styles.cards}>
          {plans.map((plan) => {
            const price = isYearly && plan.yearlyPrice ? plan.yearlyPrice : plan.monthlyPrice;
            const priceLabel = plan.enterprise
              ? "Custom pricing"
              : `${price} per month${isYearly ? ", billed yearly" : ""}`;

            return (
              <article
                className={`${styles.card}${plan.popular ? ` ${styles.cardPopular}` : ""}`}
                key={plan.name}
                aria-labelledby={`plan-${plan.name.toLowerCase()}`}
              >
                <div className={styles.cardTop}>
                  <div className={styles.planNameRow}>
                    <h3 id={`plan-${plan.name.toLowerCase()}`}>{plan.name}</h3>
                    {plan.popular ? <span className={styles.popularBadge}>Most popular</span> : null}
                  </div>
                  <p className={styles.price} aria-label={priceLabel}>
                    {price}
                    {!plan.enterprise ? <span>/mo</span> : null}
                  </p>
                  <p className={styles.planDescription}>{plan.description}</p>
                </div>

                <div className={styles.stats} aria-label={`${plan.name} plan limits`}>
                  {plan.stats.map((stat) => <span key={stat}>{stat}</span>)}
                </div>

                <ul className={styles.features}>
                  {plan.features.map((feature) => (
                    <li key={feature}>
                      <Check size={15} strokeWidth={2.8} aria-hidden="true" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>

                <PlanAction plan={plan} />
              </article>
            );
          })}
        </div>

        <p className={styles.footnote}>
          <Check size={15} strokeWidth={2.5} aria-hidden="true" />
          Plan access is activated after confirmation from the Teamora billing team.
        </p>
      </div>
    </section>
  );
}
