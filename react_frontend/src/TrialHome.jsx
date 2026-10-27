import { ArrowRight, Database, FileSignature, GraduationCap, ShieldCheck, ClipboardList } from "lucide-react";
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

export default function TrialHome({ onNavigate, experience = "research" }) {
  const modules = experience === "administration" ? [...MODULES].sort((a,b)=>["contracts","regulatory","site-training","data-capture"].indexOf(a.key)-["contracts","regulatory","site-training","data-capture"].indexOf(b.key)) : [...MODULES].sort((a,b)=>["data-capture","site-training","regulatory","contracts"].indexOf(a.key)-["data-capture","site-training","regulatory","contracts"].indexOf(b.key));
  const visibleModules = experience === "research" ? modules.map(m => (["contracts","regulatory"].includes(m.key) ? {...m, description:"View document history (read-only)."} : m)) : modules.map(m => m.key === "data-capture" ? {...m, description:"Patient Data Review and annotations. Research processing is reserved for research users."} : m);
  return (
    <div>
      <div className={styles.topRow}>
        <section className={styles.heading}>
          <span>ATLAS CLINICAL TRIAL PLATFORM</span>
          <h1>{experience === "administration" ? "Administration & Oversight" : "Clinical & Research Workspace"}</h1>
          <p>{experience === "administration" ? "Coordinate study operations, document reviews and oversight." : "Manage research data, site activities, and assigned deliverables."}</p>
        </section>
      </div>
      <button type="button" onClick={() => onNavigate("project-management")} style={{display:"flex",alignItems:"center",gap:10,marginBottom:22,padding:"12px 18px",border:0,borderRadius:9,background:"#2373a7",color:"white",fontWeight:750,cursor:"pointer"}}><ClipboardList size={18}/> {experience === "administration" ? "Open Project Management" : "Open My Project Work"} <ArrowRight size={16}/></button>
      <section className={styles.grid} style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        {visibleModules.map(module => {
          const Icon = module.icon;
          return (
            <article className={styles.card} key={module.key}>
              <div className={styles.icon}><Icon size={29} strokeWidth={1.8} /></div>
              <h2>{module.title}</h2>
              <p>{module.description}</p>
              <button type="button" onClick={() => onNavigate(experience !== "research" && module.key === "data-capture" ? "patient-review" : module.key)}>
                <span>Open {module.title}</span><ArrowRight size={17} />
              </button>
            </article>
          );
        })}
      </section>
    </div>
  );
}
