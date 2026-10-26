import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import styles from "./TutorialSpotlight.module.css";

const PAD = 8;
const GAP = 14;

export default function TutorialSpotlight({
  enabled = true,
  target,
  title,
  text,
  step,
  totalSteps,
  onSkip,
}) {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    if (!enabled || !target) {
      setRect(null);
      return undefined;
    }

    let frame = null;
    const selector = `[data-tutorial-id="${target}"]`;
    const element = document.querySelector(selector);

    const update = () => {
      const el = document.querySelector(selector);
      if (!el) {
        setRect(null);
        return;
      }
      const box = el.getBoundingClientRect();
      setRect({
        top: Math.max(8, box.top - PAD),
        left: Math.max(8, box.left - PAD),
        right: Math.min(window.innerWidth - 8, box.right + PAD),
        bottom: Math.min(window.innerHeight - 8, box.bottom + PAD),
        width: box.width + PAD * 2,
        height: box.height + PAD * 2,
      });
    };

    const schedule = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };

    element?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    const timer = window.setTimeout(update, 260);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);

    return () => {
      window.clearTimeout(timer);
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [enabled, target]);

  const tooltipStyle = useMemo(() => {
    if (!rect) return {};
    const width = Math.min(330, window.innerWidth - 32);
    const below = window.innerHeight - rect.bottom > 190 || rect.top < 210;
    let top = below ? rect.bottom + GAP : Math.max(12, rect.top - 185);
    let left = rect.left;
    if (left + width > window.innerWidth - 16) {
      left = Math.max(16, window.innerWidth - width - 16);
    }
    return { top, left, width };
  }, [rect]);

  if (!enabled || !rect) return null;

  return (
    <>
      <div className={styles.blocker} style={{ top: 0, left: 0, right: 0, height: rect.top }} />
      <div className={styles.blocker} style={{ top: rect.top, left: 0, width: rect.left, height: rect.height }} />
      <div className={styles.blocker} style={{ top: rect.top, left: rect.right, right: 0, height: rect.height }} />
      <div className={styles.blocker} style={{ top: rect.bottom, left: 0, right: 0, bottom: 0 }} />

      <div
        className={styles.spotlight}
        style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
      />

      <aside className={styles.tooltip} style={tooltipStyle}>
        <div className={styles.tooltipTop}>
          <span>GUIDE · STEP {step} OF {totalSteps}</span>
          <button type="button" onClick={onSkip} aria-label="Skip tutorial"><X size={15} /></button>
        </div>
        <strong>{title}</strong>
        <p>{text}</p>
        <div className={styles.hint}>Click the highlighted area to continue</div>
      </aside>
    </>
  );
}
