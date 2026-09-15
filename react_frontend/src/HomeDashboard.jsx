import {
  Activity,
  ArrowRight,
  Brain,
  FileText,
  Users,
} from "lucide-react";
import styles from "./HomeDashboard.module.css";

export default function HomeDashboard({ onNavigate }) {
  const cards = [
    {
      key: "imaging",
      title: "Imaging",
      description:
        "Prepare DICOM and NIfTI imaging data, scrub metadata, review defacing, and create BIDS datasets.",
      icon: Brain,
      button: "Open Imaging",
    },
    {
      key: "ephys",
      title: "Electrophysiology",
      description:
        "Select EDF recordings, scrub identifying header information, review results, and convert accepted recordings to BIDS.",
      icon: Activity,
      button: "Open Electrophysiology",
    },
    {
      key: "metadata-home",
      title: "Metadata",
      description:
        "Manage clinical, surgical, imaging, and electrophysiology metadata using the active CoCANoT dictionary.",
      icon: FileText,
      button: "Open Metadata",
    },
  ];

  return (
    <div>
      <section className={styles.heading}>
        <span>COCANOT PIPELINES</span>
        <h1>Data preparation workspace</h1>
        <p>
          De-identify, validate, review, and organize research
          data from one application.
        </p>
      </section>

      <section className={styles.grid}>
        {cards.map(card => {
          const Icon = card.icon;

          return (
            <article className={styles.card} key={card.key}>
              <div className={styles.icon}>
                <Icon size={29} strokeWidth={1.8} />
              </div>
              <h2>{card.title}</h2>
              <p>{card.description}</p>
              <button onClick={() => onNavigate(card.key)}>
                <span>{card.button}</span>
                <ArrowRight size={17} />
              </button>
            </article>
          );
        })}
      </section>

      <section className={styles.patientCard}>
        <div>
          <span>PATIENT DATA REVIEW</span>
          <h2>Review data across workflows</h2>
          <p>
            View stored records for each patient and move directly
            into Imaging or Electrophysiology when additional data
            need to be processed.
          </p>
        </div>
        <button onClick={() => onNavigate("patient-review")}>
          <Users size={18} />
          Review Patients
        </button>
      </section>
    </div>
  );
}
