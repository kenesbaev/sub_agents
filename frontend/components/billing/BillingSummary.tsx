import Link from "next/link";
import { Bot, Building2, CreditCard, UsersRound, Zap } from "lucide-react";

import { UsageCard } from "./UsageCard";

type BillingSummaryProps = {
  planName: string;
  planCode?: string;
  roleLabel: string;
  loading?: boolean;
  error?: string;
  teams: number | null;
  agents: number | null;
};

export function BillingSummary({ planName, planCode, roleLabel, loading = false, error, teams, agents }: BillingSummaryProps) {
  const hasPlan = Boolean(planCode);
  return (
    <section className="billing-page dashboard-view" aria-labelledby="billing-title">
      <header className="page-heading">
        <h1 id="billing-title">Billing</h1>
        <p>Current plan, credits, and payment settings.</p>
      </header>

      <article className="billing-summary-card">
        <div className="billing-plan-row">
          <div>
            <span className="billing-kicker">Current plan</span>
            <div className="billing-plan-name">
              <span className="billing-plan-icon"><Building2 size={26} /></span>
              <div>
                <h2>{loading ? "Loading plan..." : planName}</h2>
                <p>{hasPlan ? `${roleLabel} workspace access is active.` : "Choose a plan to activate billing and workspace allowances."}</p>
              </div>
            </div>
          </div>
          <Link className="primary-button billing-manage-button" href="/pricing">
            <CreditCard size={17} /> Manage Billing
          </Link>
        </div>

        <div className="billing-credit-row">
          <span className="billing-kicker">Teamora credits</span>
          <strong>{hasPlan ? "Not reported" : "No active allowance"}</strong>
          <small>{hasPlan ? "Credit usage will appear when it is available from billing." : "Choose a plan to receive a workspace allowance."}</small>
        </div>

        {error ? <p className="billing-error" role="alert">{error}. You can still review available plans.</p> : null}

        <div className="usage-grid">
          <UsageCard icon={UsersRound} label="Teams" value={teams ?? "—"} detail={teams === null ? "Workspace usage unavailable" : "Loaded in this workspace"} />
          <UsageCard icon={Bot} label="Agents" value={agents ?? "—"} detail={agents === null ? "Workspace usage unavailable" : "Across loaded teams"} tone="blue" />
          <UsageCard icon={Zap} label="Operator" value="Not reported" detail="Not exposed by billing status" tone="green" />
        </div>
      </article>
    </section>
  );
}
