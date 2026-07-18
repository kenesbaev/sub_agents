import type { LucideIcon } from "lucide-react";
import { ExternalLink } from "lucide-react";

export function SupportContactCard({ icon: Icon, title, description, action, href, external = false }: {
  icon: LucideIcon;
  title: string;
  description: string;
  action: string;
  href?: string;
  external?: boolean;
}) {
  return (
    <article className="support-contact-card">
      <span className="support-contact-icon"><Icon size={23} /></span>
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
        {href ? (
          <a href={href} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>
            {action}{external ? <ExternalLink size={14} /> : null}
          </a>
        ) : <span className="support-contact-unavailable" aria-disabled="true">{action}</span>}
      </div>
    </article>
  );
}
