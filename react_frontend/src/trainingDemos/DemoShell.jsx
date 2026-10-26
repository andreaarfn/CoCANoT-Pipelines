import { ArrowLeft, RotateCcw, Sparkles } from "lucide-react";
import styles from "./DemoShell.module.css";

export default function DemoShell({
  title,
  subtitle,
  coachTitle,
  coachText,
  step,
  totalSteps,
  onReset,
  children,
}) {
  function returnToPlatformSection(event) {
    event.preventDefault();

    window.dispatchEvent(new Event("atlas-training-back"));
  }

  return (
    <main className={styles.page}>
      <div className={styles.container}>
        <div className={styles.topbar}>
          <a
            href="/data#cocanot-demo-section"
            className={styles.back}
            onClick={returnToPlatformSection}
          >
            <ArrowLeft size={16} />
            Back to Site Training
          </a>

          <button type="button" className={styles.reset} onClick={onReset}>
            <RotateCcw size={15} />
            Reset Demo
          </button>
        </div>

        <header className={styles.header}>
          <div>
            <span>COCANOT INTERACTIVE DEMO</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <strong>Synthetic data only</strong>
        </header>

        <section className={styles.coach}>
          <div className={styles.coachIcon}>
            <Sparkles size={18} />
          </div>

          <div>
            <div className={styles.coachMeta}>
              <span>GUIDE</span>
              {step && totalSteps ? (
                <span>
                  Step {step} of {totalSteps}
                </span>
              ) : null}
            </div>

            <strong>{coachTitle}</strong>
            <p>{coachText}</p>
          </div>
        </section>

        {children}
      </div>
    </main>
  );
}
