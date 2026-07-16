"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import styles from "./page.module.css";

type IdleWindow = Window & {
  cancelIdleCallback?: (handle: number) => void;
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
};

const HERO_ORIGIN = typeof window === "undefined" ? "" : window.location.origin;

export function HeroOffice() {
  const mountRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [compact, setCompact] = useState<boolean | null>(null);
  const [inView, setInView] = useState(false);
  const [shouldLoad, setShouldLoad] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const postToScene = useCallback((message: Record<string, unknown>) => {
    frameRef.current?.contentWindow?.postMessage(message, HERO_ORIGIN);
  }, []);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 700px)");
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const target = mountRef.current;
    if (!target) return;

    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry.isIntersecting),
      { rootMargin: "240px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!inView || compact === null) return;

    const idleWindow = window as IdleWindow;
    const reveal = () => setShouldLoad(true);
    const idleHandle = idleWindow.requestIdleCallback?.(reveal, { timeout: 900 });
    const timeoutHandle = idleHandle === undefined ? window.setTimeout(reveal, 180) : undefined;

    return () => {
      if (idleHandle !== undefined) idleWindow.cancelIdleCallback?.(idleHandle);
      if (timeoutHandle !== undefined) window.clearTimeout(timeoutHandle);
    };
  }, [compact, inView]);

  useEffect(() => {
    if (!shouldLoad) return;
    postToScene({ type: "teamora-hero-visibility", visible: inView });
  }, [inView, postToScene, shouldLoad]);

  function sendParallax(event: React.PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, ((event.clientX - bounds.left) / bounds.width - 0.5) * 2));
    const y = Math.max(-1, Math.min(1, ((event.clientY - bounds.top) / bounds.height - 0.5) * 2));
    postToScene({ type: "teamora-hero-parallax", x, y });
  }

  return (
    <div
      ref={mountRef}
      className={styles.officeFrame}
      onPointerLeave={() => postToScene({ type: "teamora-hero-parallax", x: 0, y: 0 })}
      onPointerMove={sendParallax}
    >
      <div className={styles.officeAura} aria-hidden="true" />
      {shouldLoad ? (
        <iframe
          ref={frameRef}
          className={`${styles.officeScene} ${loaded ? styles.officeSceneLoaded : ""}`}
          src={`/office/hero.html?quality=${compact ? "low" : "high"}`}
          title="Teamora AI Office"
          aria-hidden="true"
          tabIndex={-1}
          loading="lazy"
          onLoad={() => {
            setLoaded(true);
            postToScene({ type: "teamora-hero-visibility", visible: inView });
          }}
        />
      ) : null}
      {!loaded ? <span className={styles.officeLoading}>Preparing your AI office</span> : null}

      <div className={styles.officeRoles} aria-hidden="true">
        <span className={`${styles.officeRole} ${styles.officeRoleCoordinator}`}>Coordinator</span>
        <span className={`${styles.officeRole} ${styles.officeRoleMarketing}`}>Marketing</span>
        <span className={`${styles.officeRole} ${styles.officeRoleSales}`}>Sales</span>
        <span className={`${styles.officeRole} ${styles.officeRoleResearch}`}>Research</span>
        <span className={`${styles.officeRole} ${styles.officeRoleSupport}`}>Support</span>
        <span className={`${styles.officeRole} ${styles.officeRoleAutomation}`}>Automation</span>
      </div>
    </div>
  );
}
