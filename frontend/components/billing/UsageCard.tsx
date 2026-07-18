import type { LucideIcon } from "lucide-react";

export function UsageCard({ icon: Icon, label, value, detail, tone = "violet" }: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  detail?: string;
  tone?: "violet" | "blue" | "green";
}) {
  return (
    <article className="usage-card">
      <span className={`usage-icon ${tone}`}><Icon size={23} strokeWidth={2} /></span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        {detail ? <small>{detail}</small> : null}
      </div>
    </article>
  );
}
