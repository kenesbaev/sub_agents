"use client";

import Image from "next/image";
import Link from "next/link";
import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";

import styles from "./how-it-works-section.module.css";

type HowItWorksStep = {
  number: string;
  title: string;
  description: string;
  image: string;
  alt: string;
};

const steps: HowItWorksStep[] = [
  {
    number: "01",
    title: "Connect your tools",
    description: "Connect the tools your business already uses.",
    image: "/images/how-it-works/connect-tools.webp",
    alt: "Isometric Teamora AI integration hub connected to business tools",
  },
  {
    number: "02",
    title: "Build your AI team",
    description: "Choose specialized AI teammates for every workflow.",
    image: "/images/how-it-works/build-team.webp",
    alt: "Isometric Teamora AI office with friendly coordinator and specialist agents",
  },
  {
    number: "03",
    title: "Delegate and track",
    description: "Assign work and follow every result in one place.",
    image: "/images/how-it-works/delegate-track.webp",
    alt: "Isometric AI agent tracking tasks and performance on a dashboard",
  },
];

/**
 * A self-contained landing section. The observer only adds a visual state; all
 * content stays present and accessible when JavaScript or motion is disabled.
 */
export function HowItWorksSection() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [animationReady, setAnimationReady] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section || typeof window === "undefined") return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion || !("IntersectionObserver" in window)) {
      setIsVisible(true);
      return;
    }

    setAnimationReady(true);
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        setIsVisible(true);
        observer.disconnect();
      },
      { threshold: 0.16 },
    );

    observer.observe(section);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      id="how-it-works"
      ref={sectionRef}
      className={styles.section}
      data-animated={animationReady ? "true" : undefined}
      data-visible={isVisible ? "true" : undefined}
      aria-labelledby="how-it-works-title"
    >
      <div className={styles.inner}>
        <div className={styles.heading}>
          <p className={styles.eyebrow}>How it works</p>
          <h2 id="how-it-works-title">
            Three simple steps to your <span>AI team</span>
          </h2>
        </div>

        <div className={styles.flow}>
          {steps.map((step, index) => (
            <div className={styles.flowItem} key={step.number}>
              <article className={styles.card} style={{ "--step-index": index } as CSSProperties}>
                <span className={styles.number} aria-label={`Step ${step.number}`}>
                  {step.number}
                </span>
                <div className={styles.artwork}>
                  <Image
                    src={step.image}
                    alt={step.alt}
                    fill
                    sizes="(max-width: 760px) calc(100vw - 48px), (max-width: 1100px) min(46vw, 430px), 31vw"
                  />
                </div>
                <div className={styles.cardCopy}>
                  <h3>{step.title}</h3>
                  <p>{step.description}</p>
                </div>
              </article>
              {index < steps.length - 1 ? <span className={styles.connector} aria-hidden="true" /> : null}
            </div>
          ))}
        </div>

        <Link className={styles.action} href="/office/index.html">
          See Teamora in action
          <span aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  );
}
