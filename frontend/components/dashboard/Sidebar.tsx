"use client";

import Link from "next/link";
import {
  BriefcaseBusiness,
  ChevronDown,
  CreditCard,
  LifeBuoy,
  LogIn,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  UsersRound,
  Video,
} from "lucide-react";
import { useEffect, useState } from "react";

import { AccountMenu } from "./AccountMenu";
import { SettingsDropdown, type DashboardSettingsTab } from "./SettingsDropdown";
import { SidebarItem } from "./SidebarItem";

export type DashboardNavView = "office" | "youtube-growth" | "my-teams" | "settings" | "support";

type SidebarProps = {
  activeView: DashboardNavView | null;
  settingsTab: DashboardSettingsTab;
  collapsed: boolean;
  canUpgrade: boolean;
  displayName: string;
  planLabel: string;
  avatarUrl?: string | null;
  authenticated?: boolean;
  onCollapse: () => void;
  onNavigate: (view: DashboardNavView) => void;
  onSelectSettings: (tab: DashboardSettingsTab) => void;
  onSignOut: () => void | Promise<void>;
};

export function Sidebar({
  activeView,
  settingsTab,
  collapsed,
  canUpgrade,
  displayName,
  planLabel,
  avatarUrl,
  authenticated = true,
  onCollapse,
  onNavigate,
  onSelectSettings,
  onSignOut,
}: SidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(activeView === "settings");

  useEffect(() => {
    setSettingsOpen(activeView === "settings");
  }, [activeView]);

  function navigate(view: DashboardNavView) {
    if (view !== "settings") setSettingsOpen(false);
    onNavigate(view);
  }

  function toggleSettings() {
    if (collapsed) {
      onCollapse();
      setSettingsOpen(true);
      return;
    }
    setSettingsOpen((current) => !current);
  }

  return (
    <aside id="dashboard-sidebar" className={`sidebar${collapsed ? " collapsed" : ""}`} aria-label="Workspace sidebar">
      <div className="sidebar-top">
        <Link className="dash-brand" href="/" aria-label="Teamora AI home">
          <img className="dash-logo" src="/images/teamora-dashboard-logo.svg" alt="" />
          <span>Teamora <b>AI</b></span>
        </Link>
        <button
          className="sidebar-toggle"
          type="button"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          onClick={onCollapse}
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      <button className="new-team-button" type="button" onClick={() => navigate("my-teams")}>
        <Plus size={19} aria-hidden="true" />
        <span>New Team</span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>

      <nav className="side-nav" aria-label="Workspace">
        <SidebarItem
          icon={BriefcaseBusiness}
          label="Office"
          active={activeView === "office"}
          onClick={() => navigate("office")}
        />
        <SidebarItem
          icon={Video}
          label="YouTube Growth"
          active={activeView === "youtube-growth"}
          onClick={() => navigate("youtube-growth")}
        />
        <SidebarItem
          icon={UsersRound}
          label="Your teams"
          active={activeView === "my-teams"}
          onClick={() => navigate("my-teams")}
        />
      </nav>

      <div className="sidebar-settings">
        <SettingsDropdown
          open={settingsOpen && !collapsed}
          active={activeView === "settings"}
          activeTab={settingsTab}
          onToggle={toggleSettings}
          onSelect={onSelectSettings}
        />
      </div>

      <div className="sidebar-bottom">
        {canUpgrade ? (
          <Link className="side-link sidebar-upgrade-link" href="/pricing" title="Upgrade">
            <CreditCard size={18} strokeWidth={2} aria-hidden="true" />
            <span className="side-link-label">Upgrade</span>
          </Link>
        ) : null}
        <SidebarItem
          icon={LifeBuoy}
          label="Support"
          active={activeView === "support"}
          onClick={() => navigate("support")}
        />
        {authenticated ? (
          <AccountMenu
            displayName={displayName}
            planLabel={planLabel}
            avatarUrl={avatarUrl}
            onProfile={() => onSelectSettings("profile")}
            onSignOut={onSignOut}
          />
        ) : (
          <Link className="side-link sidebar-signin-link" href="/auth" title="Sign in">
            <LogIn size={18} strokeWidth={2} aria-hidden="true" />
            <span className="side-link-label">Sign in</span>
          </Link>
        )}
      </div>
    </aside>
  );
}
