import { useState } from "react";
import { BookOpen, CheckCircle2, ExternalLink, ClipboardList } from "lucide-react";
import styles from "./TrialDocuments.module.css";

const MODULES = [
  ["Site activation", "Confirm site contacts, study readiness, and initiation requirements."],
  ["Protocol orientation", "Review study objectives, eligibility, visits, and deviations."],
  ["Data capture training", "Learn imaging, electrophysiology, metadata and patient review workflows."],
  ["Data quality and monitoring", "Review validation, de-identification and issue resolution procedures."]
];

export default function SiteTraining({ onNavigate }) {
  const [done, setDone] = useState({});
  return <section className={styles.page}>
    <div className={styles.heading}>
      <span className={styles.eyebrow}>CLINICAL TRIAL OPERATIONS</span>
      <h1>Site Initiation & Training</h1>
      <p>Site onboarding and training coordination, based on the established CoCANoT workflows.</p>
    </div>
    {MODULES.map(([title, description], index) => <div className={styles.card} key={title}>
      <div style={{display:"flex",gap:14,alignItems:"center"}}>
        {done[index] ? <CheckCircle2 color="#248450" size={25}/> : <BookOpen color="#2c6899" size={25}/>}
        <div style={{flex:1}}><h3>{index+1}. {title}</h3><p>{description}</p></div>
        <label style={{fontSize:13,display:"flex",gap:8,alignItems:"center"}}>
          <input type="checkbox" checked={Boolean(done[index])}
            onChange={event=>setDone(current=>({...current,[index]:event.target.checked}))}/> Reviewed
        </label>
      </div>
    </div>)}
    <div className={styles.card}>
      <h2>Existing data workflow training</h2>
      <p>Open the operational modules for hands-on practice.</p>
      <button className={styles.historyButton} onClick={()=>onNavigate("data-capture")}>
        <ClipboardList size={17}/> Open Data Capture & Monitoring
      </button>
    </div>
  </section>;
}
