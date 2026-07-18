"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

type SidebarItemProps = {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  disabled?: boolean;
  badge?: ReactNode;
  className?: string;
  onClick?: () => void;
};

export function SidebarItem({
  icon: Icon,
  label,
  active = false,
  disabled = false,
  badge,
  className = "",
  onClick,
}: SidebarItemProps) {
  return (
    <button
      className={`side-link${active ? " active" : ""}${className ? ` ${className}` : ""}`}
      type="button"
      title={label}
      aria-current={active ? "page" : undefined}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon size={18} strokeWidth={2} aria-hidden="true" />
      <span className="side-link-label">{label}</span>
      {badge ? <span className="side-link-badge">{badge}</span> : null}
    </button>
  );
}
