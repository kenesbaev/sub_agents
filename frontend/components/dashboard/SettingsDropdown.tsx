"use client";

import { ChevronDown, CreditCard, Plug, Settings, UserRound } from "lucide-react";

export type DashboardSettingsTab = "profile" | "billing" | "connected";

type SettingsDropdownProps = {
  open: boolean;
  active: boolean;
  activeTab: DashboardSettingsTab;
  onToggle: () => void;
  onSelect: (tab: DashboardSettingsTab) => void;
};

const items = [
  { id: "profile" as const, label: "Profile", icon: UserRound },
  { id: "billing" as const, label: "Billing", icon: CreditCard },
  { id: "connected" as const, label: "Connected Apps", icon: Plug },
];

export function SettingsDropdown({ open, active, activeTab, onToggle, onSelect }: SettingsDropdownProps) {
  return (
    <div className={`settings-dropdown${open ? " open" : ""}`}>
      <button
        className={`side-link settings-dropdown-trigger${active ? " active" : ""}`}
        type="button"
        title="Settings"
        aria-expanded={open}
        aria-controls="dashboard-settings-menu"
        onClick={onToggle}
      >
        <Settings size={18} strokeWidth={2} aria-hidden="true" />
        <span className="side-link-label">Settings</span>
        <ChevronDown className="settings-chevron" size={15} aria-hidden="true" />
      </button>
      <div id="dashboard-settings-menu" className="settings-dropdown-menu" aria-hidden={!open}>
        <div className="settings-dropdown-inner">
          {items.map((item) => {
            const Icon = item.icon;
            const selected = active && activeTab === item.id;
            return (
              <button
                className={`settings-nested-link${selected ? " active" : ""}`}
                type="button"
                key={item.id}
                tabIndex={open ? 0 : -1}
                aria-current={selected ? "page" : undefined}
                onClick={() => onSelect(item.id)}
              >
                <Icon size={16} strokeWidth={2} aria-hidden="true" />
                <span>{item.label}</span>
                {selected ? <i aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
