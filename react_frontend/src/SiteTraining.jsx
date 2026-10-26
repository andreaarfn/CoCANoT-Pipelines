import { useEffect, useState } from "react";
import { Building2, ScrollText, Database, ChartNoAxesCombined, CheckCircle2, Brain, Activity, Users, ArrowLeft, BookOpen } from "lucide-react";
import { MemoryRouter } from "react-router-dom";
import ImagingDemo from "./trainingDemos/ImagingDemo";
import EphysDemo from "./trainingDemos/EphysDemo";
import PatientDemo from "./trainingDemos/PatientDemo";
import styles from "./TrialDocuments.module.css";
import "./trainingDemos/trainingUtilities.css";

const MODULES = [
  ["Site activation", "Confirm site contacts, study readiness, and initiation requirements.", Building2],
  ["Protocol orientation", "Review study objectives, eligibility, visits, and deviations.", ScrollText],
  ["Data capture training", "Learn imaging, electrophysiology, metadata and patient review workflows.", Database],
  ["Data quality and monitoring", "Review validation, de-identification and issue resolution procedures.", ChartNoAxesCombined],
];

const TUTORIALS = [
  ["imaging", "Imaging tutorial", "Explore the synthetic MRI processing and review workflow.", Brain, ImagingDemo],
  ["electrophysiology", "Electrophysiology tutorial", "Walk through EDF scrubbing, review, and BIDS preparation.", Activity, EphysDemo],
  ["patient", "Patient data review tutorial", "Explore linked synthetic clinical, surgical, imaging, and recording data.", Users, PatientDemo],
];

export default function SiteTraining({ initialTutorial = null, onExit = null }) {
  const [done, setDone] = useState({});
  const [active, setActive] = useState(initialTutorial);
  const [guided, setGuided] = useState(true);
  useEffect(() => {
    const listener = () => { if (onExit) onExit(); else setActive(null); };
    window.addEventListener("atlas-training-back", listener);
    return () => window.removeEventListener("atlas-training-back", listener);
  }, [onExit]);

  if (active) {
    const item = TUTORIALS.find(row => row[0] === active);
    const Demo = item[4];
    return <div style={{minWidth:0}}>
      <button type="button" onClick={() => onExit ? onExit() : setActive(null)} className={styles.historyButton} style={{marginBottom:16}}>
        <ArrowLeft size={17}/> Back to Site Initiation & Training
      </button>
      <MemoryRouter initialEntries={[{pathname:"/data/demo/"+active,state:{tutorialChoice:guided?"yes":"no"}}]}>
        <Demo key={active}/>
      </MemoryRouter>
    </div>;
  }
  return <section className={styles.page}>
    <div className={styles.heading}>
      <span className={styles.eyebrow}>CLINICAL TRIAL OPERATIONS</span>
      <h1>Site Initiation & Training</h1>
      <p>Site onboarding and guided CoCANoT workflow training.</p>
    </div>
    {MODULES.map(([title, description, Icon], index) => (
      <div className={styles.card} key={title}>
        <div style={{display:"flex",gap:14,alignItems:"center"}}>
          {done[index] ? <CheckCircle2 color="#248450" size={25}/> : <Icon color="#2c6899" size={25}/>}
          <div style={{flex:1}}><h3>{index+1}. {title}</h3><p>{description}</p></div>
          <label style={{fontSize:13,display:"flex",gap:8,alignItems:"center"}}>
            <input type="checkbox" checked={Boolean(done[index])}
              onChange={event=>setDone(current=>({...current,[index]:event.target.checked}))}/> Reviewed
          </label>
        </div>
      </div>
    ))}
    <div className={styles.sectionTitle}><h2>Interactive workflow tutorials</h2></div>
    <p>Practice safely with synthetic demonstration records. Tutorials do not change your local ATLAS patient database.</p>
    <label style={{display:"flex",alignItems:"center",gap:10,fontSize:13}}>
      <input type="checkbox" checked={guided} onChange={event=>setGuided(event.target.checked)}/>
      Start with guided step-by-step instructions
    </label>
    {TUTORIALS.map(([id,title,description,Icon]) => <div className={styles.card} key={id}>
      <div style={{display:"flex",alignItems:"center",gap:15}}>
        <Icon size={25} color="#28678e"/>
        <div style={{flex:1}}><h3>{title}</h3><p>{description}</p></div>
        <button type="button" className={styles.historyButton} onClick={()=>setActive(id)}>
          <BookOpen size={17}/> Start tutorial
        </button>
      </div>
    </div>)}
  </section>;
}
