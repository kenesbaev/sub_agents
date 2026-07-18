import { CreditCard } from "lucide-react";

export function PaymentStatusCard({ authenticated, planName }: { authenticated: boolean; planName?: string }) {
  const title = !authenticated ? "Sign in to view billing status" : planName ? `${planName} plan assigned` : "No plan selected";
  const description = !authenticated
    ? "Pricing is public. Sign in to view the plan assigned to your Teamora workspace."
    : planName
      ? "Your workspace plan is confirmed. Payment-account details are not exposed by the current billing status API."
      : "Choose a plan above and contact the billing team to arrange payment securely.";
  return (
    <section className="payment-status-card">
      <span className="payment-status-icon"><CreditCard size={22} /></span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <span className={`payment-status-badge${planName ? " active" : ""}`}>{planName || (authenticated ? "No plan" : "Public pricing")}</span>
    </section>
  );
}
