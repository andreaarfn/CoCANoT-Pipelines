import { ArrowLeft, Database, Video } from "lucide-react";
import styles from "./ElectrophysiologyDashboard.module.css";

export default function VideoHome({ onHome, onProcessVideos, onPatientReview }) {
  return (
    <div>
      <div className={styles.localTopbar}>
        <button className={styles.localBack} type="button" onClick={onHome}>
          <ArrowLeft size={16} />
          Home
        </button>
        <span className={styles.localBreadcrumbChevron}>›</span>
        <span className={styles.localBreadcrumbCurrent}>Video</span>
      </div>
      <header className={styles.pageHeading}>
        <span className={styles.eyebrow}>VIDEO PIPELINE</span>
        <h1>Prepare video data for research use</h1>
        <p>
          Import and process video recordings, censor identifying information,
          review the result, and export de-identified videos with CoCANoT metadata.
        </p>
      </header>
      <div className={styles.homeCards}>
        <button type="button" onClick={onProcessVideos}>
          <Video size={28} />
          <strong>Process video data</strong>
          <span>Open the complete video de-identification workflow.</span>
        </button>
        <button type="button" onClick={onPatientReview}>
          <Database size={28} />
          <strong>Review patient data</strong>
          <span>Review locally stored video recordings and metadata records by patient.</span>
        </button>
      </div>
    </div>
  );
}
