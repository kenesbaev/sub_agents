import { Check, Headphones } from "lucide-react";

export type BillingPlan = {
  key: "start" | "plus" | "pro" | "custom";
  name: string;
  price: string;
  period?: string;
  description: string;
  stats: string[];
  features: string[];
  cta: string;
  popular?: boolean;
  enterprise?: boolean;
};

export function PlanCard({ plan }: { plan: BillingPlan }) {
  const subject = encodeURIComponent(`Teamora AI ${plan.name} plan request`);
  return (
    <article className={`plan-card${plan.popular ? " popular" : ""}`}>
      {plan.popular ? <span className="popular-badge">Most popular</span> : null}
      <div className="plan-card-head">
        <h2>{plan.name}</h2>
        <p>{plan.description}</p>
        <div className="plan-price">
          <strong>{plan.price}</strong>
          {plan.period ? <span>{plan.period}</span> : null}
        </div>
      </div>
      <div className="plan-stats">
        {plan.stats.map((stat) => <span key={stat}>{stat}</span>)}
      </div>
      <ul>
        {plan.features.map((feature) => (
          <li key={feature}><Check size={15} strokeWidth={2.6} /><span>{feature}</span></li>
        ))}
      </ul>
      <a className={`plan-cta${plan.popular ? " primary" : ""}`} href={`mailto:sales@teamorai.uz?subject=${subject}`}>
        {plan.enterprise ? <Headphones size={16} /> : null}
        {plan.cta}
      </a>
    </article>
  );
}
