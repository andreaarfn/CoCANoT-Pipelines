import React from "react";
import { ArrowRight, ClipboardList, FileSignature, ShieldCheck, GraduationCap, Database } from "lucide-react";

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

    </header>
    <AgileBoard experience={experience} siteId={siteId}/>
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

// Early project-management board: tasks persist per local application installation.
// Not a shared cross-site task service or authorization boundary.
const LANES=[["backlog","Backlog"],["todo","To do"],["in_progress","In progress"],["review","In review"],["done","Done"]];
const TYPES=["Contracts","Regulatory","Project Management","Site Initiation & Training","Data Capture & Monitoring"];
const STORE="atlas.project.tasks.v1";
function loadTasks(){try{const saved=JSON.parse(localStorage.getItem(STORE)||"[]");return Array.isArray(saved)?saved:[]}catch{return []}}
function AgileBoard({experience,siteId}){
 const [tasks,setTasks]=React.useState(loadTasks);
 const [title,setTitle]=React.useState("");
 const [category,setCategory]=React.useState("Project Management");
 const [assignee,setAssignee]=React.useState("");
 const [due,setDue]=React.useState("");
 const [filter,setFilter]=React.useState("All categories");
 React.useEffect(()=>{localStorage.setItem(STORE,JSON.stringify(tasks))},[tasks]);
 const update=(id,patch)=>setTasks(prev=>prev.map(task=>task.id===id?{...task,...patch,updatedAt:new Date().toISOString()}:task));
 const add=event=>{event.preventDefault();if(!title.trim())return;setTasks(prev=>[...prev,{id:crypto.randomUUID(),title:title.trim(),category,assignee:assignee.trim(),due,siteId,stage:"backlog",createdAt:new Date().toISOString()},]);setTitle("");setAssignee("");setDue("")};
 const visible=tasks.filter(x=>filter==="All categories"||x.category===filter);
 return <section style={{marginTop:25,padding:"22px 18px",background:"#fff",border:"1px solid #d6e2eb",borderRadius:13}}>
  <div style={{display:"flex",alignItems:"start",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
   <div><h2 style={{fontSize:20,margin:"0 0 5px"}}>Agile task board</h2><p style={{fontSize:13,color:"#647e91",margin:"0 0 15px"}}>Track tasks from backlog through review to completion. Use the stage menu to move cards.</p></div>
   <select aria-label="Filter board by category" value={filter} onChange={e=>setFilter(e.target.value)} style={{padding:9,borderRadius:7,border:"1px solid #c9d7e2"}}>{["All categories",...TYPES].map(v=><option key={v}>{v}</option>)}</select>
  </div>
  <form onSubmit={add} style={{display:"grid",gridTemplateColumns:"minmax(190px,2fr) minmax(145px,1fr) minmax(145px,1fr) 140px auto",gap:9,alignItems:"end",margin:"8px 0 22px"}}>
   <label style={{display:"grid",gap:5,fontSize:11,fontWeight:700}}>Task<input required value={title} onChange={e=>setTitle(e.target.value)} placeholder="Add a task" style={{padding:10,border:"1px solid #c9d7e2",borderRadius:7,minWidth:0}}/></label>
   <label style={{display:"grid",gap:5,fontSize:11,fontWeight:700}}>Category<select value={category} onChange={e=>setCategory(e.target.value)} style={{padding:10,border:"1px solid #c9d7e2",borderRadius:7,minWidth:0}}>{TYPES.map(t=><option key={t}>{t}</option>)}</select></label>
   <label style={{display:"grid",gap:5,fontSize:11,fontWeight:700}}>Assignee<input value={assignee} onChange={e=>setAssignee(e.target.value)} placeholder="User ID or name" style={{padding:10,border:"1px solid #c9d7e2",borderRadius:7,minWidth:0}}/></label>
   <label style={{display:"grid",gap:5,fontSize:11,fontWeight:700}}>Due date<input type="date" value={due} onChange={e=>setDue(e.target.value)} style={{padding:9,border:"1px solid #c9d7e2",borderRadius:7,minWidth:0}}/></label>
   <button type="submit" style={{padding:"11px 16px",background:"#246fa2",border:0,borderRadius:7,color:"white",cursor:"pointer",fontWeight:800}}>Add task</button>
  </form>
  <div style={{display:"grid",gridTemplateColumns:"repeat(5,minmax(180px,1fr))",gap:10,overflowX:"auto",paddingBottom:5}}>
   {LANES.map(([key,label])=><div key={key} style={{background:"#f3f7fa",border:"1px solid #dfe8ee",borderRadius:10,padding:10,minHeight:205}}>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12,gap:5}}><strong style={{fontSize:12}}>{label}</strong><span style={{fontSize:11,color:"#638093"}}>{visible.filter(x=>x.stage===key).length}</span></div>
    {visible.filter(x=>x.stage===key).map(task=><article key={task.id} style={{background:"white",border:"1px solid #d4e0e9",borderRadius:9,padding:11,marginBottom:9,boxShadow:"0 2px 5px rgba(28,61,84,.05)"}}>
     <span style={{fontSize:10,color:"#557f9d"}}>{task.category}</span><strong style={{display:"block",fontSize:12,margin:"5px 0",overflowWrap:"anywhere"}}>{task.title}</strong>
     <div style={{fontSize:11,color:"#61798b",marginBottom:8}}>Site: {task.siteId||"Unassigned"}{task.assignee?" · "+task.assignee:""}{task.due?" · Due "+task.due:""}</div>
     <select aria-label={"Move "+task.title+" to stage"} value={task.stage} onChange={e=>update(task.id,{stage:e.target.value})} style={{width:"100%",fontSize:11,padding:6,border:"1px solid #cedbe5",borderRadius:6}}>{LANES.map(([id,text])=><option key={id} value={id}>{text}</option>)}</select>
     <button type="button" onClick={()=>{if(window.confirm("Delete this task?"))setTasks(prev=>prev.filter(x=>x.id!==task.id))}} style={{border:0,background:"none",fontSize:11,color:"#8b5862",marginTop:8,cursor:"pointer"}}>Delete</button>
    </article>)}
   </div>)}
  </div>
  <p style={{fontSize:11,color:"#7b8e9d",marginTop:15}}>Prototype: board tasks are stored in this application's local storage. They are not yet synchronized between people or connected to Needs Attention.</p>
 </section>
}
