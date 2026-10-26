import { ArrowRight, Database, FileSignature, GraduationCap, ShieldCheck } from "lucide-react";
import styles from "./HomeDashboard.module.css";

const MODULES = [
  {
    key: "contracts", title: "Contracts",
    description: "Upload, manage, and retrieve trial agreements and contract versions.",
    icon: FileSignature,
  },
  {
    key: "regulatory", title: "Regulatory",
    description: "Organize regulatory documents with complete version histories and activity records.",
    icon: ShieldCheck,
  },
  {
    key: "site-training", title: "Site Initiation & Training",
    description: "Coordinate site onboarding, protocol orientation, and study training.",
    icon: GraduationCap,
  },
  {
    key: "data-capture", title: "Data Capture & Monitoring",
    description: "Prepare, de-identify, validate, monitor, and review clinical trial data.",
    icon: Database,
  },
];

export default function TrialHome({ onNavigate }) {
  return (
    <div>
      <div className={styles.topRow}>
        <section className={styles.heading}>
          <span>ATLAS CLINICAL TRIAL PLATFORM</span>
          <h1>Clinical trial workspace</h1>
          <p>Select a module to manage trial operations and research data.</p>
        </section>
      </div>
      <section className={styles.grid} style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        {MODULES.map(module => {
          const Icon = module.icon;
          return (
            <article className={styles.card} key={module.key}>
              <div className={styles.icon}><Icon size={29} strokeWidth={1.8} /></div>
              <h2>{module.title}</h2>
              <p>{module.description}</p>
              <button type="button" onClick={() => onNavigate(module.key)}>
                <span>Open {module.title}</span><ArrowRight size={17} />
              </button>
            </article>
          );
        })}
      </section>
    </div>
  );
}
