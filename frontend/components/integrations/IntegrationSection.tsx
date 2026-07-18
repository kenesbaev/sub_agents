import type { ReactNode } from "react";

export function IntegrationSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="integration-section" aria-labelledby={`integration-${title.toLowerCase().replace(/\s+/g, "-")}`}>
      <h2 id={`integration-${title.toLowerCase().replace(/\s+/g, "-")}`}>{title}</h2>
      <div className="integration-grid">{children}</div>
    </section>
  );
}
