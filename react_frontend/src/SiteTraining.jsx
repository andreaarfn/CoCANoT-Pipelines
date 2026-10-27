import { useEffect, useState } from "react";
import { Building2, ScrollText, Database, ChartNoAxesCombined, CheckCircle2, Brain, Activity, Users, ArrowLeft, BookOpen, ChevronDown, ChevronUp } from "lucide-react";
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

export default function SiteTraining({ initialTutorial = null, onExit = null, experience = "research", onNavigate = null }) {
  const [done, setDone] = useState({});
  const [active, setActive] = useState(initialTutorial);
  const [guided, setGuided] = useState(true);
  const [tutorialsOpen, setTutorialsOpen] = useState(false);
  useEffect(() => {
    const listener = () => { if (onExit) onExit(); else setActive(null); };
    window.addEventListener("atlas-training-back", listener);
    return () => window.removeEventListener("atlas-training-back", listener);
  }, [onExit]);

  if (active) {
    const item = TUTORIALS.find(row => row[0] === active);
    if (!item || (experience !== "research" && active !== "patient")) return <p>This tutorial is not available for your role.</p>;
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
    <div className={styles.card}>
      <h2>{experience === "research" ? "Research orientation" : "Study operations tutorials"}</h2>
      <p>{experience === "research" ? "Review document-history guidance and open the pipeline tutorials below." : "These guides cover the study operations pages available to your role."}</p>
      <div style={{display:"flex",gap:9,flexWrap:"wrap"}}>
        {(experience === "research" ? [["Contracts information","contracts"],["Regulatory information","regulatory"],["Metadata tutorial","training-demo"],["How to report bugs","help-support"]] : [["Contracts tutorial","contracts"],["Regulatory tutorial","regulatory"],["Project management tutorial","project-management"],["Patient data review tutorial","patient-review"],["How to report bugs","help-support"]]).map(([label,page]) => <button type="button" key={label} className={styles.historyButton} onClick={() => onNavigate?.(page, page==="training-demo"?{tutorial:"metadata"}:{})}>{label}</button>)}
      </div>
      <p style={{fontSize:12}}>Page links are orientation shortcuts. Detailed guided tutorials for contracts, regulatory, project management and bug reporting are not yet implemented.</p>
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
        {index === 2 && <div style={{marginTop:20,paddingTop:18,borderTop:"1px solid #dce7ef"}}>
          <button type="button" aria-expanded={tutorialsOpen} aria-controls="data-capture-tutorials" onClick={() => setTutorialsOpen(open => !open)} style={{display:"flex",width:"100%",alignItems:"center",justifyContent:"space-between",gap:12,padding:"7px 0",border:0,background:"transparent",color:"#24597b",fontWeight:750,cursor:"pointer",textAlign:"left"}}>
            <span>Interactive workflow tutorials</span>
            {tutorialsOpen ? <ChevronUp size={19}/> : <ChevronDown size={19}/>}
          </button>
          {tutorialsOpen && <div id="data-capture-tutorials" style={{paddingTop:12}}>
          <p style={{margin:"0 0 14px",fontSize:13}}>Practice with synthetic data. These tutorials do not change your ATLAS patient database.</p>
          <label style={{display:"flex",alignItems:"center",gap:10,fontSize:13,marginBottom:16}}>
            <input type="checkbox" checked={guided} onChange={event=>setGuided(event.target.checked)}/>
            Start with guided step-by-step instructions
          </label>
          <div style={{display:"grid",gap:12}}>
            {TUTORIALS.filter(row => experience === "research" || row[0] === "patient").map(([id,tutorialTitle,tutorialDescription,TutorialIcon]) => <div key={id} style={{display:"flex",gap:14,alignItems:"center",flexWrap:"wrap",border:"1px solid #dce7ef",borderRadius:10,padding:14,background:"#f7fbfe"}}>
              <TutorialIcon size={23} color="#28678e"/>
              <div style={{flex:"1 1 220px"}}><strong>{tutorialTitle}</strong><p style={{fontSize:13,margin:"5px 0 0"}}>{tutorialDescription}</p></div>
              <button type="button" className={styles.historyButton} onClick={()=>setActive(id)}><BookOpen size={16}/> Start tutorial</button>
            </div>)}
          </div>
          </div>}
        </div>}
      </div>
    ))}
  </section>;
}
