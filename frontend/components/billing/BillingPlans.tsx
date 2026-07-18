"use client";

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";

import { DashboardLayout } from "@/components/dashboard/DashboardLayout";
import { Sidebar, type DashboardNavView } from "@/components/dashboard/Sidebar";
import type { DashboardSettingsTab } from "@/components/dashboard/SettingsDropdown";

import { PaymentStatusCard } from "./PaymentStatusCard";
import { PlanCard, type BillingPlan } from "./PlanCard";

type BillingCycle = "monthly" | "yearly";
type PricingUser = { email: string; first_name: string | null; last_name: string | null; avatar_url: string | null };
type PricingBilling = { plan: { code: string; name: string } | null; canUpgrade: boolean };

const plans = {
  start: {
    key: "start",
    name: "Start",
    monthlyPrice: "$29",
    yearlyPrice: "$23",
    description: "For founders and small teams starting with an AI office.",
    stats: ["1 workspace", "5 agents", "50k credits"],
    features: ["Coordinator AI", "Shared chat + task history", "Telegram integration", "Activity log"],
    cta: "Request Start",
  },
  plus: {
    key: "plus",
    name: "Plus",
    monthlyPrice: "$149",
    yearlyPrice: "$119",
    description: "For SMBs that want AI agents across sales, support and marketing.",
    stats: ["3 teams", "15 agents", "500k credits"],
    features: ["AI Teams workspace", "Activity log and approvals", "Advanced integrations", "Custom agent instructions", "Priority email support"],
    cta: "Request Plus",
    popular: true,
  },
  pro: {
    key: "pro",
    name: "Pro",
    monthlyPrice: "$399",
    yearlyPrice: "$319",
    description: "For agencies and operators managing AI work for multiple clients.",
    stats: ["10 clients", "40 agents", "2M credits"],
    features: ["Client workspaces", "Reusable AI team templates", "Advanced controls", "Role-based permissions", "Priority support"],
    cta: "Request Pro",
  },
  custom: {
    key: "custom",
    name: "Enterprise",
    monthlyPrice: "Custom",
    description: "For companies that need custom AI teams, security and onboarding.",
    stats: ["Custom teams", "SLA support", "SSO ready"],
    features: ["Dedicated success manager", "Custom integrations", "Private deployment options", "Advanced security and compliance", "Custom onboarding"],
    cta: "Contact sales",
    enterprise: true,
  },
} as const;

export function BillingPlans() {
  const [cycle, setCycle] = useState<BillingCycle>("monthly");
  const [user, setUser] = useState<PricingUser | null>(null);
  const [billing, setBilling] = useState<PricingBilling | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    fetch("/api/auth/me", { credentials: "include" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => setUser(payload?.user || null))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
    fetch("/api/billing/status", { credentials: "include" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => setBilling(payload && typeof payload.canUpgrade === "boolean" ? payload : null))
      .catch(() => setBilling(null));
  }, []);

  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "Guest";
  const planLabel = user ? billing?.plan?.name || "No plan" : "Sign in to manage billing";
  const cards: BillingPlan[] = Object.values(plans).map((plan) => {
    const enterprise = "enterprise" in plan && plan.enterprise;
    const popular = "popular" in plan && plan.popular;
    const yearlyPrice = "yearlyPrice" in plan ? plan.yearlyPrice : undefined;
    return {
      key: plan.key,
      name: plan.name,
      price: enterprise ? plan.monthlyPrice : cycle === "yearly" && yearlyPrice ? yearlyPrice : plan.monthlyPrice,
      period: enterprise ? undefined : cycle === "yearly" ? "/ month, billed yearly" : "/ month",
      description: plan.description,
      stats: [...plan.stats],
      features: [...plan.features],
      cta: plan.cta,
      popular,
      enterprise,
    };
  });

  function navigate(view: DashboardNavView) {
    window.location.href = `/dashboard?view=${encodeURIComponent(view)}`;
  }

  function selectSettings(tab: DashboardSettingsTab) {
    window.location.href = `/dashboard?view=settings&tab=${encodeURIComponent(tab)}`;
  }

  async function signOut() {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } finally {
      for (const storage of [window.sessionStorage, window.localStorage]) {
        for (let index = storage.length - 1; index >= 0; index -= 1) {
          const key = storage.key(index);
          if (key?.startsWith("rebly-dashboard-") || key?.startsWith("rebly-office-") || key?.startsWith("rebly-team-conversations-")) {
            storage.removeItem(key);
          }
        }
      }
      window.location.href = "/";
    }
  }

  return (
    <DashboardLayout
      collapsed={collapsed}
      mobileOpen={mobileOpen}
      onMobileToggle={() => setMobileOpen((current) => !current)}
      sidebar={(
        <Sidebar
          activeView={null}
          settingsTab="billing"
          collapsed={collapsed}
          canUpgrade={false}
          displayName={displayName}
          planLabel={planLabel}
          avatarUrl={user?.avatar_url}
          authenticated={authChecked && Boolean(user)}
          onCollapse={() => setCollapsed((current) => !current)}
          onNavigate={navigate}
          onSelectSettings={selectSettings}
          onSignOut={signOut}
        />
      )}
    >
      <div className="billing-plans-page">
        <header className="billing-plans-head">
          <div className="page-heading">
            <h1>Billing</h1>
            <p>Choose the plan that fits your team's needs.</p>
          </div>
          <div className="billing-cycle-control" role="group" aria-label="Billing frequency">
            <button className={cycle === "monthly" ? "active" : ""} type="button" onClick={() => setCycle("monthly")}>Monthly</button>
            <button className={cycle === "yearly" ? "active" : ""} type="button" onClick={() => setCycle("yearly")}>Yearly · save 20%</button>
          </div>
          <button className="secondary-button" type="button" onClick={() => user ? selectSettings("billing") : window.location.assign("/auth?mode=login")}>
            <BarChart3 size={16} /> Plan &amp; Usage
          </button>
        </header>
        <div className="billing-plans-grid">{cards.map((plan) => <PlanCard plan={plan} key={plan.key} />)}</div>
        <PaymentStatusCard authenticated={Boolean(user)} planName={billing?.plan?.name} />
      </div>
    </DashboardLayout>
  );
}
