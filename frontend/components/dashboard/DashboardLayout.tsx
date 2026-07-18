"use client";

import { Menu, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

type DashboardLayoutProps = {
  sidebar: ReactNode;
  children: ReactNode;
  collapsed?: boolean;
  mobileOpen?: boolean;
  officeMode?: boolean;
  onMobileToggle?: () => void;
};

export function DashboardLayout({
  sidebar,
  children,
  collapsed = false,
  mobileOpen = false,
  officeMode = false,
  onMobileToggle,
}: DashboardLayoutProps) {
  const rootRef = useRef<HTMLElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const onMobileToggleRef = useRef(onMobileToggle);

  useEffect(() => {
    onMobileToggleRef.current = onMobileToggle;
  }, [onMobileToggle]);

  useEffect(() => {
    if (!mobileOpen) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const sidebarElement = rootRef.current?.querySelector<HTMLElement>(".sidebar");
    const focusable = Array.from(sidebarElement?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) || []);
    focusable[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onMobileToggleRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      (previouslyFocused || menuButtonRef.current)?.focus();
    };
  }, [mobileOpen]);

  return (
    <main
      ref={rootRef}
      className={`dashboard${collapsed ? " sidebar-collapsed" : ""}${mobileOpen ? " mobile-sidebar-open" : ""}`}
    >
      {sidebar}
      <button
        ref={menuButtonRef}
        className="mobile-menu-button"
        type="button"
        aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
        aria-expanded={mobileOpen}
        aria-controls="dashboard-sidebar"
        onClick={onMobileToggle}
      >
        {mobileOpen ? <X size={20} /> : <Menu size={20} />}
      </button>
      <button
        className="mobile-sidebar-backdrop"
        type="button"
        aria-label="Close navigation"
        onClick={onMobileToggle}
      />
      <section className={`dash-main${officeMode ? " dash-main-office" : ""}`}>{children}</section>
    </main>
  );
}
