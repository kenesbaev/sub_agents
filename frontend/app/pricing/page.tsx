import { BillingPlans } from "@/components/billing/BillingPlans";

export const metadata = {
  title: "Pricing | Teamora AI",
  description: "Start, Plus, Pro, and Custom workspace plans for Teamora AI.",
};

export default function PricingPage() {
  return <BillingPlans />;
}
