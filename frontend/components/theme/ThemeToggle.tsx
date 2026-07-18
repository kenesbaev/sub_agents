"use client";

import { Moon, Sun } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import styles from "./theme-toggle.module.css";

export type TeamoraTheme = "light" | "dark";

const THEME_STORAGE_KEY = "rebly-theme";
const THEME_CHANGE_EVENT = "teamora-theme-change";

function currentDocumentTheme(): TeamoraTheme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function applyDocumentTheme(theme: TeamoraTheme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The visual preference still applies when storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent<TeamoraTheme>(THEME_CHANGE_EVENT, { detail: theme }));
}

export function useTeamoraTheme() {
  const [theme, setThemeState] = useState<TeamoraTheme>("dark");

  useEffect(() => {
    const syncTheme = () => setThemeState(currentDocumentTheme());
    const handleStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) syncTheme();
    };

    syncTheme();
    window.addEventListener(THEME_CHANGE_EVENT, syncTheme);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(THEME_CHANGE_EVENT, syncTheme);
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  const setTheme = useCallback((nextTheme: TeamoraTheme) => {
    applyDocumentTheme(nextTheme);
    setThemeState(nextTheme);
  }, []);

  return { theme, setTheme };
}

type ThemeToggleProps = {
  className?: string;
  labelled?: boolean;
};

export function ThemeToggle({ className = "", labelled = false }: ThemeToggleProps) {
  const { theme, setTheme } = useTeamoraTheme();

  return (
    <div
      className={`${styles.toggle}${labelled ? ` ${styles.labelled}` : ""}${className ? ` ${className}` : ""}`}
      role="group"
      aria-label="Color theme"
    >
      <button
        className={theme === "light" ? styles.active : ""}
        type="button"
        aria-label="Use light cosmic theme"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
      >
        <Sun size={labelled ? 20 : 17} aria-hidden="true" />
        {labelled ? <span><strong>Light</strong><small>White cosmic workspace</small></span> : null}
      </button>
      <button
        className={theme === "dark" ? styles.active : ""}
        type="button"
        aria-label="Use dark cosmic theme"
        aria-pressed={theme === "dark"}
        onClick={() => setTheme("dark")}
      >
        <Moon size={labelled ? 20 : 17} aria-hidden="true" />
        {labelled ? <span><strong>Dark</strong><small>Deep cosmic workspace</small></span> : null}
      </button>
    </div>
  );
}
