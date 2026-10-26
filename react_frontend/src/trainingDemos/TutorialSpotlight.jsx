import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { createPortal } from "react-dom";
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
  onNext,
  nextDisabled = false,
  nextLabel = "Next",
  allowTargetInteraction = false,
  nonBlocking = false,
  onFocusTarget,
  onExplore,
}) {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    if (!enabled || !allowTargetInteraction || nonBlocking || !target) return undefined;
    const guard = (event) => {
      const highlighted = document.querySelector(`[data-tutorial-id="${target}"]`);
      const tooltip = document.querySelector(`[data-atlas-tutorial-tooltip="true"]`);
      if (highlighted?.contains(event.target) || tooltip?.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    document.addEventListener("pointerdown", guard, true);
    document.addEventListener("click", guard, true);
    return () => {
      document.removeEventListener("pointerdown", guard, true);
      document.removeEventListener("click", guard, true);
    };
  }, [enabled, allowTargetInteraction, nonBlocking, target]);

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

  return createPortal(
    <>
      <div className={styles.blocker} style={{ pointerEvents: nonBlocking || allowTargetInteraction ? "none" : "auto",  top: 0, left: 0, right: 0, height: rect.top }} />
      <div className={styles.blocker} style={{ pointerEvents: nonBlocking || allowTargetInteraction ? "none" : "auto", top: rect.top, left: 0, width: rect.left, height: rect.height }} />
      <div className={styles.blocker} style={{ pointerEvents: nonBlocking || allowTargetInteraction ? "none" : "auto", top: rect.top, left: rect.right, right: 0, height: rect.height }} />
      <div className={styles.blocker} style={{ pointerEvents: nonBlocking || allowTargetInteraction ? "none" : "auto", top: rect.bottom, left: 0, right: 0, bottom: 0 }} />

      <div
        className={styles.spotlight}
        style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
      />

      <aside data-atlas-tutorial-tooltip="true" className={styles.tooltip} style={tooltipStyle}>
        <div className={styles.tooltipTop}>
          <span>GUIDE · STEP {step} OF {totalSteps}</span>
          {onSkip && <button type="button" onClick={onSkip} aria-label="Skip tutorial"><X size={15} /></button>}
        </div>
        <strong>{title}</strong>
        {onFocusTarget && <button type="button" onClick={onFocusTarget} style={{marginTop:8,padding:"6px 10px",border:"1px solid #a6c9dd",borderRadius:7,background:"#edf7fc",color:"#194765",cursor:"pointer",fontWeight:650}}>Click to edit highlighted field</button>}
        <p>{text}</p>
        {onNext ? <div style={{marginTop:12,display:"flex",alignItems:"center",gap:12}}><button type="button" disabled={nextDisabled} onClick={onNext} style={{border:0,borderRadius:18,padding:"8px 18px",background:"#1b5275",color:"white",fontWeight:700,opacity:nextDisabled?.45:1,cursor:nextDisabled?"not-allowed":"pointer"}}>{nextLabel} →</button>{nextDisabled && <span style={{fontSize:12}}>Complete the highlighted action first</span>}</div> : <div className={styles.hint}>Click the highlighted area to continue</div>}
        {onExplore && <div style={{marginTop:13,paddingTop:14,borderTop:"1px solid #dce7ef"}}><button type="button" onClick={onExplore} style={{padding:0,border:0,background:"transparent",color:"#286b9a",fontSize:14,fontWeight:750,cursor:"pointer",textDecoration:"underline",textUnderlineOffset:3}}>or explore this step</button></div>}
      </aside>
    </>,
    document.body
  );
}
