import { useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, RotateCcw } from "lucide-react";
import styles from "../TrialDocuments.module.css";

const steps = [
  { title: "Select a patient", description: "The metadata workflow begins by choosing an existing study patient or creating a new patient identifier.", prompt: "Select synthetic patient 001.", action: "Select patient 001", result: "Patient 001 selected." },
  { title: "Create a clinical assessment", description: "Clinical assessments are tracked longitudinally and associated with the patient and active metadata dictionary.", prompt: "Create a sample assessment for patient 001.", action: "Create assessment", result: "Synthetic Clinical Assessment 001 created." },
  { title: "Review metadata", description: "Verify identifiers, required dictionary fields, and linkages before saving or submitting.", prompt: "Review the example assessment.", action: "Review fields", result: "Patient ID 001 · Assessment ID 001 · Example status: reviewed." },
  { title: "Validate the assessment", description: "Validation checks completeness and field values. This tutorial does not write to your SQLite database.", prompt: "Validate the synthetic assessment.", action: "Validate sample", result: "Sample passed the tutorial checks." },
];

export default function MetadataTutorial({ onBack }) {
  const [step, setStep] = useState(0);
  const [completed, setCompleted] = useState(false);
  const item = steps[step];
  return <section className={styles.page}>
    <button type="button" className={styles.historyButton} onClick={onBack}><ArrowLeft size={16}/> Back to Data Capture & Monitoring</button>
    <div className={styles.heading}>
      <span className={styles.eyebrow}>SYNTHETIC TRAINING · STEP {step+1} OF {steps.length}</span>
      <h1>Metadata guided tutorial</h1>
      <p>Practice patient-level metadata workflows without changing stored research data.</p>
    </div>
    <div className={styles.card}>
      <h2>{item.title}</h2>
      <p>{item.description}</p>
      <p style={{fontWeight:700,marginTop:20}}>{item.prompt}</p>
      {completed ? <p style={{display:"flex",alignItems:"center",gap:8,color:"#17633d"}}><CheckCircle2 size={19}/>{item.result}</p> :
      <button type="button" className={styles.historyButton} onClick={()=>setCompleted(true)}>{item.action}</button>}
    </div>
    <div style={{display:"flex",gap:12,flexWrap:"wrap"}}>
      <button className={styles.historyButton} disabled={!completed} onClick={()=>{setStep(v=>(v+1)%steps.length);setCompleted(false)}}><ArrowRight size={16}/>{step===steps.length-1?"Restart tutorial":"Continue"}</button>
      <button className={styles.historyButton} onClick={()=>{setStep(0);setCompleted(false)}}><RotateCcw size={16}/> Reset</button>
    </div>
  </section>;
}
