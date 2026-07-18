"use client";

import { ChevronDown, LogOut, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type AccountMenuProps = {
  displayName: string;
  planLabel: string;
  avatarUrl?: string | null;
  onProfile: () => void;
  onSignOut: () => void | Promise<void>;
};

export function AccountMenu({ displayName, planLabel, avatarUrl, onProfile, onSignOut }: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className={`account-menu${open ? " open" : ""}`} ref={rootRef}>
      <div className="account-popover" role="menu" aria-hidden={!open}>
        <button
          type="button"
          role="menuitem"
          tabIndex={open ? 0 : -1}
          onClick={() => {
            setOpen(false);
            onProfile();
          }}
        >
          <UserRound size={16} />
          Profile
        </button>
        <button
          className="account-signout"
          type="button"
          role="menuitem"
          tabIndex={open ? 0 : -1}
          onClick={() => void onSignOut()}
        >
          <LogOut size={16} />
          Sign out
        </button>
      </div>
      <button
        className="account-button sidebar-account-card"
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${displayName}, ${planLabel}`}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="account-avatar">
          {avatarUrl ? <img src={avatarUrl} alt="" /> : displayName.slice(0, 1).toUpperCase()}
        </span>
        <span className="account-copy">
          <strong>{displayName}</strong>
          <small>{planLabel}</small>
        </span>
        <ChevronDown className="account-chevron" size={15} aria-hidden="true" />
      </button>
    </div>
  );
}
