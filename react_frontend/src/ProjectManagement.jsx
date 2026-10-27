import { ArrowRight, ClipboardList, FileSignature, ShieldCheck, GraduationCap, Database, Info } from "lucide-react";

const THEMES = {
  administration: {
    eyebrow: "ADMINISTRATION & OVERSIGHT",
    title: "Project management",
    description: "Coordinate study deliverables, reviews, and site readiness across organizations you are authorized to oversee.",
    sections: [
      {title:"Document coordination",description:"Follow up on contracts and regulatory submissions.",items:[["Contracts","contracts",FileSignature],["Regulatory","regulatory",ShieldCheck]]},
      {title:"Study operations",description:"Review training and data-monitoring workstreams.",items:[["Site Initiation & Training","site-training",GraduationCap],["Data Capture & Monitoring","data-capture",Database]]},
    ],
    attention:"Review your assigned actions and pending approvals in Needs Attention.",
  },
  research: {
    eyebrow: "CLINICAL & RESEARCH TEAM",
    title: "My project work",
    description: "Prepare your site's study deliverables, complete training, and track documents awaiting review.",
    sections: [
      {title:"My site deliverables",description:"Prepare documents and track submission progress.",items:[["Regulatory","regulatory",ShieldCheck],["Contracts","contracts",FileSignature]]},
      {title:"Research readiness",description:"Complete training and manage clinical research data.",items:[["Data Capture & Monitoring","data-capture",Database],["Site Initiation & Training","site-training",GraduationCap]]},
    ],
    attention:"Open Needs Attention to follow up on items requiring action from your account.",
  },
};

export default function ProjectManagement({ experience = "research", siteId, onNavigate }) {
  const view = THEMES[experience] || THEMES.research;
  return <div style={{maxWidth:1180,margin:"0 auto",color:"#213f56"}}>
    <header style={{marginBottom:24}}>
      <span style={{letterSpacing:1.4,fontSize:11,fontWeight:800,color:"#2774a4"}}>{view.eyebrow}</span>
      <h1 style={{fontSize:30,margin:"8px 0"}}>{view.title}</h1>
      <p style={{fontSize:14,color:"#62798c",maxWidth:730}}>{view.description}</p>
      <div style={{display:"inline-flex",gap:8,alignItems:"center",padding:"8px 12px",borderRadius:8,background:"#eff6fb",fontSize:12}}>
        <Info size={15}/> Active site: <strong>{siteId}</strong> · View foundation; user-level assignments will follow.
      </div>
    </header>
    {view.sections.map(section=><section key={section.title} style={{marginBottom:22,padding:20,border:"1px solid #d6e2eb",borderRadius:13,background:"#fff"}}>
      <h2 style={{margin:"0 0 4px",fontSize:18}}>{section.title}</h2>
      <p style={{margin:"0 0 17px",fontSize:13,color:"#6c8292"}}>{section.description}</p>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(225px,1fr))",gap:12}}>
        {section.items.map(([label,page,Icon])=><button key={page} type="button" onClick={()=>onNavigate(page)}
          style={{display:"flex",alignItems:"center",gap:12,textAlign:"left",padding:16,borderRadius:10,border:"1px solid #cfdee8",background:"#f9fcfe",color:"#285a7a",cursor:"pointer"}}>
          <Icon size={19}/><span style={{flex:1,fontSize:13,fontWeight:750}}>{label}</span><ArrowRight size={15}/>
        </button>)}
      </div>
    </section>)}
    <section style={{padding:20,border:"1px solid #c5dae9",borderRadius:13,background:"#eef6fc",display:"flex",gap:14,alignItems:"center",flexWrap:"wrap"}}>
      <ClipboardList size={24}/><div style={{flex:1,minWidth:220}}><strong>Needs Attention</strong><p style={{fontSize:13,margin:"4px 0 0",color:"#546f82"}}>{view.attention}</p></div>
      <button type="button" onClick={()=>onNavigate("needs-attention")} style={{border:0,borderRadius:8,padding:"11px 17px",background:"#236c9f",color:"white",fontWeight:700,cursor:"pointer"}}>Open Needs Attention</button>
    </section>
  </div>;
}
